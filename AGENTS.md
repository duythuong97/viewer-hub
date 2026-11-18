# AGENTS.md: Viewer Hub cho AI agent / người mới

Viewer Hub là app Flask chạy trên máy Windows của user (Python embed, không cài đặt), mở bằng trình duyệt tại
`http://127.0.0.1:<cổng>`. Giao diện là một app React (build sẵn bằng Vite), backend chỉ trả JSON. Mỗi tính năng là một **module**: module có sẵn (package trong `viewer_hub/`) hoặc **addon** (zip cài vào thư mục dữ
liệu, không build lại Hub: `docs/addons.md`). Mọi thứ liệt kê tính năng (menu, trang Hướng dẫn, bảng MCP, MCP Bridge)
đều đọc từ khai báo module, nên thêm module chỉ cần làm trong package của nó.

Chi tiết và lý do: `docs/GUIDELINE.md` (quy tắc), `docs/design.md` (thiết kế). Build / phát hành: `README.md`.

## Cấu trúc

```
viewer_hub/
  app/          factory.py (tạo app, nạp module), modules.py (Module, McpServer, PACKAGES),
                portal.py (/api/app, /api/home, /api/settings, /api/help), spa.py (trang + lỗi JSON), origins.py
  core/         paths, hub.db + settings, migrate, backup, config (cài đặt, cờ premium),
                unlock.py + ed25519.py (mã mở khoá premium), mcp.py (JSON-RPC MCP dùng chung),
                monitor.py (ghi mọi lời gọi MCP vào monitor.db: dispatch + addons/proxy.mcp_call),
                scan.py (quy tắc bảo mật: quét source Hub và addon lúc cài)
  <module>/     một package cho mỗi tính năng:
    module.py     MODULE = Module(...)   ← khai báo: menu, route, hướng dẫn, MCP, premium
    GUIDE.md      mục Hướng dẫn cho user (+ "### Tool cho AI" nếu có MCP)
    routes.py     Blueprint: trang (spa.page()) + JSON API /<prefix>/api/…, lỗi spa.ApiError
    store.py      đọc/ghi dữ liệu, không import Flask
    mcp.py        tool MCP (nếu có): TOOLS, handle(), serve_stdio()
  help/         trang /help: ghép parts/*.md + GUIDE.md của từng module, tự đánh số mục
  packs/        data pack .sapack (đóng trên máy tác giả, import trên máy user)
  addons/       addon: manifest (addon.json), install (zip, chữ ký, quét), runner (managed / daemon), proxy,
                registry (addon → Module), routes (/x/<id>/…, /api/addons), gateway (MCP Bridge), sdk.py (addon Python),
                pack.py (`addon pack`: kiểm tra + ký gói đã build), sdk_kit.py + kit/ (SDK người dùng tải: AGENTS.md, mẫu; sửa hợp đồng addon → sửa kit/AGENTS.md)
  migrations/   đổi format dữ liệu
  templates/    app.html: trang duy nhất, React vẽ mọi thứ
  static/dist/  bản build của web/ (không sửa tay)
web/            Vite, chỉ build-time:
  src/md/         design system Material 3: md.css, react.jsx (Button, TextField, Select, Switch, Dialog, Tabs, FilterBar…)
  src/app/        khung: Shell (menu, thanh trên), router, http.js, ui.jsx (PageHeader, SearchBar, Badge, McpCard,
                  useLoad, useAction), context.jsx (useTitle, useLayout), pages/ (Home, Settings, Help, Premium)
  src/modules/<key>/index.jsx   trang của module (thư mục trùng key)
  src/sdk/        SDK cho trang addon (dist/sdk/*.js: react, jsx-runtime, react-dom, md, ui), API công khai
  src/app/addon.jsx  AddonPanel (trạng thái, chạy / dừng, form setting); pages/Addon.jsx: trang tự sinh của addon
addons/         addon mặc định: *.zip đã ký (commit) đi kèm mọi bản build, tự cài khi mở (addons/README.md)
packaging/      build.py (input/ → pack → zip), build_release.py, addon.py (đóng + ký addon), unlock.py (tạo mã),
                check_security.py, release.justfile (lệnh trong bản phát hành),
                requirements.lock (thư viện đóng vào bản Windows, sinh bằng `just lock`)
tests/          pytest
justfile        mọi lệnh của repo: `just` (chọn bằng fzf), `just --list`
```

Module có sẵn (thứ tự menu = `PACKAGES` trong `app/modules.py`): `codemap`, `fsearch`, `csv`, `docs`, `monitor`. Addon đã
cài đứng sau chúng trên menu. Hub không chứa code của addon nào (MCP Bridge: repo my-bridge tự build addon `mcp-bridge`; SVN: `viewer-hub-addons/svn`, addon mặc định trong `addons/`; dữ liệu SVN cũ chuyển sang bằng `addons/legacy.py`).

**Tính năng mới: ưu tiên làm addon** (`docs/addons.md`, SDK `viewer_hub/addons/kit/`): project riêng ra zip, cài trên
trang Cài đặt hoặc làm addon mặc định (`just addon-default`), không cần bản Hub mới. Module có sẵn chỉ cho phần lõi gắn chặt với dữ liệu Hub.

## Thêm một module

1. Tạo `viewer_hub/<key>/` với `routes.py`, `store.py` (xem module `csv` làm mẫu, đủ cả MCP):
   ```python
   bp = Blueprint("<key>", __name__)

   @bp.get("/")
   def index():
       return spa.page()                      # mọi URL trang trả app React

   @bp.get("/api/items")
   def items():
       return {"items": [...]}                # dữ liệu: JSON; lỗi: raise spa.ApiError("code", "Thông báo", 400)
   ```
2. Khai báo trong `viewer_hub/<key>/module.py`:
   ```python
   from pathlib import Path
   from viewer_hub.app.modules import McpServer, Module

   def _register(app):
       from viewer_hub.<key>.routes import bp
       app.register_blueprint(bp, url_prefix="/<prefix>")

   def _tools():
       from viewer_hub.<key>.mcp import TOOLS
       return [tool["name"] for tool in TOOLS]

   MODULE = Module(
       key="<key>", label="<Tên trên menu>", icon="<material_symbol>", prefix="/<prefix>",
       summary="<một câu: dùng để làm gì>",
       register=_register, guide=Path(__file__).with_name("GUIDE.md"),
       mcp=McpServer("/<prefix>/mcp", "<command>", scope="<AI thấy gì>", tools=_tools),  # bỏ nếu không có MCP
   )
   ```
3. Thêm `"viewer_hub.<key>"` vào `PACKAGES` trong `viewer_hub/app/modules.py`, đúng vị trí trên menu.
4. **Viết `GUIDE.md`** (bắt buộc): bắt đầu bằng `## <label>`, không đánh số. Viết cho user, không phải dev:
   dùng để làm gì, cách dùng từng bước trên web, ý nghĩa các nút (`[icon:tên]` hiện thành icon). Dữ liệu do admin
   chuẩn bị thì ghi "liên hệ admin", không hướng dẫn đóng pack.
5. **Có MCP thì khai báo tool ngay trong `GUIDE.md`**, ở cuối mục:
   ```markdown
   ### Tool cho AI
   | Tool | AI dùng để |
   |---|---|
   | `<tool_name>` | <AI dùng tool này khi nào, trả về gì> |
   ```
   Mỗi tên trong `tools()` phải có một dòng (`tests/test_modules.py` kiểm). Thêm lệnh stdio
   `viewer-hub mcp <command>` trong `viewer_hub/cli.py`.
6. **Trang:** `web/src/modules/<key>/index.jsx`, `export default` component nhận `{module, subpath}`
   Mẫu: `web/src/modules/csv/index.jsx`.
   ```jsx
   export default function Page({ module }) {
     useTitle("<Tên trên menu>");                  // thanh trên cùng
     useLayout("wide");                            // bảng / kết quả; bỏ nếu là trang thường
     const { data, reload } = useLoad(() => http.get("/<prefix>/api/items"));
     return <PageHeader subtitle="<một dòng mô tả>">…</PageHeader>;
   }
   ```
   Chỉ dùng component trong `web/src/md/react.jsx` và `web/src/app/ui.jsx`, class / token của `md.css`.
7. Chạy `just check` (mục dưới).

Phần **tự động** từ khai báo, không sửa tay:

| Ở đâu | Lấy gì từ `MODULE` |
|---|---|
| Menu bên trái (`GET /api/app` → `web/src/app/Shell.jsx`) | `label`, `icon`, `prefix` |
| Trang nào hiện ở URL nào (`web/src/app/pages.js`) | `key` → `web/src/modules/<key>/index.jsx` |
| Thẻ trang chủ (`GET /api/home`) | `label`, `icon`, `summary`, `stat(hub)` |
| Route | `register(app)` (và `mounts(hub)` cho module là Flask app riêng, như code map) |
| Trang Hướng dẫn `/help` | bảng các mục (`summary`), mục `GUIDE.md`, bảng địa chỉ MCP (`mcp.path`, `mcp.command`, `mcp.scope`) |
| MCP Bridge | mọi module có `mcp` (cả addon) được đăng ký vào bridge khi bridge chạy (`addons/gateway.py`), tên `viewer-<command>`, URL `http://127.0.0.1:<cổng><path>` |

**Premium:** module hoặc addon khai `premium="<tên>"` (addon: `"premium": "<tên>"` trong `addon.json`) bị khoá tới khi
một mã mở khoá chứa tên đó được nhập (`core/unlock.py`, mã `VH2-…` mang **tên** tính năng, tạo bằng `just unlock <tên>`,
nên addon làm sau vẫn mở được mà không đổi Hub). Khi khoá: không có menu, mục hướng dẫn hay MCP, tên không xuất hiện
trên trang nào (trang `prefix` → `/premium`, còn lại 404). Mở ngay, không cần khởi động lại; file cấu hình không mở được
premium.

## Quy tắc bắt buộc

- **Bảo mật** (máy công ty scan rất chặt, `docs/GUIDELINE.md` §5): không exe đóng gói (addon Node chỉ được kèm
  `node/node.exe`), không tải gì lúc chạy, không
  native addon, không đọc / gom mật khẩu, token, cấu hình của tool khác; chạy tiến trình con chỉ bằng argv (không
  shell) và chỉ ở file đã được `packaging/check_security.py` cho phép. Không dependency mới nếu chưa qua §5.3.
- **Dữ liệu user không bao giờ mất**: ghi atomic (`core/atomic.py`), đổi format = migration, dữ liệu pack chỉ đọc.
- **MCP chỉ đọc**: tool có `readOnlyHint`, trả văn bản gọn; ghi chỉ khi có token riêng và qua hàng chờ duyệt.
- **Giao diện**: React + Material 3 từ `web/src/md`; không template Jinja, không JS rời trong `static/`. Tìm kiếm /
  bộ lọc dùng `SearchBar` + `FilterBar`. Dữ liệu hiện bằng JSX, không `dangerouslySetInnerHTML` với dữ liệu.
- **Ngôn ngữ**: chữ trên giao diện và trong `GUIDE.md` là tiếng Việt; code, comment, docstring tiếng Anh.

## Kiểm tra trước khi xong

Mọi lệnh nằm trong `justfile` (uv + just; macOS và Windows như nhau):
```bash
just check          # web build + pytest + check_security + test code map (JS)
just test -k <tên>  # một phần pytest
```
Chạy Python của repo bằng `uv run python …` (không gọi `.venv/bin/python` trực tiếp). Thêm lệnh mới cho người dùng repo
thì thêm recipe vào `justfile` (có comment một dòng và `[group(...)]`), không thêm script `.sh`/`.cmd` rời.
