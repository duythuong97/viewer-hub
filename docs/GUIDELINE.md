# Viewer Hub — Guideline phát triển

> Đọc cùng [design.md](design.md) (kiến trúc) và [addons.md](addons.md) (addon). Bridge: repo my-bridge, `docs/box-mcp-design.md`.
> Mọi thay đổi phải giữ đúng 4 điều: **Material Design 3**, **không mất data của user khi update**, **qua được security scan**, **viewer chỉ đọc pack**.

---

## 1. Bắt đầu

Mọi lệnh nằm trong `justfile` (cần uv, just, fzf, Node.js 22+; cài xem README §1). `just` = chọn lệnh bằng fzf.

```bash
just setup        # uv sync (Python 3.12+, .venv, nhóm dev) + npm ci --prefix web
just web          # build giao diện → viewer_hub/static/dist/ (máy user không cần Node)
just web-watch    # build lại mỗi khi sửa web/ (chạy song song với serve)
just serve        # chạy với thư mục data dev var/dev (không đụng data thật), cổng 8765
```

Chạy lệnh Python khác trong môi trường của repo: `uv run python …` / `uv run viewer-hub …`.

Dữ liệu mẫu cho dev:

```bash
# search.sqlite từ file JSON mẫu của Solr
uv run python -c "from pathlib import Path; from viewer_hub.fsearch.export_solr import from_json; \
  from_json(Path('../ocr-demo/docker/solr/sample_data.json'), Path('var/dev/search/search.sqlite'))"
# code-map: copy một thư mục output vào var/dev/codemap/
```

Trước mỗi commit: `just check` (build giao diện, pytest, `check_security.py`, test code map).

---

## 2. Cấu trúc

```
viewer_hub/
  core/        paths, lock, db (hub.db, settings), migrate, backup, repair, atomic, logs, mcp (MCP chung), monitor (ghi lời gọi MCP vào monitor.db),
               config (cài đặt, danh sách premium), unlock + ed25519 (mã mở khoá premium)
  app/         factory (create_app / create_wsgi), modules (danh sách module), spa (trang + lỗi JSON),
               portal (home, settings, help, premium, /api/app), origins
  csv/         CSV workspace + MCP          → /csv
  fsearch/     F-Search: full-text search (FTS5) + MCP → /ocr-search  (+ export_solr.py cho máy tác giả)
  docs/        docs site (mkdocs)           → /docs
  monitor/     Giám sát: lời gọi MCP (cả addon), sức khoẻ addon + MCP → /monitor (ghi: core/monitor.py)
  codemap/     code-map viewer + MCP        → /code-map
    api/         route JSON cho SPA
    business/    lớp nghiệp vụ: cây chức năng, flow, sửa, AI export/import, liên kết tay, tìm kiếm
    mcp/         tool + prompt của MCP code map
    cli/         lệnh `mcp codemap`, `erd`
    contract/    phần chép từ extractor của code-map (đọc pack)
  addons/      addon cài vào thư mục dữ liệu (docs/addons.md): manifest, install, runner, proxy, registry, routes
               (/x/<id>/…, /api/addons), gateway (đăng ký MCP vào MCP Bridge), sdk.py (addon Python)
  help/        trang Hướng dẫn: ghép parts/*.md + GUIDE.md của từng module
  packs/       import/build .sapack
  migrations/  0001_init.sql, 0002_….py
  templates/   app.html: trang duy nhất Flask trả về; React vẽ mọi trang
  static/dist/ bản build của web/ (md.js/css, app.js/css, chunks/, sdk/*.js cho trang addon)
web/           Vite, chỉ build-time:
  src/md/        design system Material 3 (md.css, md/react.jsx bọc component cho React)
  src/app/       khung SPA: Shell (menu, thanh trên), router, http.js, ui.jsx, trang chung (Home, Settings, Help, Premium)
  src/modules/<key>/index.jsx   trang của từng module (tìm theo key)
  src/sdk/       SDK addon: react, jsx-runtime, react-dom, md, ui (API công khai, có version)
addons/        addon mặc định: *.zip đã ký (commit), đi kèm mọi bản build, tự cài khi mở
packaging/     build.py, build_release.py, addon.py, unlock.py, check_security.py, requirements.lock (bản Windows),
               release.justfile, viewer-hub.yaml, windows/ (viewer-hub.cmd, setup.cmd, launcher), unix/viewer-hub.sh
tests/         pytest
docs/          design.md, GUIDELINE.md, addons.md; solutions/: đề xuất còn đang làm (xong thì xoá)
justfile       mọi lệnh của repo (`just` = chọn bằng fzf); pyproject.toml + uv.lock (uv)
```

**Quy tắc module:** mỗi tính năng là một package có `module.py` (khai báo `MODULE`, xem `app/modules.py`), `GUIDE.md` (mục Hướng dẫn cho user), `routes.py` (Blueprint: trang trả `spa.page()`, dữ liệu là JSON API dưới `/<prefix>/api/…`), `store.py` (đọc/ghi data, không import Flask); có MCP thì thêm `mcp.py`. Giao diện ở `web/src/modules/<key>/`. Store không biết gì về request; routes không đụng file trực tiếp và không render HTML.

**Lấy hub trong request:** `g.hub.paths` (HubPaths), `g.hub.db` (HubDB), `g.hub.readonly`.

---

## 3. Data — không bao giờ làm mất data của user

### 3.1 Đặt file ở đâu

| Loại | Ở đâu | Ví dụ |
|---|---|---|
| Nguồn (user tạo) | `paths.workspace/…`, `paths.user/…` | `source.csv`, `dataset.json`, `src/`, `knowledge.sqlite` |
| Dẫn xuất (tạo lại được) | cạnh nguồn | `data.sqlite`, `site/` |
| Pack (bất biến) | `paths.packs/<id>/<version>/` | `search.sqlite`, `codemap.sqlite` |
| Tạm | `paths.tmp` | upload đang ghi, build đang chạy |

- **Không bao giờ** ghi vào thư mục app, vào `packs/`, hay ngoài `paths.home`.
- Không thêm "portable mode" để data cạnh app.
- Mở SQLite của pack bằng `open_readonly()` (`mode=ro`).

### 3.2 Ghi an toàn
- File JSON: `core.atomic.write_json()` (tmp → fsync → `os.replace`).
- Tạo thư mục mới (dataset, site, pack): dựng xong trong `paths.tmp`, rồi `rename` vào chỗ — data xuất hiện **đầy đủ hoặc không có**.
- Xoá: `rename` sang `tmp/` rồi mới xoá.
- hub.db: chỉ ghi trong `with g.hub.db.write() as db:` (transaction, tự rollback).
- Mỗi bản ghi trong hub.db phải có **bản sao trong file JSON cạnh data** (`dataset.json`, `site.json`, `pack.json`) để `viewer-hub repair` dựng lại được.

### 3.3 Đổi format data = viết migration
1. Tạo `viewer_hub/migrations/NNNN_mo_ta.sql` hoặc `.py` (`def migrate(db, paths)`), số tiếp theo, không bỏ số.
2. Chỉ tiến (forward-only). Không sửa migration đã phát hành.
3. Data dẫn xuất đổi format → không chuyển đổi, chỉ `UPDATE … SET needs_rebuild = 1`.
4. Đổi `dataset.json`/`site.json`: tăng `schema` trong file, ghi file mới bằng `write_json` (bản cũ đã nằm trong backup tự động).
5. Key cấu hình lạ: **giữ nguyên**, không xoá.
6. Thêm fixture data dir của bản trước vào `tests/migrations/fixtures/<version>/` và test nâng cấp từ fixture đó.

App tự backup trước khi migrate, migrate lỗi thì khôi phục và mở **chỉ đọc**; data mới hơn app thì mở **chỉ đọc**. Đừng viết code né cơ chế này.

---

## 4. Giao diện — Material Design 3

Mọi trang (React, docs site) theo [Material 3](https://m3.material.io). Không có ngoại lệ.

### 4.1 Nguồn duy nhất
- **Màu:** chỉ dùng token `--md-sys-color-*` (sinh từ một seed trong `web/scripts/make-theme.mjs`, có sẵn light/dark). Không hard-code mã màu.
- **Chữ:** `--md-sys-typescale-*` hoặc class `.md-title-large`, `.md-body-medium`… Font Roboto/Roboto Mono đi kèm app.
- **Phong cách "thin":** chữ thường dùng Roboto Light (300), tiêu đề 400, nhãn/nút 500. Dữ liệu (bảng, kết quả tìm kiếm, danh sách) dùng token gọn `--vh-data` (13px), `--vh-data-small` (12px), `--vh-data-mono`; bảng dùng `--vh-table` (14px), hàng cao 48px, đệm ngang 16px. Icon Material Symbols độ dày `wght 200` (icon đang chọn: FILL 1, `wght 300`). Không tự đặt `font-weight: 600/700` cho nội dung.
- **Bo góc, chuyển động:** `--md-sys-shape-corner-*`, `--md-sys-motion-*`.
- **Icon:** chỉ **Material Symbols Outlined** qua `<md-icon>tên_icon</md-icon>` (tra tên tại fonts.google.com/icons). Icon "đang chọn" dùng `<md-icon filled>`. Không emoji làm icon, không SVG icon lẻ, không thư viện icon khác (lucide, font-awesome…).

### 4.2 Component
| Cần | Dùng |
|---|---|
| Nút | `md-filled-button` (hành động chính, 1/màn hình), `md-filled-tonal-button`, `md-outlined-button`, `md-text-button`, `md-icon-button` |
| Nhập liệu | `md-outlined-text-field`, `md-outlined-select` + `md-select-option`, `md-checkbox`, `md-switch`, `md-slider`, `md-radio` |
| Lọc / thẻ | `md-chip-set` + `md-filter-chip` / `md-input-chip` / `md-assist-chip` |
| Hộp thoại | `Dialog` (react.jsx); xác nhận thao tác nguy hiểm: `useConfirm()` (bên dưới) |
| Tiến trình | `md-linear-progress`, `md-circular-progress` |
| Khung trang | `web/src/app/Shell.jsx`: navigation rail + top app bar (tự đổi thành bottom bar khi < 600px) |
| Bọc cho React | `web/src/md/react.jsx` (Button, IconButton, TextField, Select, Switch, Checkbox, Dialog, Tabs, Chip, FilterBar…), `web/src/app/ui.jsx` (PageHeader, SearchBar, LinkCard, ListItem, Badge, useAction, useLoad, useConfirm) |
| Card, bảng, search bar, banner, empty state, snackbar, badge, dropzone | class trong `web/src/md/md.css`: `.md-card`, `.md-table`, `.md-search-bar`, `.md-banner`, `.md-empty`, `window.md.snackbar()`, `.md-badge`, `.md-dropzone` |

**Màu theo nghĩa** (giống nhau ở mọi trang và mọi addon): `Badge tone` = `success` (đang chạy, cho phép, đã ký),
`warning` (đang chờ, thử lại, cần duyệt, sắp hết hạn), `error` (lỗi, nguy hiểm), `primary` (thông tin nổi bật), không
tone (trung tính: dừng, tắt). Không tự đặt mã màu; chỉ token (`--md-sys-color-*`).

**Thao tác nguy hiểm phải xác nhận** (`useConfirm()` trong `ui.jsx`, `@vh/ui` cho addon): xoá, gỡ, dừng / tắt dịch vụ
hoặc server, cấp quyền rộng (cho tool ghi tự chạy), từ chối / huỷ việc người khác chờ. Hộp xác nhận nói **cái gì sẽ
mất / dừng** và có hoàn tác được không; nút xác nhận ghi đúng động từ ("Xoá", "Dừng", không phải "OK") và đỏ
(`danger`, mặc định). Nút mở thao tác đó cũng đỏ: `<Button danger>`, `<IconButton danger>` (class `md-button--danger`).
Thao tác an toàn / hoàn tác được (bật, lưu, tải lại, chạy) không hỏi.

```jsx
const [confirm, dialog] = useConfirm();   // render {dialog} một lần trong trang
if (!(await confirm({ title: `Xoá “${name}”?`, text: "Không hoàn tác được.", confirm: "Xoá", icon: "delete" }))) return;
```

Component mới của `@material/web` phải import trong `web/src/md/index.js`. Component M3 mà thư viện không có thì viết CSS trong `md.css`, theo spec m3.material.io, chỉ dùng token.

### 4.3 Trang (React)
Flask chỉ trả `templates/app.html` cho mọi URL trang (`spa.page()`); `web/src/app` đọc `GET /api/app` (menu, phiên bản,
chế độ chỉ đọc) rồi vẽ trang. Trang của module là `web/src/modules/<key>/index.jsx`, `export default` một component nhận
`{module, subpath}`:
```jsx
import { useLayout, useTitle } from "../../app/context.jsx";
import { http } from "../../app/http.js";
import { PageHeader, useAction, useLoad } from "../../app/ui.jsx";

export default function ErrorDictPage({ module, subpath }) {
  useTitle("Từ điển lỗi");        // thanh trên cùng + tab trình duyệt
  useLayout("wide");              // "page" (mặc định), "wide" (bảng, kết quả) hoặc "full" (code map)
  const { data, reload } = useLoad(() => http.get("/error-dict/api/items"));
  const [run, busy] = useAction(); // lỗi tự hiện snackbar
  return <PageHeader subtitle="Tra mã lỗi…">…</PageHeader>;
}
```
- Dữ liệu chỉ qua JSON API của module; lỗi trả bằng `raise spa.ApiError(code, message, status)` → `{"error": {code, message}}`.
  Ghi dùng `http.post/patch/put/delete` (gửi JSON); upload dùng `uploadWithProgress`.
- Mục menu, route trang và thẻ trang chủ tự có từ `module.py` (§10.2); không sửa `Shell.jsx` hay `pages.js`.
- Mọi icon button phải có `aria-label` (`IconButton label=…`). Văn bản giao diện: tiếng Việt.
- Dữ liệu hiện bằng JSX (React tự escape). Chỉ dùng `dangerouslySetInnerHTML` với HTML do chính app sinh và đã escape
  (trang Hướng dẫn, đoạn trích `<mark>` của F-Search).

### 4.4 Thư viện
Dùng chính custom element của `@material/web` (qua `md/react.jsx`) và class/token của `md.css`; CSS riêng của component
chỉ dùng token. Không thêm Tailwind, MUI hay design system khác.

### 4.5 Tính năng chưa phát hành
Không ghi tên tính năng chưa phát hành ở bất kỳ đâu trên giao diện (menu, tiêu đề, nút, thông báo, `title`, `aria-label`). Trong app nó chỉ hiện là **Premium feature**: mục điều hướng "Premium" (icon `workspace_premium`), trang khoá có nút **Donate to unlock** (icon `volunteer_activism`). Tên thật chỉ nằm trong tài liệu nội bộ (`docs/`) và code.

Mở **bằng mã trên từng máy**, không phải lúc build: mọi bản build giống nhau và có đủ file, tính năng premium khoá sẵn.

```bash
just unlock bridge     # máy admin: một mã ngẫu nhiên mới mở premium "bridge" (addon MCP Bridge)
```

- Tính năng premium luôn là **addon** khai `"premium": "<tên>"` (module builtin không bao giờ premium: `modules.all_modules()` từ chối). Mã = `VH2-` + base32 của (`VH`, phiên bản, **tên** tính năng, 5 byte ngẫu nhiên) + chữ ký Ed25519 (`viewer_hub/core/unlock.py`, Ed25519 thuần Python ở `core/ed25519.py`, không thêm dependency). App chỉ chứa khoá công khai; khoá bí mật ở `~/.viewer-hub/unlock-signing.key` trên máy admin, không bao giờ vào repo hay bản build.
- Người dùng dán mã ở trang **Premium** → `POST /api/premium/unlock`: mã đúng được lưu vào `hub.db` (setting `premium.codes`) và tính năng mở **ngay**, không khởi động lại (`addons/routes.py` kiểm khoá mỗi request). Mã mang tên một tính năng chưa cài vẫn được lưu: cài addon đó là mở. Lần mở sau đọc lại mã đã lưu.
- Chạy từ source hay bản phát hành đều như nhau: chỉ mã mới mở được. Cờ `premium` trong `viewer-hub.yaml`/`config.yaml` bị bỏ qua (log ghi cảnh báo).
- **Khoá:** không có mục menu, không có tên ở đâu cả; chỉ có mục chung **Premium** → ô nhập mã + *Donate to unlock*. Gõ thẳng `/x/mcp-bridge` bị chuyển về `/premium`, mọi route khác của nó trả 404.
- **Mở:** mục menu riêng với **tên và icon thật** (*MCP Bridge* → `/x/mcp-bridge`). Mục **Premium** tự ẩn khi không còn tính năng nào bị khoá.
- **Mật khẩu admin** (không cần source): `just unlock-passphrase` (máy tác giả, một lần) ghi khoá công khai của mật khẩu vào `viewer_hub/core/unlock_pass.py` (khoá bí mật = scrypt(mật khẩu), `unlock.derive`). Bản phát hành có `just unlock <tên>`: hỏi mật khẩu, sai thì từ chối, đúng thì in mã. Lệnh `viewer-hub unlock` không có trong `--help`. Mã từ mật khẩu và mã từ file khoá đều hợp lệ; ký addon vẫn chỉ bằng file khoá. Đổi mật khẩu = chạy lại lệnh: mã của mật khẩu cũ hết hiệu lực ở bản build mới. Tối thiểu 6 ký tự; mật khẩu ngắn đoán được từ khoá công khai (scrypt chỉ làm chậm), đủ cho mục đích "đọc hướng dẫn rồi mới mở", không phải bảo mật.
- Dev: `just unlock bridge` rồi dán mã ở trang Premium của `just serve` (mã lưu trong `var/dev/hub.db`). Test mở khoá qua `tests/test_core.py: _client_with(paths, premium=True)` (addon mẫu: `tests/addon_kit.py`).
- Thêm tính năng premium: `"premium": "<tên>"` trong `addon.json`. Không có bảng tính năng nào phải sửa trong Hub; đừng đổi tên đã phát mã.
- Giới hạn: mã không gắn với máy (ai có mã cũng mở được) và không thu hồi được (không có server). Code phát hành là file `.py` đọc được, người sửa code vẫn bỏ qua được bước kiểm tra; mã chỉ chặn việc mở khoá thông thường. Addon premium được cài sẵn (bản phát hành kèm zip) nhưng không chạy, không hiện tên cho tới khi mở khoá.

### 4.6 Docs site
mkdocs-material, `font: false`, palette theo hệ thống. Không bật theme/plugin khác.

---

### 4.7 Bố cục trang (giống nhau ở mọi trang)
- **Thanh trên cùng** chỉ ghi tên mục (Docs, CSV, Cài đặt…), thêm nút quay lại ở trang con. **Không đặt nút hành động ở đây.**
- **Mọi trang mở đầu bằng `PageHeader`** (`web/src/app/ui.jsx`): một dòng mô tả bên trái, nút hành động của trang bên phải (nút chính là filled, phụ là tonal/outlined hoặc icon button). **Không lặp tên**: trang gốc của một mục (Docs, CSV, Cài đặt…) để `title=""` vì thanh trên cùng đã ghi tên; chỉ trang con (một site, một bộ dữ liệu) mới có tiêu đề riêng.
- **Trang tìm kiếm** (F-Search, Code map) không dùng `PageHeader` mà dùng **thanh công cụ** ngay dưới thanh trên cùng, tràn hết chiều ngang, có đường kẻ dưới: ô tìm bên trái (tối đa 640px), vài bộ lọc chính + nút "Nâng cao" bên phải (`.md-search-toolbar`, giống `.cm-toolbar`).
  ```jsx
  <PageHeader subtitle="Mỗi thư mục markdown thành một site…">
    <Button variant="filled" icon="add" onClick={create}>Tạo site</Button>
  </PageHeader>
  ```
- **Độ rộng**: mọi trang dùng mặc định (tối đa 1280px, căn giữa) để các trang thẳng hàng nhau khi chuyển qua lại, kể cả bảng CSV, Bridge, trang addon; bảng rộng hơn thì cuộn ngang trong khung. Chỉ trang tìm kiếm có thanh công cụ tràn ngang (F-Search) dùng `useLayout("wide")`, Code map dùng `"full"`.
- **Danh sách + chi tiết** (sơ đồ, đặc tả, ticket…): danh sách bên trái luôn hiện, chi tiết bên
  phải, URL ghi mục đang mở. Không bắt người dùng "quay lại" trên màn hình rộng; màn hẹp mới hiện một cột và nút quay lại.
- **Form thêm / sửa ngắn** (thêm repo, cài đặt addon) mở trong `Dialog` từ nút ở `PageHeader`; nội dung chính (danh
  sách) đứng đầu trang. Trạng thái trống có nút làm việc tiếp theo ("Thêm repository").
- **Banner** chỉ khi người dùng phải làm gì (dịch vụ dừng, thiếu cài đặt, lỗi), kèm nút làm luôn.
- **Tiêu đề mục trong trang**: `<h2 class="md-section-title">`, không viết style inline.
- **Code map (React)** theo cùng quy tắc: `.cm-page__head--actions` (tiêu đề trái, nút phải).

## 5. Bảo mật — máy công ty scan rất chặt

`packaging/check_security.py` kiểm tra tự động phần lớn các quy tắc dưới đây; chạy trước mỗi commit.

### 5.1 Không được dùng
| Không | Thay bằng |
|---|---|
| Exe tự đóng gói (PyInstaller, Nuitka, Node SEA, bun compile, Tauri) | `python.exe` embeddable của python.org + source |
| Tải code/asset lúc chạy (pip, npm, CDN, Google Fonts) | Mọi thứ nằm trong bản phát hành; CSP `default-src 'self'` |
| Native extension của bên thứ ba (`.pyd`, `.so`, addon Node) | Package thuần Python; build_release xoá native file và dựa vào fallback thuần Python |
| `subprocess(shell=True)`, `os.system`, PowerShell, `cmd /c`, ẩn cửa sổ của chương trình có giao diện | Không chạy tiến trình. Ngoại lệ (argv, không shell, đã khai trong `check_security.py`): `explorer.exe /select,` khi user bật "thư mục file gốc"; `python` / `node` / `dotnet` của addon đã cài (`addons/runner.py`; `dotnet` là .NET có sẵn trên máy, addon chỉ mang assembly .NET; addon premium chỉ chạy khi đã mở khoá); `ps` / `tasklist` chỉ đọc RAM / CPU của Hub và addon cho trang Giám sát. Trên Windows các tiến trình console này chạy với `CREATE_NO_WINDOW` (không bật cửa sổ console; output vào log của Hub), addon Node dùng `node` của máy, không mang `node.exe` |
| Gọi mạng từ code chạy trên máy user | Không. Ngoại lệ: `export_solr.py` (chỉ chạy trên máy tác giả); `addons/proxy.py` chỉ gọi `127.0.0.1` tới tiến trình addon Hub vừa chạy |
| Addon (zip cài thêm) | Quét lúc cài bằng cùng bộ quy tắc (`core/scan.py`): native / script file (trừ assembly .NET của addon `runtime: dotnet`), `shell=True`, `eval`, `innerHTML` trong UI bị từ chối; gọi mạng, chạy tiến trình được báo cho admin. Chữ ký Ed25519 (cùng khoá mã mở khoá); addon chưa ký ghi rõ "do admin cung cấp"; bản chưa ký không thay được bản đã ký. Từ chối thêm: tên file Windows không giữ được / chỉ khác hoa thường, id hoặc lệnh MCP trùng (docs/addons.md §7.1) |
| Addon làm chết Hub | Addon là tiến trình riêng; `addons/limits.py` giới hạn request đồng thời mỗi addon, crash liên tục bị tạm dừng, log quá 50 MB bị dừng, addon managed tự thoát khi Hub chết (pipe stdin). Không sửa các giới hạn này mà không cập nhật `tests/test_addon_isolation.py` (docs/addons.md §7.2) |
| Đọc config/secret của app khác, Credential Manager, registry, autostart | Không làm |
| `eval`/`exec`, `pickle`, `yaml.load` không SafeLoader, payload base64, obfuscate | Không làm |
| `innerHTML` / `dangerouslySetInnerHTML` với dữ liệu | JSX (React tự escape); highlight tự escape rồi mới chèn `<mark>` |

### 5.2 Nội dung do user đưa vào
- **Upload:** kiểm tra phần mở rộng (allowlist), kích thước, đường dẫn (`safe_relative`), không lưu file thực thi.
- **Zip / pack:** chặn `..`, đường dẫn tuyệt đối, ký tự ổ đĩa; giới hạn tổng dung lượng và tỉ lệ nén; kiểm tra sha256.
- **mkdocs.yml của user:** chỉ giữ `site_name`, `nav`, `copyright`, markdown extension trong allowlist. **Bỏ `hooks`, plugin ngoài `search`, theme.** YAML đọc bằng SafeLoader không import gì.
- **Hai origin** (`app/origins.py`): app chỉ chạy ở `http://127.0.0.1:<port>`, nội dung do user tạo (docs site) chỉ ở `http://localhost:<port>`. Script trong markdown vì vậy không đọc được trang app, không gửi form của app, không gọi được daemon bridge (daemon chỉ cho origin app). Host khác bị từ chối (chống DNS rebinding). Link tới docs site dùng `content_url(...)`. Không dùng CSP `sandbox` cho docs: mkdocs-material cần localStorage và tải asset bình thường.
- **Export CSV:** escape ô bắt đầu bằng `= + - @`.

### 5.3 Thêm dependency
1. Phải thuần Python (hoặc có fallback thuần Python đã kiểm tra) và phổ biến.
2. Thêm vào `pyproject.toml`, rồi `just lock` (cập nhật `uv.lock` và `packaging/requirements.lock` cho Windows); npm ghim chính xác trong `web/package.json`.
3. Không có hook cài đặt chạy script lạ; không tải gì lúc chạy.
4. Ghi lý do vào PR. SBOM được sinh tự động khi build release.

### 5.4 Log
Chỉ ghi sự kiện (mở pack, build site, lỗi). **Không** ghi nội dung tài liệu, giá trị ô CSV, đường dẫn file của user ở mức INFO, token.

---

## 6. Data pack (máy tác giả)

Thường dùng `just pack` (đọc `input/`, xem README); trong bản phát hành cũng có `just pack` / `viewer-hub pack`, không cần source. Gọi từng bước bằng tay:

```bash
# 1. Solr → search.sqlite (Solr phải đang chạy)
just export-solr http://localhost:8983/solr/documents
# 2. Đóng pack
uv run python -m viewer_hub.packs.builder --id core-system --title "Core System" \
    --search input/search.sqlite --codemap ../code-map/var/output/prod \
    --csv danh-muc.csv --csv ma-loi.csv --docs ./spec-docs --out core-system.sapack
# 3. User import: Cài đặt → Import .sapack (hoặc `viewer-hub import core-system.sapack`)
```

`pack.json` phải hợp lệ theo design.md §5.2.

- `--csv` / `--docs`: cột, index SQLite và site mkdocs được tạo **lúc đóng pack**; trên máy user chúng mở ngay, **chỉ đọc**, id dạng `<pack>--<tên>` nên không bao giờ trùng hay đè CSV/Docs user tự thêm. Đổi nội dung → đóng pack version mới. Đổi format một component → tăng `schema` của component đó và giữ code đọc được schema cũ.

---

## 7. Test

- Mỗi store có test riêng, không qua HTTP; mỗi route chính có test qua `client` (fixture trong `tests/conftest.py`, data dir tạm).
- Bắt buộc có test cho: migration (thành công, lỗi → khôi phục, data mới hơn → chỉ đọc), path traversal, zip độc, file thực thi bị loại, escape HTML.
- Không test bằng data thật của công ty; dùng dữ liệu mẫu trong test.

---

## 8. Phát hành (Windows)

> Cách build cho admin (bỏ file vào `input/`, chạy `just build`): xem [README](../README.md). Phần dưới là chi tiết của `build_release.py`.

```bash
# Tải python-3.12.x-embed-amd64.zip từ python.org vào packaging/ (tác giả tự tải, script không tải gì)
uv run python packaging/build_release.py --python-embed packaging/python-3.12.10-embed-amd64.zip
```

Mọi bản build giống nhau: có đủ module (premium khoá, mở bằng mã §4.5), kèm mọi addon mặc định trong `addons/*.zip` (tự cài vào thư mục dữ liệu khi mở; bản mới hơn thay bản cũ) và `justfile` cho lệnh trong bản phát hành (`packaging/release.justfile`).

Kết quả: `dist/ViewerHub-<version>.zip`, `SHA256SUMS.txt`, `SBOM.json`.

User cài/cập nhật:
1. Giải nén (vd. vào `%LOCALAPPDATA%\Programs\ViewerHub\`), bản mới cạnh bản cũ.
2. Nhấp đúp `ViewerHub-<version>\viewer-hub.cmd`. Dữ liệu (`%LOCALAPPDATA%\ViewerHub\`) dùng chung mọi phiên bản.
3. Tuỳ chọn: `setup.cmd` ghi `current.txt` + launcher chung `…\ViewerHub\viewer-hub.cmd` (đường dẫn cố định cho shortcut / MCP stdio).
Rollback: mở `viewer-hub.cmd` của bản cũ (bản cũ thấy dữ liệu mới hơn → chỉ đọc, §3.3).

Tăng version: `viewer_hub/__init__.py` và `pyproject.toml`. Có migration mới → ghi rõ trong release note.

---

## 9. Lệnh

| Lệnh | Làm gì |
|---|---|
| `viewer-hub` / `viewer-hub serve [--port 8700] [--no-browser]` | Chạy web (một instance mỗi data dir) |
| `viewer-hub backup` | Sao lưu data nguồn |
| `viewer-hub restore <tên backup>` | Khôi phục (tự sao lưu trạng thái hiện tại trước) |
| `viewer-hub repair` | Dựng lại hub.db từ các file JSON |
| `viewer-hub import <file.sapack>` | Import data pack |
| `viewer-hub pack [--input input] [--out dist] [--install]` | Đóng data pack từ thư mục `input/` (chạy được trong bản phát hành) |
| `viewer-hub addon install <zip>` / `list` / `remove <id>` | Cài / liệt kê / gỡ addon (web: Cài đặt → Addon) |
| `viewer-hub addon pack <dir> [--include <zip>]` / `sdk` | Đóng một addon tự viết thành zip (kiểm như lúc cài) / ghi SDK viết addon (web: Cài đặt → Addon → Tải SDK) |
| `viewer-hub mcp <lệnh của addon>` | MCP stdio của một addon (chạy addon, chuyển tiếp tới `/mcp` của nó, chỉ tool đọc) |
| `viewer-hub export-solr <url> --out search.sqlite` | (Máy tác giả) Solr → SQLite |
| `viewer-hub mcp codemap [--pack ID]` | MCP stdio cho Code map (gồm `codemap_erd`) |
| `viewer-hub mcp search [--pack ID]` | MCP stdio cho F-Search (2 tool, gọn token) |
| `viewer-hub mcp csv` / `viewer-hub mcp monitor` | MCP stdio cho CSV / Giám sát |
| `viewer-hub erd (--table T \| --schema DB.S \| --system N) [--format mermaid\|dbml\|json] [--out F]` | ERD khoá ngoại của pack code-map |
| `viewer-hub --data-dir <dir> …` | Dùng thư mục data khác |
| `just` | (Máy dev/build) chọn lệnh của repo bằng fzf; `just --list` xem tất cả |
| `just build` / `build-fast` / `pack` | (Máy build) `input/` → data pack → `dist/` (xem README) |
| `just addon-default <zip>` | Kiểm tra một addon zip rồi chép vào `addons/` (addon mặc định, bỏ bản cũ) |
| `just addon <dir>` / `addon-watch <dir> <data>` | (Máy dev) sync SDK, build (`.sdk/build.mjs`), đóng + ký addon vào `dist/addons/`; build lại UI addon khi sửa |
| `just addon-sdk-sync <dir>…` | Chép SDK hiện tại (`.sdk/`, `AGENTS.md`, script npm) vào thư mục addon |
| `just unlock [key]` | (Máy admin) tạo mã mở khoá premium (§4.5) |

---

## 10. Thêm tính năng mới

Ví dụ xuyên suốt: tính năng **"Từ điển lỗi"** (`error_dict`), dữ liệu đến từ data pack, có trang web và MCP.
Chỉ làm những bước cần cho tính năng của bạn; các bước đánh dấu *(nếu …)* là tuỳ trường hợp.

### 10.1 Quyết định trước khi code

| Câu hỏi | Trả lời dẫn tới |
|---|---|
| Dữ liệu do **admin** cung cấp hay **user** tự thêm? | Admin → thành phần mới của data pack (§10.3). User → `paths.workspace/<tên>/` (§3) |
| Dữ liệu cần xử lý nặng (parse, index, build)? | Làm **lúc đóng pack** trên máy build, không làm trên máy user |
| Đổi được định dạng dữ liệu cũ? | Có → migration (§3.3) và tăng `schema` của thành phần |
| AI agent có cần tra cứu? | Có → MCP (§10.5) |
| Làm được ngoài Hub (API, MCP, trang riêng, tiến trình riêng)? | **Addon** (`docs/addons.md`, SDK `viewer_hub/addons/kit/`): không build lại Hub |
| Chưa phát hành cho mọi người? | Premium (§4.5): `premium: "<tên>"`, mặc định khoá |
| Nguồn dữ liệu nằm ở repo khác (extractor)? | Ghi rõ **hợp đồng** (file/bảng/field) ở cả hai repo; viewer chỉ đọc, không import code của extractor |

### 10.2 Module và trang web

1. Tạo package `viewer_hub/error_dict/`:
   - `store.py`: đọc/ghi dữ liệu, **không import Flask**. Mở SQLite của pack bằng `mode=ro` (`core/db.py: open_readonly`).
   - `routes.py`: `bp = Blueprint("error_dict", __name__)`; trang `@bp.get("/")` trả `spa.page()`, dữ liệu là JSON
     dưới `/api/…`, lỗi `spa.ApiError`; lấy hub qua `g.hub` (`paths`, `db`, `readonly`, `config`).
   - Trang: `web/src/modules/error_dict/index.jsx` (§4.3; thư mục trùng `key`). Tìm kiếm / bộ lọc dùng `SearchBar` và
     `FilterBar` (`.md-filter-bar`, `.md-filter-panel`, §4.2). Không viết thanh tìm kiếm riêng, không script inline (CSP chặn).
2. Khai báo module trong `viewer_hub/error_dict/module.py` và thêm `"viewer_hub.error_dict"` vào `PACKAGES` (`viewer_hub/app/modules.py`, theo thứ tự menu):
   ```python
   MODULE = Module(key="error_dict", label="Từ điển lỗi", icon="<material_symbol>", prefix="/error-dict",
                   summary="Tra mã lỗi: nghĩa, nguyên nhân, cách xử lý",
                   register=_register,  # def _register(app): app.register_blueprint(bp, url_prefix="/error-dict")
                   guide=Path(__file__).with_name("GUIDE.md"),
                   mcp=McpServer("/error-dict/mcp", "error-dict", tools=_tools))  # nếu có MCP (§10.5)
   ```
   Từ khai báo này app tự đăng ký route và mục menu, trang Hướng dẫn tự thêm mục, MCP tự vào bảng *Dùng với AI* và
   tự được đăng ký vào MCP Bridge (tên `viewer-<command>`). **Không** sửa `factory.py`, `help/` hay `addons/gateway.py`.
3. Thẻ trên trang chủ tự có (`label`, `icon`, `summary`); số đếm trên thẻ: `stat=lambda hub: "3 mục"` trong `MODULE`.
4. Chạy `just web` sau khi đổi `web/` (hoặc để `just web-watch` chạy).

### 10.3 Dữ liệu từ data pack *(nếu admin cung cấp)*

1. **Builder** `viewer_hub/packs/builder.py`: thêm tham số (vd. `--error-dict FILE`), xử lý nặng tại đây, ghi vào `error_dict/…` trong pack và `components["error_dict"] = {...schema...}`.
2. **build.py** `packaging/build.py`: đọc phần tương ứng trong `input/` (vd. `input/error-dict/`) và truyền cho builder; cập nhật README mục 2 (cây thư mục `input/`).
3. **Import** `viewer_hub/packs/importer.py`: nếu thành phần có loại file mới, thêm vào `ALLOWED_SUFFIXES` (không bao giờ thêm file thực thi).
4. **Đọc** trong store: lấy thư mục qua `viewer_hub/packs/content.py: pack_dirs(hub, "error_dict")` — chỉ các pack đang bật.
5. Mục của pack là **chỉ đọc**; id dạng `<pack_id>--<id>` nếu chúng hiện chung danh sách với mục của user (xem CSV/Docs). Không ghi vào `packs/`.
6. Ghi chú/sửa đổi của user về dữ liệu pack: lưu ở `paths.user/error_dict/<pack_id>/…`, khoá theo `pack_id` + id ổn định (không theo version) để không mất khi có pack mới (design §7.4).

### 10.4 Dữ liệu do user thêm *(nếu có)*

- Thư mục `paths.workspace/error_dict/<id>/`, file JSON mô tả cạnh dữ liệu (để `repair` dựng lại), ghi bằng `core/atomic.py`, tạo trong `paths.tmp` rồi `rename`.
- Đăng ký trong `hub.db` cần bảng mới → migration `viewer_hub/migrations/NNNN_….sql`, và cập nhật `core/repair.py`.
- Upload: allowlist phần mở rộng, giới hạn dung lượng, `safe_relative` cho đường dẫn (§5.2).

### 10.5 MCP *(nếu AI agent cần tra cứu)*

Theo mẫu `viewer_hub/fsearch/mcp.py`:
- **Ít tool** (thường 2: tìm → đọc), mô tả ngắn, `readOnlyHint: true`.
- Trả **văn bản thuần, gọn**: mỗi kết quả một dòng + đoạn trích ngắn, mặc định ≤ 5 kết quả, có `offset`/`limit`; đọc chi tiết thì trả đúng đoạn cần (theo `query`) hoặc theo lát cắt.
- HTTP: route `POST /<prefix>/mcp` (kiểm `Origin` loopback, giới hạn body); stdio: thêm lựa chọn vào `viewer-hub mcp` trong `cli.py`, mở `hub.db` **chỉ đọc**.
- Khai báo `mcp=McpServer(path, command, scope, tools)` trong `module.py`; `tools()` trả tên mọi tool AI thấy mặc định.
  Mỗi tool phải có một dòng trong bảng `### Tool cho AI` của `GUIDE.md` (test `tests/test_modules.py` kiểm).
  Bridge tự đăng ký MCP này khi chạy; không thêm tay.
- Không tool nào ghi dữ liệu nếu không có token riêng (như `propose_*` của code-map).

### 10.6 Premium *(nếu chưa phát hành cho mọi người)*

- Thêm `"premium": "error_dict"` vào `addon.json` (module có sẵn không được premium). Khoá thì trang
  chuyển về `/premium`, route khác trả 404; không menu, không mục Hướng dẫn, không MCP.
- Tính năng premium là **addon**: trang của nó là file của addon (`ui/ui.js`), nên bundle của Hub không chứa tên.
- Route của tính năng không cần tự kiểm tra: `addons/routes.py` chặn khi còn khoá.
- Không đặt tên tính năng trong template/JS dùng chung, `title`, `aria-label`, thông báo hay Hướng dẫn khi nó còn khoá.
- Mở: `just unlock error_dict`, dán mã ở trang Premium.

### 10.7 Hướng dẫn sử dụng

**Bắt buộc** với mọi module: `viewer_hub/error_dict/GUIDE.md`, bắt đầu bằng `## <label>` (không đánh số; trang /help tự đánh):
*dùng để làm gì*, *cách dùng trên web*, ý nghĩa các nút (icon `[icon:tên]`); có MCP thì kết thúc bằng
`### Tool cho AI` (bảng `| Tool | AI dùng để |`, mỗi tool một dòng). Không hướng dẫn extract/đóng pack — ghi "liên hệ admin".
Phần chung (mở app, cài đặt, sự cố, AI) ở `viewer_hub/help/parts/`. Module premium chỉ hiện mục khi được mở.

### 10.8 Checklist trước khi merge

- [ ] `just check` xanh (web build, pytest, security, test code map); test mới có test cho store (không qua HTTP), route chính, và: dữ liệu pack chỉ đọc, không đè dữ liệu user, escape HTML, path traversal (nếu có upload/đường dẫn)
- [ ] Không dependency mới (hoặc đã qua §5.3)
- [ ] Xem trên trình duyệt: sáng/tối, màn hẹp (< 600px), trạng thái rỗng, trạng thái chỉ đọc (`hub.readonly`)
- [ ] Không gọi mạng ra ngoài (CSP `default-src 'self'` vẫn giữ)
- [ ] `module.py` + `GUIDE.md` (có `### Tool cho AI` nếu có MCP); `tests/test_modules.py` xanh
- [ ] Premium: khoá thì không lộ tên, route trả 404 (trang về `/premium`); mở bằng mã thì hiện ngay, không cần khởi động lại
- [ ] Đổi định dạng dữ liệu → migration / tăng `schema` thành phần pack
- [ ] Cập nhật: README (nếu `input/` đổi), Hướng dẫn, `docs/design.md` §6 (một mục cho tính năng)

