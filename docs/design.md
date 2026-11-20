# Viewer Hub: thiết kế

> Kiến trúc, dữ liệu, cập nhật phiên bản. Bản đồ code và lệnh: [AGENTS.md](../AGENTS.md). Quy tắc khi viết code:
> [GUIDELINE.md](GUIDELINE.md). Addon: [addons.md](addons.md). Đề xuất đang làm: `solutions/` (xong thì xoá).

## 1. Viewer Hub là gì

Web app chạy trên máy Windows của user (Python embeddable chính hãng, không cài đặt), mở ở `http://127.0.0.1:<cổng>`,
gom phần **xem** của các tool: Code map, F-Search (full-text), CSV, Docs, Giám sát, cùng các addon. Phần **extract**
(quét code, OCR, index Solr) chạy trên máy tác giả và được đóng thành **data pack** (`.sapack`) phát cho user.

```
 MÁY TÁC GIẢ                         .sapack        MÁY USER
 code-map extractor  ─┐            (Box, file)      viewer-hub  (waitress, 127.0.0.1)
 ocr-demo → export-solr├──► viewer-hub pack ─────►    /             trang chủ, cài đặt, hướng dẫn
 CSV, thư mục markdown ┘                              /code-map /ocr-search /csv /docs /monitor
                                                      /x/<addon>    addon (vd. MCP Bridge, ERD, SVN)
                                                      <prefix>/mcp  MCP từng module · stdio `viewer-hub mcp …`
```

Nguyên tắc:
1. **App và data tách thư mục.** Cập nhật chỉ thêm thư mục app mới, không ghi đè thư mục data.
2. **Pack bất biến, chỉ đọc.** Mọi thứ user tạo nằm ngoài pack.
3. **Nguồn và dẫn xuất tách nhau.** Nguồn (file user đưa vào, ghi chú) không bao giờ tự xoá; dẫn xuất (index, site đã
   build) xoá và tạo lại được.
4. **Hợp đồng duy nhất giữa extract và viewer là format pack** có version.
5. **Không tác vụ nền tự gom / gửi data**, không gọi mạng ra ngoài (GUIDELINE §5).

Ngoài phạm vi: extract trên máy user; full-text ngang Solr (chấp nhận SQLite FTS5); nhiều user cùng ghi một thư mục data
(Hosted / chạy trong trình duyệt chưa làm).

Repo liên quan: `code-map` (extractor, ra `codemap/` của pack), `ocr-demo` (OCR, `export-solr`),
`viewer-hub-addons` (các addon, gồm `my-bridge`: daemon MCP Bridge tự build addon `mcp-bridge`).

## 2. Data pack

```
pack.json
codemap/        codemap.sqlite  graph.sqlite  manifest.json
search/         search.sqlite
csv/<id>/       dataset.json  source.csv  data.sqlite      (index tạo lúc đóng pack)
docs/<id>/      site.json  site/…                          (build lúc đóng pack)
source/         (tuỳ chọn) file nguồn để Code map xem đoạn code
```

`pack.json`: `format`, `id` (ổn định qua các lần phát hành), `version` (tăng mỗi lần build), `title`, `components`
(mỗi thành phần có `schema` riêng), `sha256` của từng file. Pack có thể chỉ chứa một phần.

Import (`packs/importer.py`): chặn zip slip / zip bomb; chỉ nhận phần mở rộng trong allowlist, có file khác thì từ chối
cả pack; kiểm `sha256`; giải nén vào `packs/<id>/<version>.tmp/` rồi rename (atomic). Chỉ **bật** khi version mới ≥ bản
đang dùng; bản cũ giữ lại, Cài đặt → **Dùng bản này** để quay lại. Import không ghi `workspace/`, `user/`, `config.yaml`;
id `local` dành riêng.

Mục CSV / Docs từ pack hiện chung danh sách với mục của user, id `<pack>--<id>`, chỉ đọc.

## 3. Dữ liệu trên máy user

| Mục đích | Đường dẫn (Windows) | Cập nhật có đụng tới |
|---|---|---|
| Chương trình | `%LOCALAPPDATA%\Programs\ViewerHub\ViewerHub-<ver>\` | thêm thư mục mới |
| Con trỏ bản dùng + launcher chung | `…\Programs\ViewerHub\current.txt`, `viewer-hub.cmd` (`setup.cmd`) | có |
| Data | `%LOCALAPPDATA%\ViewerHub\` (`--data-dir` > `VIEWER_HUB_HOME` > `config.yaml` > mặc định) | **không** (chỉ migration) |

```
ViewerHub\
├─ hub.db            registry: packs, datasets, sites, settings (SQLite WAL)
├─ hub.lock          một instance mỗi thư mục data
├─ config.yaml
├─ packs\<id>\<version>\                         bất biến
├─ workspace\csv\<id>\   source.csv, dataset.json (NGUỒN) · data.sqlite (DẪN XUẤT)
├─ workspace\docs\<id>\  site.json, src\ (NGUỒN) · site\ (DẪN XUẤT)
├─ user\codemap\<pack_id>\knowledge.sqlite      NGUỒN: tài liệu, quy tắc, liên kết, ghi chú
├─ addons\<id>\  · user\addons\<id>\            addon đã cài · dữ liệu của addon (gỡ addon không xoá)
├─ backups\<thời điểm>-from-<ver>\  · logs\  · monitor.db  · tmp\ (xoá khi khởi động)
```

| Loại | Mất thì | Quy tắc |
|---|---|---|
| Nguồn | mất vĩnh viễn | không tự xoá; backup trước migration |
| Dẫn xuất | tạo lại được | migration chỉ đánh dấu `needs_rebuild` |
| Registry `hub.db` | mất danh sách | backup; `viewer-hub repair` dựng lại từ các file JSON cạnh data |
| Pack | import lại | không migration; app đọc theo `schema` của từng thành phần |

Không có "portable mode" (data cạnh app là nguyên nhân mất data phổ biến nhất khi giải nén đè). Ghi file atomic
(`core/atomic.py`: tmp → fsync → `os.replace`), thư mục mới dựng trong `tmp\` rồi rename. Pack mở `mode=ro`.
Instance thứ hai (kể cả khác version) thấy `hub.lock` thì mở trình duyệt tới bản đang chạy rồi thoát.

Tài liệu Code map của user gắn theo `pack_id` + node, không theo version, nên pack mới vẫn giữ. Node không còn trong pack
mới: liên kết tự gắn lại theo địa chỉ node (`solutions/node-address-and-linking.md`), phần còn lại vẫn nằm trong
`knowledge.sqlite`.

## 4. Cập nhật phiên bản

Ba version độc lập: app (`viewer_hub/__init__.py`), schema data (`PRAGMA user_version` của `hub.db` = số migration cuối
trong `viewer_hub/migrations/`; `schema` trong `dataset.json` / `site.json`), format pack (`format`,
`components.*.schema`).

User giải nén bản mới **cạnh** bản cũ rồi mở `viewer-hub.cmd` của nó; data dùng chung. Không auto-update, không installer.

Khởi động (`core/migrate.py`):
```
user_version == HUB_SCHEMA  → chạy
user_version <  HUB_SCHEMA  → backup → migration lần lượt (mỗi file một transaction) → chạy
user_version >  HUB_SCHEMA  → data của bản mới hơn: CHỈ ĐỌC, không ghi gì
migration lỗi               → rollback, khôi phục backup vừa tạo, mở CHỈ ĐỌC kèm đường dẫn backup
```
Migration chỉ tiến, không sửa migration đã phát hành; key lạ trong `config.yaml` giữ nguyên.

Backup (`core/backup.py`): tự động trước migration và thủ công (Cài đặt, `viewer-hub backup`); SQLite online backup cho
`hub.db` và mọi `knowledge.sqlite`, cùng `config.yaml`, `dataset.json`, `site.json`; không chép file nguồn lớn, dẫn xuất,
pack. Giữ 5 bản. `viewer-hub restore <backup>` tự backup trạng thái hiện tại trước.

Rollback: mở `viewer-hub.cmd` của bản cũ; nếu bản mới đã migration thì bản cũ chỉ đọc, muốn ghi thì `restore` backup
tạo lúc migration.

## 5. Các module

Mỗi module là một package có `module.py` (menu, route, hướng dẫn, MCP): AGENTS.md "Thêm một module". Hướng dẫn cho user
và bảng tool MCP của từng module nằm trong `GUIDE.md` của nó.

| Module | Đọc gì | Ghi chú thiết kế |
|---|---|---|
| **Code map** `/code-map` | `codemap/` của pack (graph chỉ đọc) + `user/codemap/<pack>/knowledge.sqlite` (attach `kn`) | Nhiều pack: mỗi request mang `pack`. Lớp nghiệp vụ (`business/`): cây tính năng, tài liệu luồng, AI xuất / nhập, liên kết tay. ERD của luồng (`erd.py`, khoá ngoại `REFERENCES`); ERD cả DB là addon `erd`, đọc qua export `erd_model` / `db_objects` / `table_usage` (`codemap/exports.py`). Tool ghi `propose_*` chỉ khi có knowledge token; AI ghi là dùng ngay, nhãn **AI viết**, không đè phần người viết |
| **F-Search** `/ocr-search` | `search/search.sqlite`: `docs`, FTS5 `unicode61` + `trigram` (tiếng Nhật) | Port từ ocr-demo, trả đúng cấu trúc kết quả cũ. Không fuzzy / lucene. MCP 2 tool (tìm, đọc) cho gọn token |
| **CSV** `/csv` | `workspace/csv` + CSV của pack | Nhận dạng encoding / dấu phân cách / kiểu cột, nạp SQLite + FTS5; export escape `= + - @`. MCP chỉ với file bật "Cho AI đọc" |
| **Docs** `/docs` | `workspace/docs` + site của pack | Build mkdocs trong tiến trình; `mkdocs.yml` của user bị bỏ `hooks`, plugin ngoài `search`, theme. Site chỉ phục vụ ở origin `localhost` (app ở `127.0.0.1`) để script trong markdown không đọc được app |
| **Giám sát** `/monitor` | `monitor.db` (`core/monitor.py`) | Mọi lời gọi MCP (cả addon), sức khoẻ và RAM / CPU của addon |

MCP: mỗi module một server (HTTP `<prefix>/mcp` chỉ nhận Origin loopback; stdio `viewer-hub mcp <lệnh>` mở `hub.db` chỉ
đọc). Tool chỉ đọc, trả văn bản gọn. MCP Bridge (addon premium `mcp-bridge`) tự đăng ký mọi MCP của Hub và addon
(`addons/gateway.py`); Hub nói với daemon bridge qua kênh quản trị của cùng user (named pipe / Unix socket), trình duyệt
không chạm daemon.

## 6. Chưa làm

- Export / Import workspace (chuyển data nguồn sang máy khác).
- Fixture data dir của từng bản phát hành để test migration (`tests/migrations/fixtures/`), test downgrade tự động.
- Chạy thật trên Windows công ty: F-Search với data Solr thật, MCP Bridge với Box Drive / Copilot Studio (cần IT duyệt
  `python.exe` embeddable và bridge).
