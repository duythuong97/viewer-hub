# Viewer Hub — build bản phát hành

Hướng dẫn cho người build: bỏ dữ liệu vào `input/`, chạy một lệnh, lấy file zip trong `dist/` gửi cho mọi người.
Cách dùng app nằm ngay trong app (mục **Hướng dẫn**). Phát triển: [docs/GUIDELINE.md](docs/GUIDELINE.md).

## 1. Chuẩn bị (một lần)

- Cài [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), fzf và Node.js 22+ trên máy build (máy người dùng không cần):
  - macOS: `brew install uv just fzf node`
  - Windows: `winget install astral-sh.uv Casey.Just junegunn.fzf OpenJS.NodeJS.LTS`
- Cài môi trường: `just setup` (uv tự lấy Python 3.12+, tạo `.venv`; `npm ci` cho `web/`).
- Tải **Windows embeddable package (64-bit)** của Python 3.12 từ python.org
  (ví dụ `python-3.12.10-embed-amd64.zip`) và đặt vào thư mục `packaging/`.

Mọi lệnh của repo nằm trong `justfile`. Gõ **`just`** để chọn lệnh bằng fzf (khung bên phải cho xem lệnh sẽ chạy),
`just --list` để xem danh sách, hoặc gọi thẳng `just <lệnh>`.

| Lệnh | Làm gì |
|---|---|
| `just setup` | Cài / cập nhật môi trường (sau mỗi lần pull) |
| `just serve [cổng]` | Chạy Viewer Hub từ source, dữ liệu dev ở `var/dev` |
| `just build` / `build-fast` | Build bản phát hành đầy đủ (mục 3); `build-fast` dùng lại giao diện đã build |
| `just pack` | Chỉ build data pack từ `input/` |
| `just addon-default <zip>` | Thêm / cập nhật addon mặc định (đi kèm mọi bản build, mục 4) |
| `just addon <thư mục>` | Sync SDK, build, đóng + ký một addon vào `dist/addons/` |
| `just addon-sdk-sync <thư mục>…` | Cập nhật SDK (`.sdk/`, `AGENTS.md`) trong thư mục addon |
| `just unlock [tính năng]` | Tạo mã mở khoá premium (không tham số thì hỏi) |
| `just unlock-check [mã]` | Mã này mở gì |
| `just check` | Kiểm tra đầy đủ trước khi commit |
| `just export-solr <url>` | Xuất Solr ra `input/search.sqlite` |
| `just addon-install <zip>` / `addons` | Cài addon vào dữ liệu dev (`var/dev`) / xem addon đã cài |
| `just lock` | Cập nhật phiên bản thư viện (`uv.lock` + `packaging/requirements.lock`) |

## 2. Bỏ dữ liệu vào `input/`

```
input/
├── pack.yaml          ← bắt buộc
├── codemap/           ← thư mục output của code-map (codemap.sqlite, graph.sqlite, manifest.json)
├── search.sqlite      ← dữ liệu F-Search (full-text search), xuất từ Solr (xem bên dưới)
├── csv/               ← các file .csv
│   ├── danh-muc.csv
│   ├── ma-loi.csv
│   └── config.json    ← tuỳ chọn: định dạng csv-viewer cũ + mô tả cho AI
└── docs/              ← mỗi thư mục con là một site tài liệu markdown
    ├── dac-ta/
    └── huong-dan-van-hanh/
```

`csv/config.json` dùng định dạng csv-viewer cũ, khớp file theo `path` (hoặc `<tên>.csv`); mọi khoá đều tuỳ chọn:

```json
{
  "Từ điển cột DB đơn hàng": {
    "path": "data/columns.csv",
    "description": "Mỗi dòng là một cột của một bảng trong DB ORDER: tên bảng, tên cột, kiểu, tên logic.",
    "mcp": true,
    "columnDescriptions": { "TABLE_NAME": "Tên vật lý của bảng" },
    "visibleCols": ["TABLE_NAME", "COLUMN_NAME", "DATA_TYPE"],
    "filterCol": [{ "TABLE_NAME": "==" }]
  }
}
```

| Khoá | Ý nghĩa |
|---|---|
| tên mục (`"Từ điển cột DB đơn hàng"`) | tên bộ dữ liệu trong app |
| `description` | mô tả file — người xem thấy trên trang CSV, AI đọc để chọn đúng file. Thiếu thì lúc build có cảnh báo |
| `mcp` | AI agent được đọc file không; CSV trong data pack mặc định `true` |
| `columnDescriptions` | nghĩa của cột có tên khó hiểu |
| `visibleCols` / `filterCol` | cột được hiện / dòng lọc có sẵn khi mở trang (như csv-viewer cũ) |

Phần nào không có thì bỏ trống; chỉ cần `pack.yaml`:

```yaml
id: core-system            # cố định qua các lần phát hành (a-z, 0-9, dấu -; không dùng "--")
title: Core System         # tên hiện trong app
version: 2026.11.13        # tuỳ chọn; bỏ trống = ngày giờ build. Lần sau phải lớn hơn lần trước
```

Lấy `search.sqlite` từ Solr (Solr phải đang chạy):

```bash
just export-solr http://localhost:8983/solr/documents
```

Lấy `codemap/`: chạy `./codemap.sh extract` trong repo code-map rồi chép thư mục `output` của config vào `input/codemap/`.

## 3. Build

Gõ `just` rồi chọn một trong ba lệnh build (hoặc gọi thẳng):

| Lệnh | Build gì |
|---|---|
| `just build` | Bản phát hành đầy đủ: app + dữ liệu `input/` + addon mặc định trong `addons/`, build lại giao diện |
| `just build-fast` | Như trên nhưng dùng lại giao diện đã build (khi không sửa `web/` từ lần trước) |
| `just pack` | Chỉ data pack `.sapack`: cập nhật dữ liệu cho người đã cài |

Trước khi build, lệnh in ra dữ liệu tìm thấy trong `input/` và addon sẽ được đóng kèm.

Kết quả trong `dist/`:

| File | Dùng để |
|---|---|
| `ViewerHub-<phiên bản>.zip` | **Gửi cho mọi người.** Đã gồm Python, app, data pack, addon và `justfile`; premium khoá, mở bằng mã |
| `<id>-<version>.sapack` | Data pack riêng (đã nằm sẵn trong zip) |
| `SHA256SUMS.txt` | Mã kiểm tra các file zip |

Gọi script trực tiếp: `uv run python packaging/build.py [--pack-only] [--skip-web]`.

**Phát hành trên GitHub** ([.github/workflows/release.yml](.github/workflows/release.yml)): mỗi lần push, GitHub Actions
chạy test, quét bảo mật và build thử. Đẩy một tag đúng phiên bản (`viewer_hub/__init__.py`) để ra bản phát hành:

```bash
git tag v0.1.0 && git push origin v0.1.0     # → GitHub Releases: ViewerHub-0.1.0.zip + SHA256SUMS.txt
```

Bản trên GitHub **không có data pack** (`input/` không nằm trong repo): người dùng import `.sapack` riêng, hoặc tự đóng
theo `input/README.md` trong bản phát hành. Addon mặc định đã ký sẵn trong `addons/` nên CI không cần khoá ký.
Bản build còn được giải nén và chạy thử trên Windows (Python của python.org) trước khi đăng.

**Chỉ cập nhật dữ liệu** (`just pack`): gửi file `.sapack` trong `dist/`; người dùng vào **Cài đặt → Import .sapack**.

**Đóng data pack không cần source.** Bản phát hành có sẵn `justfile`: trên máy nào đã giải nén zip (và cài `just`),
bỏ dữ liệu vào `input/` cạnh `viewer-hub.cmd` rồi chạy `just pack` (hoặc `viewer-hub.cmd pack`), ra `dist/<id>-<version>.sapack`;
`just pack-install` import luôn vào máy đó. Các lệnh khác: `just serve`, `just import <file>`, `just addon-install <zip>`,
`just backup`. Dữ liệu cũ của họ (CSV, Docs, ghi chú) không bị đè; pack cũ hơn bản đang dùng sẽ không tự bật.

Tuỳ chọn khác khi gọi thẳng: `--input <thư mục>` (mặc định `input/`), `--python-embed <file zip>` (nếu không để trong `packaging/`).

**Mở khoá premium bằng mã.** Mọi bản build giống nhau; tính năng premium nằm sẵn nhưng khoá. Người dùng vào mục
**Premium**, dán mã mở khoá, bấm **Mở khoá**: tính năng mở ngay (không cần khởi động lại) và mã được lưu trong `hub.db`.
Tạo mã trên máy admin:

```bash
just unlock bridge         # mỗi lần chạy ra một mã ngẫu nhiên khác, mã nào cũng dùng được
just unlock-check <mã>     # mã này mở gì
```

Mã được ký bằng khoá bí mật `~/.viewer-hub/unlock-signing.key`, file này **không nằm trong repo, phải sao lưu riêng**.
App chỉ chứa khoá công khai, nên đọc code cũng không tự tạo được mã. Mất khoá thì không tạo được mã mới; tạo khoá mới
(`just unlock-keygen`) thì mọi mã đã phát mất hiệu lực. Mã không gắn với máy: ai có mã cũng mở được.

## 4. Addon (tính năng thêm, không build lại Viewer Hub)

Addon là một zip (`addon.json` + chương trình Python / Node + trang React tuỳ chọn + `GUIDE.md`), cài vào thư mục dữ
liệu của người dùng. Thiết kế: [docs/addons.md](docs/addons.md). Mỗi addon là **một project riêng** tự build ra zip
theo SDK; Viewer Hub không chứa code của addon nào.

**Cài addon:** **Cài đặt → Addon → Cài addon (.zip)** (không cần khởi động lại) hoặc `viewer-hub addon install <zip>`.
Lúc cài, zip được kiểm tra: tên file an toàn, chữ ký, quy tắc bảo mật (không exe / native trừ `node/node.exe`, không
`shell=True`, `eval`, `innerHTML`); addon chưa ký hiện "do admin cung cấp". Gỡ addon giữ lại dữ liệu của nó.

**Addon mặc định** ([addons/](addons/README.md)): zip đặt trong `addons/` được `just build` đóng kèm bản phát hành và
**tự cài khi mở** (bản mới hơn thay bản cũ), người dùng không phải upload. Zip đã ký được commit vào git (CI build bản phát hành không cần khoá ký).

```bash
just addon-default ../viewer-hub-addons/my-bridge/dist/mcp-bridge-0.4.1.zip   # kiểm tra, chép vào addons/ (bỏ bản cũ của cùng addon)
just addon-install addons/mcp-bridge-0.4.1.zip              # thử trên dữ liệu dev, rồi `just serve`
```

**Viết addon** (không cần source Viewer Hub): **Cài đặt → Addon → Tải SDK** (hoặc `just addon-sdk`). Thư mục SDK
chính là addon (một cấu trúc cho managed và daemon): `npm run new -- simple|daemon <id>`, viết theo `AGENTS.md` (nhờ
AI), `npm run zip`, tải zip lên (hoặc tự nén cả thư mục). Chi tiết: docs/addons.md §8.1.

**MCP Bridge** là addon `mcp-bridge` của repo **my-bridge** (premium `bridge` do my-bridge khai báo). my-bridge tự build
cả chương trình lẫn trang của nó:

```bash
cd ../viewer-hub-addons/my-bridge && npm run release -- --node-zip <node-vX.Y.Z-win-x64.zip>   # → dist/mcp-bridge-<ver>.zip (đã ký nếu có khoá)
cd ../../viewer-hub && just addon-default ../viewer-hub-addons/my-bridge/dist/mcp-bridge-<ver>.zip   # đi kèm bản build tới
```

`--node-zip` (bản chính thức từ nodejs.org) đưa `node.exe` vào addon; thiếu thì máy Windows phải tự cài Node.js 22.13+.
Sau khi mở khoá (`just unlock bridge`), Viewer Hub **tự chạy bridge khi mở** và quản trị nó trên trang
**MCP Bridge** (trang do my-bridge làm): chạy / dừng / khởi động lại, thư mục Box, "tự chạy khi mở Viewer Hub", server,
request chờ duyệt. Bridge là tiến trình riêng: tắt Viewer Hub thì nó vẫn phục vụ Copilot Studio. Khi bridge chạy,
Viewer Hub **tự đăng ký mọi MCP của nó** (cả MCP của addon khác) vào bridge: `viewer-codemap`, `viewer-search`,
`viewer-csv`, `viewer-svn`… (HTTP `http://127.0.0.1:<cổng>/…/mcp`, chỉ tool đọc). Các tool này chỉ gọi được khi Viewer
Hub đang mở.

**SVN** là addon mặc định (repo `viewer-hub-addons/svn`, zip trong `addons/`, tự cài khi mở; không phải premium): trang
**SVN** + MCP để AI đọc file thẳng trên repo SVN theo đúng branch / tag / revision, không cần checkout. Trên trang SVN
khai báo repo được phép đọc (tên, URL gốc, mô tả); AI chỉ đọc được URL nằm dưới các repo này. Tool: `svn_repos`,
`svn_branches`, `svn_list`, `svn_read` (cả file hoặc khoảng dòng / tìm chữ), `svn_log`, `svn_diff`. Địa chỉ:
`http://127.0.0.1:<cổng>/x/svn/mcp` (địa chỉ cũ `/svn/mcp` được chuyển tiếp) hoặc `viewer-hub mcp svn`; khi bridge
chạy thì được tự đăng ký là `viewer-svn`. Danh sách repo của bản Hub cũ (khi SVN còn là module) được chép sang addon
lần đầu mở bản mới.

Addon chỉ gọi lệnh `svn` (info / list / cat / log / diff, `--non-interactive`), không đọc hay lưu mật khẩu: đăng
nhập dùng thông tin svn đã lưu sẵn trên máy (vd. đã checkout / đăng nhập bằng TortoiseSVN một lần). URL có kèm
user:mật khẩu bị từ chối. Máy dùng cần có lệnh `svn`:

- Windows: cài TortoiseSVN, chọn thêm **command line client tools** (addon tìm cả trong
  `C:\Program Files\TortoiseSVN\bin`).
- macOS: `brew install subversion`.
- Đường dẫn khác: đặt biến môi trường `VIEWER_HUB_SVN=<đường dẫn tới svn>`.

Gỡ một addon mặc định trên trang Cài đặt thì nó **không tự cài lại** khi mở Viewer Hub (kể cả bản build mới có zip
mới hơn), cho tới khi tự cài lại bằng tay.

## 5. Gửi cho người dùng

Người dùng giải nén zip rồi mở:

- **Windows:** nhấp đúp **`ViewerHub-<phiên bản>\viewer-hub.cmd`** (ví dụ giải nén vào `%LOCALAPPDATA%\Programs\ViewerHub\`). Không cần cài đặt hay quyền admin.
- **macOS / Linux:** cần Python 3.12+ có sẵn trên máy (python.org hoặc `brew install python`), rồi chạy:
  ```bash
  ./ViewerHub-<phiên bản>/viewer-hub.sh
  ```

Cách dùng app có trong app (mục **Hướng dẫn**), không kèm file riêng.

Phiên bản mới: giải nén cạnh bản cũ và mở `viewer-hub.cmd` của bản mới. Dữ liệu người dùng
(`%LOCALAPPDATA%\ViewerHub\`) dùng chung cho mọi phiên bản nên giữ nguyên; bản cũ có thể xoá sau.

*Tuỳ chọn:* chạy `setup.cmd` trong thư mục phiên bản để có một đường dẫn mở cố định
`%LOCALAPPDATA%\Programs\ViewerHub\viewer-hub.cmd` (luôn mở bản vừa setup). Chỉ cần khi muốn shortcut
hoặc cấu hình MCP dạng stdio không phải sửa mỗi lần cập nhật.

Trước khi gửi, nên chạy trên một máy Windows sạch:

```
ViewerHub-<phiên bản>\python\python.exe -I -c "import yaml, markupsafe, chardet, flask, waitress, mkdocs.commands.build, material"
```

## Kiểm tra trước khi build (người sửa code)

```bash
just check     # build giao diện, pytest, quy tắc bảo mật, test code map
```
