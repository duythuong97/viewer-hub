# Viewer Hub — Tài liệu thiết kế

> Phiên bản: 0.1 (draft) · Nền tảng: Windows 10/11 (chính), macOS (dev) · Ngày: 2026-11-13
> Liên quan: [box-mcp-design.md](box-mcp-design.md) (box-mcp v0.3) — tài liệu này đề xuất tách UI của box-mcp vào viewer-hub (§9).

---

## 1. Tổng quan

**Viewer Hub** là một web app gom toàn bộ phần *xem* của các tool hiện có (code-map, ocr-demo, csv-viewer, mkdocs, UI của box-mcp) vào một chỗ, chạy trên máy user **không cần** Solr, Docker, IIS, hay source code của các tool.

Phần *extract* (OCR, index Solr, quét code) vẫn ở các repo cũ và chạy trên máy của tác giả; kết quả được đóng thành **data pack** (`.sapack`) để phát cho user.

### 1.1 Mục tiêu
- User chạy được trên máy của họ, không phụ thuộc máy tác giả phải bật.
- User xem data tác giả phát (pack) **và** tự thêm data của họ (CSV, markdown).
- **Cập nhật phiên bản mới không làm mất data của user** (§7, §8).
- Qua được security scan của máy công ty: không exe tự đóng gói, không tải code lúc chạy, không native addon (§10).
- Cung cấp một MCP server (`hub_mcp`) cho mọi data, để AI agent (Copilot, Claude, Copilot Studio qua box-mcp) dùng được.

### 1.2 Ngoài phạm vi
- Extract/OCR/index trên máy user (vẫn làm trên máy tác giả; user nào cần thì dùng repo extract).
- Full-text search tương đương Solr (fuzzy, Kuromoji) — chấp nhận chất lượng của SQLite FTS5 (§6.2).
- Nhiều user cùng ghi trên một data dir (chế độ hosted nhiều user để giai đoạn sau).

---

## 2. Kiến trúc tổng thể

```
 MÁY TÁC GIẢ (extract)                     MÁY USER
 ┌─────────────────────────────┐ .sapack ┌──────────────────────────────────────────────┐
 │ ocr-demo: OCR → Solr → export├────────►│ viewer-hub (python.exe chính hãng + source)  │
 │ code-map: extractor          │  (Box)  │  waitress 127.0.0.1:8700                     │
 │ mkdocs build / CSV gốc       │         │   /             portal + settings            │
 └─────────────────────────────┘         │   /code-map     React + API (đọc sqlite)     │
                                          │   /ocr-search   search (SQLite FTS5)         │
                                          │   /csv          CSV workspace                │
                                          │   /docs/<site>  site tĩnh (origin riêng)     │
                                          │   /x/<addon>    addon (vd. MCP Bridge)       │
                                          │   /mcp          hub_mcp (HTTP) · stdio       │
                                          │                                              │
                                          │  APP  %LOCALAPPDATA%\Programs\ViewerHub\     │
                                          │  DATA %LOCALAPPDATA%\ViewerHub\   ← tách hẳn │
                                          └───────────────┬──────────────────────────────┘
                                                          │ fetch từ trình duyệt
                                          ┌───────────────▼──────────────┐
                                          │ box-mcp-daemon 127.0.0.1:7801│ (repo riêng)
                                          └──────────────────────────────┘
```

### Nguyên tắc cốt lõi
1. **App và data tách thư mục.** Update chỉ thay thư mục app, không bao giờ ghi đè thư mục data.
2. **Viewer chỉ đọc pack.** Pack bất biến; mọi thứ user tạo ra nằm ngoài pack.
3. **Phân biệt data nguồn và data dẫn xuất.** Nguồn (file user upload, ghi chú) không bao giờ tự xóa; dẫn xuất (index, site đã build) xóa và tạo lại được.
4. **Hợp đồng duy nhất giữa extract và viewer là `pack-schema`** có version.
5. **Mọi thao tác với data do user bấm**; không có tác vụ nền tự gom/gửi data.

---

## 3. Repo

| Repo | Ngôn ngữ | Nội dung | Đầu ra |
|---|---|---|---|
| `viewer-hub` (mới) | Python + React tĩnh | portal, code-map viewer + MCP, ocr-search, csv, docs, giám sát, addon host (SVN, Sơ đồ… là addon) (`/x/<id>`), `hub_mcp`, `contracts/pack-schema` | zip release |
| `my-bridge` (box-mcp-daemon) | Node/TS | daemon headless, `api/openapi.yaml`, flow Copilot Studio | tự build addon `mcp-bridge` (addon.json, GUIDE.md, trang, chương trình) → `dist/mcp-bridge-<ver>.zip`; viewer-hub chỉ nhận zip (`addons/` = addon mặc định) |
| `code-map` | Python + Node/.NET | chỉ còn extractor + `export-pack` | `codemap/` trong pack |
| `ocr-demo` | Python + Solr | OCR, indexing, `export-solr` | `search/` trong pack |
| `csv-viewer` | — | đã thay bằng CSV của viewer-hub (nhánh `chore/move-to-viewer-hub`) | — |

```
viewer-hub/
├─ viewer_hub/
│  ├─ core/        # paths, config, hub.db, migrations, backup, lock, MCP chung, mã mở khoá premium
│  ├─ packs/       # import, validate, kích hoạt version
│  ├─ app/         # app factory, registry module, SPA, DispatcherMiddleware, portal, 2 origin
│  ├─ codemap/     # chuyển từ code-map: phần đọc + API + business/ + MCP
│  ├─ fsearch/     # F-Search, port từ ocr-demo main, backend SQLite
│  ├─ csv/         # CSV workspace
│  ├─ docs/        # docs workspace (mkdocs build)
│  ├─ monitor/     # Giám sát: lời gọi MCP, sức khoẻ addon (monitor.db)
│  ├─ addons/      # addon host: manifest, cài/gỡ, chữ ký, runner, proxy, gateway (docs/addons.md)
│  └─ migrations/  # 0001_init.sql, 0002_….py
├─ web/            # toàn bộ giao diện (React SPA) + design system M3 — build vào viewer_hub/static/dist
├─ addons/         # addon mặc định: *.zip đi kèm mọi bản build, tự cài khi mở (zip đã ký, commit)
├─ packaging/      # build bản Windows, addon, mã mở khoá, quét bảo mật
├─ justfile        # mọi lệnh của repo (uv + just)
├─ vendor/         # wheel đã ghim hash (chỉ có trong release)
└─ tests/migrations/fixtures/<version>/   # data dir mẫu của từng bản đã phát hành
```

---

## 4. Chế độ chạy

| | **Local** (chính) | **Hosted** | **Browser-only** (spike) |
|---|---|---|---|
| Chạy ở | Máy user, `python.exe` embeddable | Server luôn bật | Pyodide trong trình duyệt |
| Data user | `%LOCALAPPDATA%\ViewerHub\` | Volume server, tách theo user | OPFS của trình duyệt |
| MCP | stdio + HTTP | HTTP | ✗ |
| Ghi chú | Mặc định cho Windows công ty | Cần đăng nhập nếu cho upload | Tự host Pyodide + wheel, cần kiểm chứng FTS5 |

Tài liệu này mô tả chi tiết chế độ **Local**; §8.6 nói khác biệt về data của hai chế độ còn lại.

---

## 5. Data pack

### 5.1 Cấu trúc `.sapack` (zip)
```
pack.json
codemap/      codemap.sqlite  graph.sqlite  manifest.json
search/       search.sqlite
csv/<dataset>/   dataset.json  source.csv  data.sqlite   (index tạo sẵn lúc đóng pack)
docs/<site>/     site.json  site/…   (build sẵn lúc đóng pack; không kèm src/)
source/       (tùy chọn — để code-map xem snippet file nguồn)
```

### 5.2 `pack.json`
```json
{
  "format": 1,
  "id": "core-system",
  "version": "2026.11.13-1",
  "title": "Core System",
  "builtAt": "2026-11-13T07:00:00Z",
  "components": {
    "codemap": { "path": "codemap/", "schema": 3, "contractVersion": "3.0" },
    "search":  { "path": "search/search.sqlite", "schema": 1, "docCount": 18234 },
    "csv":     [ { "id": "employees", "schema": 1 } ],
    "docs":    [ { "id": "spec", "schema": 1 } ]
  },
  "sha256": { "codemap/codemap.sqlite": "…", "search/search.sqlite": "…" }
}
```
- `id` ổn định qua các lần phát hành; `version` tăng mỗi lần build.
- Pack có thể chỉ chứa một phần (ví dụ chỉ `csv`).

### 5.3 Import
1. Kiểm tra zip: chặn đường dẫn `..`/tuyệt đối (zip slip), giới hạn tổng dung lượng giải nén và tỉ lệ nén (zip bomb).
2. Chỉ cho phép phần mở rộng `.json .sqlite .csv .md .html .css .js .png .jpg .svg .woff2`; có file khác → từ chối cả pack.
3. Validate `pack.json` theo `pack-schema`; kiểm tra `sha256`.
4. Giải nén vào `packs\<id>\<version>.tmp\` → rename thành `packs\<id>\<version>\` (atomic).
5. Ghi bảng `packs` trong `hub.db`. Kích hoạt **chỉ khi version mới ≥ version đang dùng** (so sánh tự nhiên: `1.10 > 1.9`); pack cũ hơn (vd. pack đóng sẵn trong bản phát hành cũ) được nạp nhưng không bật. Version cũ giữ lại; Cài đặt → **Dùng bản này** để quay lại.
6. Bất biến khi import (có test): không ghi vào `workspace/`, `user/` hay `config.yaml`; không import khi đang chỉ đọc; đăng ký lỗi thì xoá thư mục vừa giải nén; id `local` được dành riêng; `repair` bật version mới nhất của mỗi pack.
7. Ghi chú code-map gắn theo `pack_id` + node id. Node không còn trong pack mới thì ghi chú vẫn nằm trong `knowledge.sqlite` (không bị xoá) nhưng **chưa có màn hình liệt kê** các ghi chú này — việc cần làm.

---

## 6. Thành phần

### 6.1 code-map viewer
- Phần đọc (`codemap/` ≈ 3.400 dòng), `web/backend` (≈ 1.500 dòng), frontend React, MCP — chuyển từ repo code-map.
- Bỏ phụ thuộc vào `code_tree_exporter.pipeline.load_config`: settings đọc từ `pack.json` + `hub.db`.
- Nhiều pack code-map: mỗi request mang `pack_id`; không đọc settings ở cấp module (khác bản hiện tại dùng `lru_cache` lúc import).
- Ghi chú/knowledge của user: `user\codemap\<pack_id>\knowledge.sqlite` (§7.4), không ghi vào pack.
- `/api/snippet` cần `source/` trong pack; không có thì trả `source_unavailable`, UI ẩn nút xem file.
- ERD (`codemap/erd.py`, thuần, không Flask): từ cạnh `REFERENCES` (cột FK → cột được tham chiếu, `properties_json` có `constraint`, `position`, `source`, `delete_rule`) và `TABLE -CONTAINS-> COLUMN`; quanh một bảng (độ sâu 1–2, cả hai chiều) hoặc cả schema / system, tối đa 80 bảng (`truncated`). Xuất Mermaid `erDiagram` và DBML. Thêm chế độ `tables=[…]` (đúng một tập bảng, khoá ngoại chỉ giữa chúng, `outside_tables` đếm bảng ngoài tập nối tới) cho mục **Dữ liệu** của trang luồng (`business/data.py`, `GET /business/flows/<id>/data`: bảng + dòng CRUD của luồng đang mở, tối đa 40 bảng; id tính năng cho ma trận luồng × bảng, dùng cho export / MCP). ERD cả cơ sở dữ liệu là addon `erd`, đọc qua export `erd_model` / `db_objects` / `table_usage` của module (`codemap/exports.py`, `docs/addons.md` §3.2); trang `#/erd` cũ chuyển sang addon. Còn lệnh `viewer-hub erd` và MCP `codemap_erd` (alias một bản, rồi bỏ, thay bằng `erd_diagram` của addon). Pack extract cũ không có `REFERENCES` vẫn xem được bảng/cột, kèm thông báo cần extract lại.

### 6.2 ocr-search (port từ ocr-demo `main`)
- Giữ `parse_form` và cấu trúc kết quả; giao diện viết lại bằng React (`web/src/modules/fsearch/`); thay `pysolr` bằng `SqliteSearchBackend` trả đúng cấu trúc cũ (`docs`, `facets`, `highlighting`, `groups`, `num_found`).
- `search.sqlite`: bảng `docs` (mọi stored field, kể cả `image_orc_text`), `fts_word` (`unicode61 remove_diacritics 2`), `fts_tri` (`trigram` cho tiếng Nhật/chuỗi con).
- Không hỗ trợ: fuzzy, parser lucene, `fq`/`bf` tự do, debugQuery → ẩn khỏi UI.
- "Open local" (`explorer /select`) tắt mặc định; chỉ bật khi user cấu hình `localFileRoot`.

### 6.3 CSV workspace
1. User kéo thả file `.csv`.
2. Nhận dạng encoding (`chardet`), dấu phân cách (`csv.Sniffer`), header, kiểu cột (1.000 dòng đầu).
3. Lưu nguyên file vào `workspace\csv\<id>\source.csv` (**data nguồn**).
4. Nạp stream vào `workspace\csv\<id>\data.sqlite` + FTS5 (**data dẫn xuất**).
5. Tự sinh `dataset.json` (mọi cột hiển thị + lọc được, toán tử `IN`); user chỉnh cột/toán tử/tên hiển thị → lưu vào `dataset.json` (**data nguồn**: cấu hình của user).
6. Export kết quả: escape ô bắt đầu bằng `= + - @`.
7. CSV từ data pack (`--csv` khi đóng pack): cột + `data.sqlite` tạo sẵn lúc đóng pack; hiện chung danh sách, id `<pack>--<id>`, nhãn *Data pack*, chỉ đọc (không cấu hình cột, không xoá).

### 6.4 Docs workspace
1. Tạo site: tên + slug + chọn thư mục (`webkitdirectory`) hoặc `.zip` → `workspace\docs\<id>\src\` (**nguồn**).
2. Build bằng `mkdocs.commands.build` trong process → `workspace\docs\<id>\site\` (**dẫn xuất**).
   - Có `mkdocs.yml` thì dùng, nhưng **xóa `hooks`, chỉ cho plugin `search`, theme cố định** (hooks/plugin chạy được code Python tùy ý).
   - Không có thì sinh: nav theo cây thư mục, tiêu đề từ `# heading` đầu.
3. Site từ data pack (`--docs` khi đóng pack): build sẵn, pack chỉ chứa `site.json` + `site/`; id `<pack>--<id>`, chỉ đọc (không build lại, không xoá).
4. Site chỉ được phục vụ ở origin nội dung `http://localhost:<port>/docs/<id>/view/`, còn app ở `http://127.0.0.1:<port>` → script trong markdown không đọc được token của `/bridge`, daemon từ chối origin này. (Đã thử CSP `sandbox`: mkdocs-material hỏng vì cần localStorage.)

### 6.5 MCP
Mỗi nguồn có MCP riêng (không có `hub_mcp` chung), tất cả chỉ đọc:
- **Code map:** HTTP `/code-map/mcp`, stdio `viewer-hub mcp codemap`. Tool `codemap_search`, `codemap_impact`, `codemap_trace_flow`, `codemap_file_context`, `codemap_current_behavior`, `codemap_check_terms`, `codemap_status`, `codemap_erd`; `propose_*` chỉ có khi có token.
- **F-Search (full-text search):** HTTP `/ocr-search/mcp`, stdio `viewer-hub mcp search`. Chỉ 2 tool để tiết kiệm token: `search_documents` (mỗi kết quả 1 dòng metadata + 1 đoạn trích ≤180 ký tự, mặc định 5) và `read_document` (đoạn quanh từ khoá, hoặc lát cắt có `offset`). Văn bản thuần, đánh dấu «».
- stdio mở `hub.db` chỉ đọc (không migration khi web đang chạy). HTTP chỉ nhận `Origin` loopback.
- CSV có MCP (`csv_list`, `csv_search` tại `/csv/mcp`, chỉ file bật "Cho AI đọc"); Docs chưa có, thêm theo GUIDELINE §10.5 khi cần.

---

## 7. Lưu trữ data trên máy user

### 7.1 Tách thư mục app và data

| Mục đích | Đường dẫn | Update có đụng tới? |
|---|---|---|
| Chương trình | `%LOCALAPPDATA%\Programs\ViewerHub\<version>\` | Thêm thư mục version mới |
| Con trỏ version | `%LOCALAPPDATA%\Programs\ViewerHub\current.txt` | Có (chỉ 1 dòng) |
| Launcher | `%LOCALAPPDATA%\Programs\ViewerHub\viewer-hub.cmd` | Có |
| Cấu hình user | `%APPDATA%\ViewerHub\config.yaml` | **Không** (chỉ migration, §8.3) |
| Data | `%LOCALAPPDATA%\ViewerHub\` | **Không** (chỉ migration) |

- Đổi vị trí data: biến môi trường `VIEWER_HUB_HOME` hoặc `--data-dir`. Thứ tự ưu tiên: tham số dòng lệnh > biến môi trường > `config.yaml` > mặc định.
- **Không có "portable mode" để data trong thư mục app** — đó là nguyên nhân phổ biến nhất làm mất data khi giải nén đè bản mới.
- Data không đặt dưới `Program Files`, không cần quyền admin.

### 7.2 Cấu trúc thư mục data
```
%LOCALAPPDATA%\ViewerHub\
├─ hub.db                         # registry: packs, datasets, sites, settings (SQLite, WAL)
├─ hub.lock                       # khóa một instance
├─ packs\
│  └─ core-system\
│     ├─ 2026.11.01-1\            # bất biến, chỉ đọc
│     └─ 2026.11.13-1\
├─ workspace\
│  ├─ csv\<id>\
│  │  ├─ source.csv               # NGUỒN
│  │  ├─ dataset.json             # NGUỒN (cấu hình user)
│  │  └─ data.sqlite              # DẪN XUẤT
│  └─ docs\<id>\
│     ├─ site.json                # NGUỒN
│     ├─ src\…                    # NGUỒN
│     └─ site\…                   # DẪN XUẤT
├─ user\
│  └─ codemap\<pack_id>\knowledge.sqlite   # NGUỒN (ghi chú của user)
├─ backups\
│  └─ 20261113-070000-from-0.3.0\          # tự tạo trước mỗi migration
├─ logs\
└─ tmp\                           # file tạm; xóa khi khởi động
```

### 7.3 Phân loại data

| Loại | Ví dụ | Mất thì sao | Quy tắc |
|---|---|---|---|
| **Nguồn** | `source.csv`, `dataset.json`, `src\`, `site.json`, `knowledge.sqlite`, `config.yaml` | Mất vĩnh viễn | Không bao giờ tự xóa; backup trước migration; có trong Export |
| **Dẫn xuất** | `data.sqlite`, `site\`, FTS index | Tạo lại được | Migration được phép xóa + rebuild; không backup; không export |
| **Registry** | `hub.db` | Mất danh sách/settings | Backup trước migration; dựng lại được một phần bằng cách quét `workspace\` + `packs\` (§8.5) |
| **Pack** | `packs\<id>\<version>\` | Import lại từ `.sapack` | Bất biến; không migration — app đọc theo `schema` của từng component |

Tách "nguồn" và "dẫn xuất" giúp migration đơn giản: phần lớn thay đổi format chỉ cần đánh dấu "rebuild" thay vì chuyển đổi data.

### 7.4 Data của user gắn với pack
- Ghi chú code-map lưu theo **khóa ổn định** (`pack_id` + `node_id` của graph), không theo `version`, nên khi kích hoạt pack version mới, ghi chú vẫn hiện.
- Node không còn trong pack mới → ghi chú thành **orphan**: vẫn giữ, hiện ở mục "Ghi chú không còn khớp" để user xem/xóa.

### 7.5 Ghi file an toàn
- File: ghi `tmp\<random>` → `flush` + `fsync` → `os.replace()` vào đích (atomic trên cùng ổ).
- SQLite: `journal_mode=WAL`, `synchronous=NORMAL`; thay đổi nhiều bước trong một transaction.
- Upload lớn (CSV, thư mục md): ghi vào `tmp\` trước, xong mới chuyển vào `workspace\`; lỗi giữa chừng không để lại dataset hỏng.
- Pack: mở SQLite `mode=ro` (đọc qua URI `file:…?mode=ro`).

### 7.6 Một instance
- `hub.lock` (khóa file độc quyền, `msvcrt.locking` trên Windows / `fcntl` trên macOS) ghi `pid`, `version`, `startedAt`.
- Instance thứ hai (kể cả **khác version**) thấy khóa → mở trình duyệt tới instance đang chạy rồi thoát. Ngăn bản cũ và bản mới cùng ghi lên data trong lúc update.

---

## 8. Update phiên bản

### 8.1 Ba loại version độc lập

| Version | Ở đâu | Khi nào tăng |
|---|---|---|
| App (`0.4.0`) | `viewer_hub/__init__.py` | Mỗi bản phát hành |
| Schema data (`hub_schema`) | `PRAGMA user_version` của `hub.db` + `schema` trong `dataset.json`/`site.json` | Khi đổi cấu trúc data user |
| Pack format (`format`, `components.*.schema`) | `pack.json` | Khi đổi format pack |

Mỗi bản app khai báo: `HUB_SCHEMA = 5` (schema nó ghi ra) và `PACK_FORMATS = {1}`, `COMPONENT_SCHEMAS = {"search": {1, 2}, …}` (những gì nó đọc được).

### 8.2 Quy trình update cho user
1. Admin build (`packaging/build.py`, README) → `ViewerHub-<ver>.zip` + `SHA256SUMS.txt`, gửi qua Box/chỗ phát hành.
2. User giải nén **cạnh bản cũ** (vd. `%LOCALAPPDATA%\Programs\ViewerHub\ViewerHub-<ver>\`) và mở `viewer-hub.cmd` của bản mới → migration tự chạy lần đầu (§8.3). Dữ liệu `%LOCALAPPDATA%\ViewerHub\` dùng chung mọi bản.
3. Tuỳ chọn: `setup.cmd` ghi `current.txt` + launcher chung `…\ViewerHub\viewer-hub.cmd` (đường dẫn cố định cho shortcut / MCP stdio).
4. Bản cũ giữ lại để rollback (mở `viewer-hub.cmd` của nó; nếu dữ liệu đã nâng cấp thì bản cũ chỉ đọc). Xoá bản cũ bằng tay khi không cần.

Không có auto-update, không có installer exe, không tải gì lúc chạy (§10).

### 8.3 Migration khi khởi động
```
lock → đọc user_version của hub.db
  ├─ = HUB_SCHEMA            → chạy bình thường
  ├─ < HUB_SCHEMA            → backup (§8.4) → chạy migration lần lượt → chạy bình thường
  └─ > HUB_SCHEMA (data mới hơn app, tức là downgrade)
                             → CHẾ ĐỘ CHỈ ĐỌC + banner "Data được tạo bởi bản mới hơn (x.y)"
                               không migration ngược, không ghi gì
```
- Migration **chỉ tiến** (forward-only), đánh số `migrations/0001_init.sql`, `0002_add_site_theme.py`, …; mỗi file một transaction, xong thì tăng `user_version`.
- Migration của file trong `workspace\` (ví dụ `dataset.json` v1 → v2): ghi file mới cạnh file cũ → `os.replace()`; file cũ đã có trong backup.
- Thay đổi data dẫn xuất: không chuyển đổi, chỉ đánh dấu `needs_rebuild = 1`; rebuild chạy nền sau khi app mở, UI hiện tiến độ; dataset/site chưa rebuild vẫn hiện, báo "đang tạo lại index".
- Migration lỗi: rollback transaction, khôi phục từ backup vừa tạo, mở **chế độ chỉ đọc** + hiện lỗi và đường dẫn backup. Không bao giờ để data ở trạng thái nửa chừng.
- `config.yaml`: key không biết thì **giữ nguyên** (không xóa); key đổi tên thì migration chép sang key mới và giữ key cũ một bản.

### 8.4 Backup
- Tự động trước mỗi migration: `backups\<yyyyMMdd-HHmmss>-from-<version>\`
  - `hub.db` và mọi `knowledge.sqlite`: dùng SQLite online backup (`sqlite3.Connection.backup`), không copy file thô khi đang mở.
  - `config.yaml`, mọi `dataset.json`, `site.json`.
  - **Không** copy `source.csv`, `src\` (migration không sửa file nguồn lớn; nếu migration nào cần sửa thì nó tự backup phần đó).
  - **Không** copy data dẫn xuất và pack.
- Giữ 5 backup gần nhất; dung lượng backup hiện trong Settings.
- Thủ công: `viewer-hub backup` / Settings → **Backup now**.
- Khôi phục: `viewer-hub restore <thư mục backup>` (chỉ khi không có instance chạy; trước khi restore lại tự backup trạng thái hiện tại).

### 8.5 Tự sửa khi registry hỏng
- `hub.db` hỏng hoặc mất → `viewer-hub repair`: tạo `hub.db` mới, quét `workspace\csv\*\dataset.json`, `workspace\docs\*\site.json`, `packs\*\*\pack.json` để đăng ký lại; đánh dấu mọi data dẫn xuất `needs_rebuild`.
- Vì vậy mọi metadata quan trọng của dataset/site được ghi **cả** trong file JSON cạnh data, không chỉ trong `hub.db`.

### 8.6 Rollback
- Chạy lại bản cũ: sửa `current.txt` hoặc chạy `<version-cũ>\viewer-hub.cmd`.
- Nếu bản mới đã migration → bản cũ thấy `user_version` lớn hơn → **chỉ đọc** (§8.3). Muốn ghi được ở bản cũ: `viewer-hub restore` backup tạo lúc migration (mất thay đổi làm sau khi update — UI cảnh báo rõ).

### 8.7 Export / Import workspace
- Settings → **Export workspace** → `.sapack` chứa toàn bộ data **nguồn** (CSV, docs src, cấu hình, ghi chú) + `pack.json` (`kind: "workspace"`).
- Dùng để chuyển máy, gửi cho người khác, hoặc tự backup ngoài máy.
- Import workspace: gộp theo `id`; trùng `id` → hỏi Ghi đè / Giữ cả hai (đổi `id`) / Bỏ qua.

### 8.8 Chế độ Hosted và Browser-only
| | Hosted | Browser-only |
|---|---|---|
| Data dir | Volume riêng của server, `workspace\<user>\…` | OPFS theo origin |
| Update | Thay image/thư mục app; volume giữ nguyên; migration như §8.3 | Thay file tĩnh; OPFS giữ nguyên |
| Rủi ro mất data | Volume không được mount lại | **Đổi domain/origin → mất hết**; user/IT xóa site data; trình duyệt tự dọn khi thiếu dung lượng |
| Biện pháp | Backup volume theo lịch của server | Giữ origin cố định; gọi `navigator.storage.persist()`; nhắc Export workspace định kỳ (banner nếu > 14 ngày chưa export) |

### 8.9 Kiểm thử migration
- Mỗi bản phát hành lưu một data dir mẫu vào `tests/migrations/fixtures/<version>/` (có CSV, docs site, ghi chú, pack).
- CI: với mỗi fixture → chạy app mới → kiểm tra migration xong, đủ dataset/site/ghi chú, đọc được, rebuild được.
- Kiểm tra downgrade: data của bản mới + app bản cũ → phải vào chế độ chỉ đọc, không ghi file nào.

---

## 9. Tích hợp box-mcp

- Daemon (`box-mcp-daemon`) headless: discovery thủ công, registry, process manager, Box transport, executor, approval, audit. Local API REST + SSE tại `127.0.0.1:7801`, hợp đồng `api/openapi.yaml` có version.
- **MCP Bridge** là một **addon daemon** do repo `my-bridge` build (`packaging/build_addon.mjs`, docs/addons.md), trang `/x/mcp-bridge`; Viewer Hub relay `/x/mcp-bridge/api/…` sang kênh quản trị của daemon.
- Xác thực: Viewer Hub (server) nói chuyện với daemon qua **kênh quản trị** của cùng user hệ điều hành — named pipe `\\.\pipe\McpBridge-<user>` (Windows) / Unix socket `admin.sock` 0600 (Mac/Linux) — với quyền chủ sở hữu: không ghép nối, không `bridge confirm`. Trình duyệt chỉ gọi `/x/mcp-bridge/api/…` của Viewer Hub (`addons/routes.py`; ghi cần header `X-Viewer-Hub` và Origin của app), không chạm tới daemon; CSP `connect-src 'self'`. Tool mới (kể cả `viewer-*`) luôn bắt đầu ở *Tắt*: user tự bật, từng tool hoặc *Cho phép tất cả* / *Tắt tất cả* trên trang bridge (`PUT /api/tools/policy`, chỉ chủ máy). Cổng HTTP 7801 + ghép nối mã 6 số vẫn còn cho công cụ khác.
- Thao tác nguy hiểm (thêm/sửa server, policy `allow`, token, `allowedOrigins`) phải xác nhận trên daemon (CLI/trang `/status` của daemon).
- MCP của viewer-hub (§6.5) đăng ký vào bridge như mọi server khác: HTTP loopback hoặc stdio qua `python.exe` (bridge từ chối `.cmd`).
- **Đã làm (2026-11-14):** daemon ở repo `my-bridge`; từ 2026-11-14 là addon `mcp-bridge` (premium, mở bằng mã VH2 `just unlock bridge`; GUIDELINE §4.5). Addon (addon.json, trang, GUIDE.md) nằm hẳn ở my-bridge (`addon/`), viewer-hub không còn code nào của bridge. Giao diện gọn lại: bảng điều khiển addon (chạy/dừng, tự chạy, gateway, cài đặt, log) + tab Server (bật/tắt, làm mới, xoá) và Duyệt (approve/reject), cập nhật qua SSE. Gateway tự đăng ký MCP của Hub (và của các addon) vào bridge. Hợp đồng: `my-bridge/api/openapi.yaml`.
- Data của bridge (`bridge.db`, log) thuộc daemon, nằm ở `%LOCALAPPDATA%\McpBridge\`, tuân theo cùng nguyên tắc §7–§8.
- **Cần IT/Security phê duyệt trước khi chạy trên máy công ty** (xem box-mcp §1.3).

---

## 10. Ràng buộc bảo mật (máy công ty scan chặt)

| Không dùng | Lý do | Dùng thay |
|---|---|---|
| PyInstaller, Nuitka, Node SEA, `bun --compile`, Tauri | Exe tự đóng gói, chưa ký, tự giải nén | `python.exe` embeddable của python.org, `node.exe` chính thức + source |
| `pip`/`npm`/`micropip`/CDN lúc chạy | Tải và chạy code | `vendor\` trong release, ghim hash; CSP chặn domain ngoài |
| Native addon (`better-sqlite3`, `@napi-rs/keyring`) | Binary tải lúc cài | `sqlite3` (stdlib), `node:sqlite` (Node 24) |
| Tự quét config của Claude/Cursor/VS Code | Giống hành vi đánh cắp thông tin | User tự chọn file; chỉ đọc `mcpServers`, bỏ qua `env` |
| Credential Manager | Truy cập kho credential | Không giữ secret; tham chiếu `${env:X}` |
| `cmd.exe /c`, PowerShell, process ẩn | Hay bị gắn cờ | Spawn trực tiếp, `shell:false` |
| Autostart `HKCU\…\Run` | Persistence | User tự mở |
| `mkdocs.yml` có `hooks`/plugin lạ | Chạy code tùy ý | Xóa `hooks`, allowlist plugin |
| Zip có mật khẩu | DLP không đọc được | Phân quyền bằng Box |
| Obfuscate, `eval`, payload base64 | Dấu hiệu malware | Minify thường |

Dependency runtime của viewer-hub: `flask`, `jinja2`, `markupsafe`, `werkzeug`, `waitress`, `pyyaml`, `markdown`, `mkdocs`, `mkdocs-material`, `chardet` (MCP tự viết, không dùng SDK). Bản phát hành xoá mọi native extension của thư viện (dùng fallback thuần Python), kèm SBOM + SHA-256. Đã kiểm chứng chạy đủ tính năng trong sandbox chặn mọi mạng ngoài localhost.

Log: không ghi nội dung tài liệu, giá trị cell CSV, token. Server bind `127.0.0.1`.

---

## 11. Lộ trình

| Giai đoạn | Nội dung | Trạng thái (2026-11-13) |
|---|---|---|
| **V0** | Repo, `core/` (paths, lock, hub.db, migration, backup), portal, launcher `.cmd` | Xong |
| **V1** | CSV workspace (+ CSV trong pack) | Xong |
| **V2** | Docs workspace (+ docs trong pack, một menu nhiều cấp) | Xong |
| **V3** | `export-solr` + ocr-search SQLite + MCP 2 tool | Xong; **chưa thử với data Solr thật** |
| **V4** | code-map viewer + MCP, đa pack; ERD + Mermaid/DBML (+ extractor FK ở repo code-map) | Xong |
| **V5** | Import pack (không đè, không hạ version, quay lại bản cũ), `repair`, build một lệnh `packaging/build.py` | Xong; **chưa chạy trên Windows thật**. Chưa có: Export/Import workspace, CI migration fixtures, màn hình ghi chú mồ côi |
| **V6** | MCP Bridge: daemon `my-bridge` + addon `mcp-bridge` (premium) | Xong bản đầu; **chưa thử Box Drive / Copilot Studio thật**, cần IT duyệt |
| **V7** | Addon: tách tính năng thêm ra zip cài vào thư mục dữ liệu, không cần build lại Hub; `viewer-hub pack` trong bản phát hành (docs/addons.md) | Xong |

## 12. Câu hỏi mở
1. Data Solr thật lớn bao nhiêu (số document, dung lượng)? Ảnh hưởng thời gian export và chế độ Browser-only.
2. Phát hành release và pack qua đâu — thư mục Box chung? Ai có quyền đọc?
3. Có cần chế độ Hosted nhiều user (đăng nhập) không, hay chỉ Local?
4. IT có cho chạy `python.exe` embeddable từ `%LOCALAPPDATA%` không (AppLocker/WDAC)? Nếu không → chỉ còn Hosted/Browser-only.
5. Ghi chú code-map của user có cần đồng bộ ngược về cho tác giả không (hiện thiết kế: chỉ export thủ công)?
