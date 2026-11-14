# Viết addon cho Viewer Hub (SDK {{sdk}})

Tài liệu cho AI agent (và người) viết **addon**: tính năng thêm cho Viewer Hub, đóng thành một file zip, người dùng
cài ở **Cài đặt → Addon** mà không cần bản Viewer Hub mới. Đọc hết file này trước khi viết code. Mọi chữ hiện cho
người dùng (menu, nút, thông báo, GUIDE.md) viết **tiếng Việt**; tên trong code, comment viết tiếng Anh.

Bản SDK này đi kèm Viewer Hub {{version}}. `.sdk/python/viewer_hub/` là mã thật của SDK Python (`addons/sdk.py` và
những gì nó import): đọc để biết chi tiết, `npm test` dùng nó để chạy test không cần Hub (§8). Đừng chép vào addon:
lúc chạy, Hub cung cấp nó.

---

## 1. Chọn loại addon

| Loại | Khi nào | Ví dụ |
|---|---|---|
| `managed` + `python` (**mặc định, chọn cái này nếu không chắc**) | Hàm, API cho trang, tool MCP cho AI; không cần chạy khi không ai dùng | đọc Jira, tra cứu file, ghi chú |
| `managed` + `node` | Như trên nhưng code sẵn có là Node (không có SDK, tự làm HTTP: §4.2) | thư viện chỉ có cho JS |
| `daemon` + `node` hoặc `python` | Một chương trình **chạy lâu, có vòng đời riêng** (vẫn chạy khi đóng Viewer Hub), Hub chỉ bật / tắt / hỏi trạng thái | MCP Bridge, đồng bộ nền |
| `external` | Chương trình **đã có sẵn, viết bằng ngôn ngữ khác** (.NET, Java, Go…), người dùng tự cài và tự chạy; khó chuyển sang Python / Node | công cụ nội bộ .NET có web API |

- `managed`: Hub chạy tiến trình khi có request đầu tiên, dừng khi Hub thoát. Hub giữ tiến trình.
- `daemon`: chương trình tự sống; Hub gọi các lệnh `init` / `start` / `status` của nó và nói chuyện qua **kênh
  quản trị** (named pipe / Unix socket).
- `external`: Hub **không chạy gì**: addon chỉ có `addon.json`, `GUIDE.md`, trang `ui/`; Hub chuyển request của trang
  và của AI tới chương trình của người dùng trên `127.0.0.1:<cổng>` (§5.4). Không bao giờ đóng `.exe` / `.dll` vào addon.

Bắt đầu: `npm run new -- simple <id>` (managed python + trang + 2 tool MCP), `npm run new -- daemon <id>`
(daemon node + trang + SSE) hoặc `npm run new -- external <id>` (nối tới chương trình có sẵn) ngay trong thư mục này; rồi sửa `name`, `menu` và code. Loại nào cũng **cùng một cấu
trúc** (§2) và cùng một cách đóng gói (§8).

## 2. Cấu trúc một addon (một kiểu duy nhất)

**Thư mục này chính là addon.** Mỗi addon một thư mục (giải nén SDK một lần cho mỗi addon). Tên thư mục không quan
trọng (zip và Hub dùng `id`), đặt theo id cho dễ nhận. Không có thư mục con `addon/`, không có bước chép: zip thư
mục là cài được.

```
<id>/
  addon.json              khai báo (bắt buộc, §3)
  GUIDE.md                hướng dẫn cho người dùng (bắt buộc, §7)
  main.py | main.mjs      "entry": luôn là main.py (python) hoặc main.mjs (node), ở gốc (external: không có)
  lib/                    (tuỳ chọn) code đi kèm: package thuần Python (tự thêm vào sys.path) / module .mjs
  ui/                     trang đã build (npm run build), cài cùng addon
  …                       file dữ liệu chỉ đọc khác của addon (vd. packs/)

  # phát triển, KHÔNG được cài (Hub bỏ qua, zip của SDK bỏ ra):
  web/                    mã nguồn trang (web/index.jsx → ui/ui.js)
  src/                    (node, khi cần package npm) src/main.mjs → bundle thành main.mjs
  test/ tests/            test của bạn
  dist/                   zip đã đóng gói
  node_modules/ package.json package-lock.json AGENTS.md CLAUDE.md README.md
  .sdk/ .gitignore .git/  (mọi file / thư mục bắt đầu bằng ".", cả __pycache__/, *.pyc, __MACOSX/)
```

- **Node có package npm** (vd. `oracledb`): viết ở `src/main.mjs`, `npm install <package>`; `npm run build`
  bundle tất cả vào một file `main.mjs` (esbuild). Package có file native (`.node`) không cài được (§7): chọn bản
  JS thuần (vd. oracledb "thin mode").
- **Python** chỉ thư viện chuẩn + package thuần Python chép vào `lib/` (§4.1).
- Daemon là chương trình lớn ở repo riêng? Xem §5.2.

Addon được cài vào `<data>/addons/<id>/` (**chỉ đọc**: bị thay khi cập nhật); dữ liệu của nó ở
`<data>/user/addons/<id>/` (giữ qua cập nhật, gỡ, sao lưu).

## 3. addon.json

```json
{
  "schema": "viewer-hub/addon", "schemaVersion": 1, "sdk": "{{sdk}}",
  "id": "jira-reader", "name": "Jira Reader", "version": "0.1.0",
  "runtime": "python", "entry": "main.py", "lifecycle": "managed",
  "menu": {"label": "Jira", "icon": "bug_report", "summary": "Đọc ticket Jira cho AI và trên web"},
  "ui": {"script": "ui/ui.js", "style": "ui/ui.css"},
  "mcp": {"command": "jira", "scope": "chỉ project đã thêm", "tools": ["jira_search", "jira_read"]},
  "settings": [{"key": "baseUrl", "label": "Địa chỉ Jira", "type": "text"}],
  "premium": null
}
```

| Trường | Quy tắc |
|---|---|
| `id` | `^[a-z][a-z0-9-]{1,40}$`, duy nhất; không trùng mục có sẵn (`codemap`, `fsearch`, `csv`, `docs`, `monitor`, `settings`, `help`, `premium`, `api`, `sdk`, `static`, `x`: bị từ chối). Trùng id addon đã cài = cập nhật addon đó (kể cả addon mặc định như `svn`), nên chọn id riêng. Trang ở `/x/<id>` |
| `version` | `1.2.3` (thêm `-beta.1` được). Tăng mỗi lần gửi bản mới |
| `runtime` / `entry` | `python` + `*.py`, hoặc `node` + `*.mjs` / `*.js`; file nằm ở gốc addon |
| `lifecycle` | `managed`, `daemon` hoặc `external` (§1) |
| `menu` | `label` (≤ 40 ký tự, tên trên menu), `icon` (tên [Material Symbols](https://fonts.google.com/icons), vd. `bug_report`), `summary` (một câu) |
| `ui` | Tuỳ chọn. `script` (`ui/<tên>.js`), `style` (`ui/<tên>.css`). Không có `ui`: Hub tự làm trang (trạng thái, cài đặt, MCP, GUIDE.md) |
| `mcp` | `managed` hoặc `external` (daemon không có). `command`: tên lệnh (`viewer-hub mcp <command>`), không trùng lệnh có sẵn (`codemap`, `search`, `csv`, `monitor`) hay của addon khác; `scope`: AI đọc được gì; `tools`: tên mọi tool (`^[a-z0-9_]+$`, nên có tiền tố chung) |
| `settings` | Form cài đặt trên trang addon. Mỗi mục: `key`, `label`, `type` (`text`, `folder`, `list`, `switch`, `select` + `options`), `default`, `help`, `required` (true: trang báo "Cần điền …" tới khi có giá trị). Daemon: thêm `arg` (`--ten`) và `on` (`init` / `start`): Hub truyền `<arg> <giá trị>` cho lệnh đó |
| `commands` | Chỉ `daemon`, bắt buộc: `{"init": [...], "start": [...], "status": [..., "--json"]}`: tham số đơn giản, không có shell |
| `minNode` | (node) phiên bản Node tối thiểu, vd. `"22"` |
| `provides` | (daemon) `["mcp-servers"]` nếu daemon gom MCP server (như MCP Bridge, §5.3). Không thì bỏ |
| `premium` | `null`. (Tên tính năng nếu admin bán kèm mã mở khoá; chỉ admin của Viewer Hub đặt) |

## 4. Addon managed

Biến môi trường Hub truyền cho mọi addon:

| Biến | Là gì |
|---|---|
| `VIEWER_HUB_ADDON_ID` | id |
| `VIEWER_HUB_ADDON_DATA` | thư mục dữ liệu riêng, **chỗ duy nhất addon được ghi** |
| `VIEWER_HUB_ADDON_SETTINGS` | file JSON các giá trị form cài đặt (Hub ghi, addon đọc) |
| `VIEWER_HUB_ADDON_TOKEN` | managed: token của lần chạy này |

### 4.1 Python: dùng SDK

Chạy bằng Python của Viewer Hub (`python -I`). **Chỉ thư viện chuẩn** + package thuần Python chép vào `lib/`
(không có `.pyd` / `.so`: bị từ chối khi cài). Không dùng `pip install` lúc chạy.

```python
from viewer_hub.addons.sdk import Addon, ApiError, ToolError, int_arg

addon = Addon("jira", title="Jira Reader", instructions="Read-only Jira for AI: search, then read.")  # tên = mcp.command

@addon.get("/issues")                      # trang gọi: api.get("/issues")  →  GET /x/<id>/api/issues
def issues(request):                       # request.method, .path, .params, .query (dict str), .body (JSON), .headers
    base = addon.settings().get("baseUrl")  # giá trị form cài đặt
    if not base:
        raise ApiError("not_configured", "Chưa nhập địa chỉ Jira ở phần Cài đặt", 400)
    return {"issues": []}                  # dict / list → JSON

@addon.post("/issues/<key>/star")          # <tên> → request.params["key"]; có .put(), .patch(), .delete(), .route(method, ...)
def star(request): ...

@addon.tool("jira_read", "Full text of one issue by key, e.g. ABC-12.",
            {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]})
def jira_read(arguments):                  # arguments: dict theo inputSchema
    limit = int_arg(arguments, "limit", 20, 1, 100)  # số nguyên (mặc định, nhỏ nhất, lớn nhất); sai kiểu → ToolError
    return "text for the AI"               # str (hoặc ToolResult); lỗi cho AI: raise ToolError("...")

if __name__ == "__main__":
    addon.run()                            # bắt buộc: Hub chạy "main.py serve --port N"
```

- `Addon(name, title=, instructions=)`: `name` là tên MCP server AI thấy, đặt bằng `mcp.command`; `title` tên hiển thị,
  `instructions` hướng dẫn chung cho AI (tiếng Anh).
- `addon.data`: `Path` thư mục dữ liệu. Ghi file kiểu ghi tạm rồi `replace()` (xem mẫu).
- Lỗi API trả `{"error": {"code", "message"}}`; `message` là tiếng Việt cho người dùng. Exception khác → 500 và ghi log.
- Tool MCP **chỉ đọc** (Hub ẩn và từ chối tool nào không chỉ đọc). Mô tả tool bằng tiếng Anh, ngắn, nói rõ trả gì.
- Mỗi request chạy trên một thread: dữ liệu dùng chung cần `threading.Lock`.
- **Tiếng Nhật và encoding khác UTF-8** (file của dự án Nhật thường là Shift_JIS / CP932 hoặc EUC-JP): đừng
  `bytes.decode("utf-8")` hay `read_text()` không tham số. Dùng `decode_text(data, name="") → (text, encoding)`:
  theo BOM, theo khai báo trong file (`<?xml encoding=…?>`, `<meta charset>`, `coding:`), rồi tự nhận UTF-8 /
  UTF-16 / CP932 / EUC-JP, cuối cùng CP1252; không bao giờ ném lỗi. `looks_binary(data)` để từ chối file nhị phân.
  Tìm kiếm: so `fold(query) in fold(text)` (NFKC + bỏ hoa thường: `ｶﾀｶﾅ` = `カタカナ`, `ＡＢＣ` = `ABC`). Ghi file của
  addon luôn `encoding="utf-8"`; file của người dùng thì giữ nguyên byte (`write_bytes`). Cả ba import từ
  `viewer_hub.addons.sdk`.
- Gọi mạng (`urllib.request`) được, nhưng Hub sẽ hiện **lưu ý** cho admin lúc cài (§7). Chỉ gọi địa chỉ người dùng nhập.
- `print` / `logging` → log của addon (Cài đặt → Addon → trang addon → log khi lỗi; file `<data>/logs/addon-<id>.log`).

### 4.2 Node (managed): tự làm HTTP

`node <entry> serve --port N`: nghe **chỉ** `127.0.0.1:N`; từ chối (403) mọi request thiếu header
`X-Viewer-Hub-Token` = `VIEWER_HUB_ADDON_TOKEN`. Trả JSON:

- `GET /health` → `{"ok": true}` (Hub chờ cái này sau khi chạy, tối đa 20 giây)
- `/api/<path>` (mọi method) ← trang gọi `/x/<id>/api/<path>`; lỗi: `{"error": {"code", "message"}}`
- `POST /mcp`: MCP JSON-RPC (`initialize`, `tools/list`, `tools/call`; thông báo → 202). Mỗi tool phải có
  `"annotations": {"readOnlyHint": true}`
- `POST /shutdown` → trả 200 rồi thoát
- Khi biến môi trường `VIEWER_HUB_PARENT_PIPE=1`: đọc stdin tới hết rồi thoát (Hub giữ một pipe ở stdin và không ghi gì;
  pipe đóng = Hub đã tắt hay bị kill). Addon Python được Hub làm sẵn việc này; addon Node phải tự làm:
  `process.stdin.on("end", () => process.exit(0)); process.stdin.resume();`
- Tiếng Nhật: Node có sẵn `new TextDecoder("shift_jis")` / `"euc-jp"` / `"utf-16le"` để đọc file không phải UTF-8;
  tìm kiếm so `text.normalize("NFKC").toLowerCase()`. JSON trả về luôn UTF-8.

## 5. Addon daemon

### 5.1 Hợp đồng

Hub chạy `<node|python> <entry> <commands.X> <tham số từ settings>` (thư mục làm việc = thư mục addon, cùng biến
môi trường §4, Windows: node là `node/node.exe` trong addon nếu có, không thì `node` của máy):

| Lệnh | Phải làm |
|---|---|
| `init` | Chuẩn bị (thư mục, config, nhận `arg` của settings `on: "init"`). Thoát 0 khi xong. Chạy **trước mỗi lần** start, nên phải chạy lại được nhiều lần và **không được đè** config user đã chỉnh: không có `arg` thì giữ nguyên. Hub chỉ truyền một `arg` của init khi user vừa đổi giá trị đó trên Hub (so với lần truyền trước), nên chỉnh bằng CLI / trang riêng của daemon không bị Hub ghi đè lúc khởi động lại. `arg` của `on: "start"` thì luôn được truyền (chỉ cho lần chạy đó) |
| `start` | Chạy **foreground** tới khi được bảo dừng. Hub tự đưa vào nền (Windows: cửa sổ console thu nhỏ, không ẩn; macOS/Linux: session riêng) và ghi **mọi dòng stdout / stderr** vào log của Hub (`addon-<id>.log`, xoay vòng ~2 MB, xem ở nút **Nhật ký**): in log ra stdout, không cần tự làm trang log. Đã có bản đang chạy thì thoát 0 |
| `status --json` | In **một dòng JSON**: `{"running": bool, "adminChannel": "<đường dẫn>", ...}`. Thoát 0 cả khi daemon đang dừng (nó không cần daemon chạy) |

**Kênh quản trị** (`adminChannel`): Windows named pipe `\\.\pipe\<tên riêng của addon>-<user>`, macOS/Linux Unix
socket (trong `VIEWER_HUB_ADDON_DATA`, quyền 0600). **Không bao giờ mở cổng TCP** cho Hub. Giao thức: mỗi kết nối
một request, một dòng JSON:

```
→ {"method": "GET", "path": "/api/state", "query": {"a": "1"}, "body": {...}}
← {"status": 200, "body": {...}}            rồi đóng kết nối

→ {"method": "EVENTS"}
← {"event": "keepalive", "data": {}}        NGAY LẬP TỨC (Hub chờ dòng đầu), rồi mỗi ~15 giây
← {"event": "tick", "data": {"ticks": 3}}   mỗi sự kiện một dòng, giữ kết nối tới khi một bên đóng
```

Bắt buộc có: `GET /api/health` → 200 (Hub dùng để biết đang chạy), `POST /api/daemon/shutdown` → 200 rồi tự thoát.
Trang gọi `api.get("/state")` → Hub chuyển thành `GET /api/state` trên kênh; `api.events()` → `EVENTS`, đến
trang dưới dạng server-sent events (`event: tick`).

Mẫu đầy đủ, không dependency: `npm run new -- daemon <id>` → `main.mjs`. Chạy thử không cần Hub:
`node main.mjs init && node main.mjs start` rồi (cửa sổ khác) `node main.mjs status --json`.

### 5.2 Daemon là chương trình lớn ở repo riêng

Addon zip phải **tự chứa đủ**: chương trình nằm trong thư mục addon. Cách đơn giản nhất vẫn là cấu trúc §2: code
ở `src/` (TypeScript / nhiều file được: `src/main.mjs` import chúng), `npm run build` gom thành `main.mjs`.

Repo đã có sẵn (có build và zip phát hành riêng, vd. MCP Bridge) thì: repo tự bundle chương trình ra `main.mjs`
của thư mục addon, hoặc đóng addon bằng `{{hub}} addon pack <thư mục addon> --include <zip phát hành>` (zip có
**một thư mục gốc `<Tên>-<version>`**; pack chép chương trình vào addon, bỏ script khởi chạy `.cmd` / `.sh`, lấy
version theo tên thư mục đó).

Dù cách nào: chương trình phải hiểu 3 lệnh ở §5.1 (thêm một lớp `cli` nhỏ nếu chương trình có CLI khác) và ghi
dữ liệu vào `VIEWER_HUB_ADDON_DATA` (hoặc thư mục riêng của nó dưới thư mục người dùng).

### 5.3 Gom MCP (`provides: ["mcp-servers"]`)

Chỉ cho daemon kiểu MCP gateway. Hub sẽ đăng ký MCP của chính nó (và của các addon) vào daemon qua kênh quản trị:
`GET /api/servers` → `{"servers": [{"name", "url", "tools": {"total"}}]}`, `POST /api/servers`
`{"servers": [{"name", "transport": "http", "url", "startMode"}]}`, `POST /api/servers/<name>/refresh`.

Tuỳ chọn, cho trang **Giám sát** của Hub: `GET /api/stats?hours=24` → `{"calls": {"total", "errors"}, "tools": [{"server",
"tool", "calls", "errors", "avgMs", "p95Ms"}]}` (lời gọi daemon nhận, cả MCP ngoài Hub), `GET /api/process` → `{"rss",
"cpuPct"}`. Khi gọi MCP của Hub, gửi header `X-MCP-Client: <tên>/<phiên bản>` để Hub biết lời gọi đi qua daemon.

### 5.4 Addon external (chương trình .NET, Java… có sẵn)

```json
{ "lifecycle": "external", "service": {"port": 5123}, "ui": {"script": "ui/ui.js"},
  "mcp": {"command": "my-service", "tools": ["service_info"]} }
```

Không có `runtime`, `entry`, `commands`. Hub tự thêm vào form **Cài đặt** ô **Cổng của chương trình** (key `port`,
mặc định `service.port`) để người dùng đổi khi chương trình chạy ở cổng khác. Trên trang, Hub vẽ thẻ **Chương trình
ngoài** (đã kết nối / chưa, kiểm tra lại); không có nút chạy / dừng, không có nhật ký (log là của chương trình).

Chương trình (ngôn ngữ nào cũng được) phải phục vụ HTTP trên **chỉ** `127.0.0.1:<cổng>`, giống §4.2 trừ token:

- `GET /health` → 200 (Hub coi là "đã kết nối")
- `/api/<path>` (mọi method) ← trang gọi `/x/<id>/api/<path>`; trả JSON, lỗi `{"error": {"code", "message"}}`
- `POST /mcp` (nếu có `mcp`): MCP JSON-RPC; Hub chỉ cho AI thấy / gọi tool có `"annotations": {"readOnlyHint": true}`

Hub không gửi token (nó không chạy chương trình nên không trao token được): chương trình tự chịu trách nhiệm chỉ
nghe `127.0.0.1` và không có API ghi nguy hiểm. Ví dụ ASP.NET Core (minimal API):

```csharp
var app = WebApplication.Create(args);
app.Urls.Add("http://127.0.0.1:5123");
app.MapGet("/health", () => Results.Ok(new { ok = true }));
app.MapGet("/api/info", () => new { name = "My service", version = "1.0.0", status = "OK" });
app.Run();
```

Người dùng cài chương trình theo cách của chương trình đó (do IT / admin cấp); addon zip chỉ là phần nối vào Hub.

## 6. Trang (UI)

`web/index.jsx` export default một React component; Hub truyền props:

| Prop | Là gì |
|---|---|
| `module` | `{key, label, path, icon, mcp: {path, command} \| null}` của addon (`module.key` = id, `module.path` = `"/x/<id>"`) |
| `subpath` | phần đường dẫn sau `/x/<id>` (`"/"`, `"/issues/ABC-1"`): trang con tự route bằng nó |
| `addon` | trạng thái addon từ Hub: `addon?.running`, `addon?.values` (giá trị cài đặt)…; `null` lúc đang tải |
| `api` | gọi API của addon: `api.get(path, params)`, `.post(path, body)`, `.put`, `.patch`, `.delete(path)`, `.upload(path, formData)`, `.url(path)`, `.events(path = "/events")` (EventSource). Lỗi: `ApiError` có `.message` tiếng Việt |

Chỉ được import: `react`, `react-dom`, `@vh/md`, `@vh/ui`, `@vh/mermaid`, `@vh/flow` (Hub cung cấp lúc chạy, không bundle) và
thư viện JS thuần của riêng bạn (`npm install <package>`, được bundle vào `ui.js`). Thư viện vẽ DOM lớn (d3,
Mermaid...) thường dùng `innerHTML` nên bị từ chối khi cài: cần sơ đồ thì dùng `@vh/mermaid`.

- `@vh/md` (Material 3): `Icon`, `Button` (`variant`: text / filled / tonal / outlined, `icon`, `danger`), `IconButton`
  (`icon`, `label` bắt buộc, `danger`), `TextField` (`type="textarea"`, `rows`, `supportingText`, `leadingIcon`), `Select`
  (`options: [[value, label]]`), `Switch`, `Checkbox`, `Dialog` (`headline`, `icon`, `actions(close)`, `onClose`),
  `Tabs` (`tabs: [[value, label, icon]]`), `Segmented` (`options: [[value, label, icon]]`, `value`, `onChange`, `label`),
  `Chip` (`selected`, `onClick`, `children`), `InputChip` (`label`, `onRemove`), `FilterBar` (`filters: [{key, label,
  value, defaultValue, options: [[value, label]]}]`, `onApply(values)`), `Progress`, `Loading`, `ErrorBanner`, `Empty`
  (`icon`, `title`, `children`).
- `Dialog`: không có prop `open`: render khi cần mở, bỏ khi đóng (`{form ? <Dialog …/> : null}`). Nội dung là
  `children`; `actions(close)` vẽ nút, `close()` đóng có hiệu ứng rồi gọi `onClose`; `wide` cho hộp rộng.
- **Hub vẽ sẵn phần đầu mọi trang addon**, một hàng: mô tả (`summary`) bên trái; bên phải trạng thái (daemon:
  `Đang chạy` / `Đã dừng`, bấm vào mở hộp điều khiển chạy / dừng / khởi động lại / tự chạy; external: `Đã kết nối`),
  nút **Nhật ký**, nút **Cài đặt** (form `settings` trong hộp thoại). Banner chỉ hiện khi người dùng phải làm gì:
  dịch vụ đang dừng, chưa kết nối chương trình, lỗi, thiếu setting `required`. Trang của bạn bắt đầu ngay dưới, nhận
  `addon` (`addon?.running`, `addon?.values`...; `null` lúc đang tải). **Không** tự làm nút chạy / dừng, form cài đặt
  hay màn xem log: in log ra stdout / stderr, Hub ghi và hiện. Trang lỗi thì phần đầu của Hub vẫn dùng được.
- `useAddon()` (từ `@vh/ui`) → `{ info, openSettings(key?), reload }`: mở hộp **Cài đặt** của Hub từ trang của bạn,
  vd. trạng thái trống "Chưa có kết nối" kèm nút **Thêm kết nối** → `openSettings("connections")`.
- **Bố cục**: độ rộng mặc định của Hub (đừng gọi `useLayout("wide")`, để mọi trang thẳng hàng; chỉ trang canvas
  như sơ đồ `@vh/flow` mới dùng `"wide"`). Danh sách + chi tiết (sơ đồ, ticket, file…) dùng hai cột: danh sách bên trái
  luôn hiện, chi tiết bên phải (class `md-layout-sheet`: cột trái 300px, một cột trên màn hẹp), URL là `subpath`
  (`useRouter().navigate(\`${module.path}/${id}\`, {replace})`); không bắt người
  dùng bấm "quay lại" trên màn hình rộng. Form thêm / sửa ngắn mở trong `Dialog`, không đặt sẵn đầu trang.
- **Không** tự vẽ thẻ "Kết nối AI" / địa chỉ MCP: trang Hướng dẫn của Hub đã có (cùng bảng tool từ GUIDE.md).
- `@vh/ui`: `PageHeader` (`subtitle`), `Badge` (`tone`: success / warning /
  error / primary, `icon`), `useConfirm()` → `[confirm, dialog]` (§6.1), `ListItem` (`icon`, `headline`, `supporting`,
  `children` = nút bên phải; đặt trong `<ul className="md-list">`), `LinkCard` (`to`, `icon`, `title`), `LinkButton`
  (`to`, `icon`, `variant`), `SearchBar` (`value`, `onSubmit(text)`, `placeholder`), `useLoad(fn, deps)` → `{data, error, loading,
  reload}`, `useAction()` → `[run(fn, thôngBáo), busy]`, `useTitle(text)`, `useLayout`, `useApp`, `useRouter`,
  `useQuery`, `useAddon`, `Link` (`to`), `http` (gọi API khác của Hub), `addonApi(id)`, `ApiError`, `uploadWithProgress`.
  `fold(text)` (NFKC + chữ thường: lọc danh sách tiếng Nhật không phân biệt nửa / toàn độ rộng),
  `readFileBody(file)` → `{content}` nếu file là UTF-8, không thì `{base64}` (byte gốc: Shift_JIS, EUC-JP…). Gửi file
  người dùng chọn bằng `api.post(path, {name: file.name, ...(await readFileBody(file))})`, **không** dùng
  `file.text()` (trình duyệt luôn đọc là UTF-8, file Shift_JIS hỏng chữ); phía Python: `decode_text(base64.b64decode(…))`.
- `@vh/mermaid` (Mermaid của Hub, chế độ an toàn, chỉ tải khi vẽ lần đầu): `render(text, {theme})` → `{svg}`
  (`theme`: `"page"` theo Hub, `"export"` nền sáng cho file), `parse(text)` (ném `Error` cú pháp dễ đọc),
  `svgElement(svg)` → phần tử `<svg>` để `appendChild` (không qua `innerHTML`), `pageIsDark()`.
  ```jsx
  const ref = useRef(null);
  useEffect(() => { render(text).then(({ svg }) => ref.current.replaceChildren(svgElement(svg)), (e) => setError(e.message)); }, [text]);
  ```
- `@vh/flow` (React Flow 12 của Hub, CSS tự thêm khi import): canvas khối / cạnh kéo thả, zoom, nhóm lồng nhau.
  Export lại `ReactFlow`, `ReactFlowProvider`, `Background`, `Controls`, `MiniMap`, `Panel`, `Handle`, `Position`,
  `MarkerType`, `NodeResizer`, `useReactFlow`, `useStore`... (API của `@xyflow/react` 12). `layoutGraph({nodes, edges},
  {direction})` → `Promise<{id: {x, y, width, height}}>`: tự sắp xếp đồ thị lồng nhau (x / y theo nhóm cha) trong Web
  Worker, 10 000 khối cỡ 50 ms. Sơ đồ lớn: truyền `onlyRenderVisibleElements`, kích thước khối cố định.
- Class CSS của Hub: `md-stack` (cột cách 16px), `md-row`, `md-spacer`, `md-card md-card--outlined` >
  `md-card__body` (`md-card__title`, `md-card__subtitle`) + `md-card__actions`, `md-list`, `md-table-wrap` >
  `md-table`, `md-muted`, kiểu chữ `md-body-small`, `md-title-medium`, `md-display-small`...
  Thông báo nhanh: `window.md?.snackbar("Đã lưu")`.
- **Không**: `innerHTML` / `dangerouslySetInnerHTML` với dữ liệu, `eval` / `new Function`, tải gì từ CDN / Internet
  (font, script, ảnh), `fetch` thẳng tới chương trình của addon (luôn qua `api`). Dữ liệu từ API hiện bằng text.
- Mọi request ghi (POST / PUT / PATCH / DELETE) phải qua `api` / `http` (chúng gửi header `X-Viewer-Hub` Hub yêu cầu).

### 6.1 Màu và xác nhận (bắt buộc, giống mọi trang của Hub)

**Màu theo nghĩa**, chỉ qua `Badge tone` / `danger` (không tự đặt mã màu, để trang đúng cả theme sáng và tối):

| tone | Dùng cho |
|---|---|
| `success` | đang chạy, đã bật / cho phép, thành công, đã ký |
| `warning` | đang chờ, đang thử lại, cần duyệt, sắp hết hạn |
| `error` | lỗi, thất bại, có thể nguy hiểm |
| `primary` | thông tin cần nổi bật (vd. "Đọc") |
| (không) | trung tính: dừng, tắt, phiên bản |

**Thao tác nguy hiểm phải hỏi trước** bằng `useConfirm()`: xoá / gỡ, dừng / tắt (dịch vụ, server, tiến trình), cho
quyền rộng (vd. cho một tool ghi tự chạy), từ chối / huỷ việc đang chờ. Thao tác an toàn hoặc hoàn tác được (bật, lưu,
tải lại, chạy) thì không hỏi. Nút mở thao tác nguy hiểm dùng `danger` (đỏ).

```jsx
import { useConfirm } from "@vh/ui";
import { IconButton } from "@vh/md";

const [confirm, dialog] = useConfirm();          // trong component trang; render {dialog} một lần
const remove = async (item) => {
  if (!(await confirm({
    title: `Xoá “${item.name}”?`,               // câu hỏi, nêu đúng đối tượng
    text: "Dữ liệu của nó bị xoá. Không hoàn tác được.",   // cái gì mất / dừng, hoàn tác được không
    confirm: "Xoá", icon: "delete",               // nút ghi đúng động từ; danger: false cho câu hỏi thường
  }))) return;
  await api.delete(`/items/${item.id}`);
};
return <>{dialog}<IconButton icon="delete" danger label="Xoá" onClick={() => remove(item)} /></>;
```

Thẻ điều khiển của Hub đã tự hỏi trước khi **Dừng** / **Khởi động lại** addon.

Build: `npm install` (một lần) rồi `npm run build` → `ui/ui.js`. Đừng tự cấu hình bundler: `.sdk/build.mjs` đã
đổi import `react` / `react/jsx-runtime` / `react-dom` / `@vh/md` / `@vh/ui` thành
`/static/dist/sdk/{react,jsx-runtime,react-dom,md,ui}.js` mà Hub phục vụ.

## 7. GUIDE.md và bảo mật

`GUIDE.md` bắt đầu bằng đúng `## <menu.label>`, viết cho người dùng (làm gì, bấm gì); hiện ở trang addon và trang
Hướng dẫn. `[icon:tên]` hiện thành icon. Nếu có `mcp`, phải có bảng liệt kê **mọi** tool:

```
### Tool cho AI

| Tool | Làm gì |
|---|---|
| `jira_read` | Nội dung một ticket |
```

Lúc cài, Hub quét addon. **Bị từ chối** (không cài được):

- file thực thi / native: `.exe .dll .pyd .so .dylib .node .bat .cmd .ps1 .sh .vbs .com .scr .msi .jar` (trừ `node/node.exe`)
- Python: `shell=True`, `os.system`, `os.popen`, `eval(`, `exec(`, gọi `powershell` / `cmd /c`, `winreg` / autostart,
  `pickle.load(s)`, `marshal.load(s)`, `yaml.load` không SafeLoader
- trang (`ui/`, `.css`, `.html`): địa chỉ CDN (`http(s)://` + `cdn.`, `unpkg`, `jsdelivr`, `cdnjs`, `fonts.googleapis`,
  `fonts.gstatic`; địa chỉ khác trong chữ thì được), `eval(` / `new Function(`, `innerHTML =`
- Node: `child_process` với `shell: true`

**Được nhưng admin thấy lưu ý** khi cài: Python gọi mạng, `subprocess`, socket / named pipe, `base64.b64decode`;
Node dùng `child_process`, `eval`, nhắc tới PowerShell / cmd. Chỉ dùng khi thật cần; `subprocess` luôn là danh sách
tham số, không shell. Khác: không ghi ngoài thư mục dữ liệu của addon, không đọc / gửi dữ liệu của người dùng đi đâu
khi người dùng không yêu cầu, không tự cài gì vào máy, không đụng registry / autostart.

Cũng bị từ chối: tên file Windows không giữ được (`CON`, `NUL`, `COM1`… kể cả có đuôi; ký tự `<>"|?*`; kết thúc bằng
`.` hoặc dấu cách), hai file chỉ khác chữ hoa / thường, `id` / `mcp.command` trùng (§3). Dòng có `# noqa: security`
được bỏ qua: chỉ dùng khi chắc chắn đúng (vd. chữ "eval(" trong một chuỗi). `npm run check` chạy cùng các quy tắc này.

Addon do bạn đóng gói là **chưa ký** (Hub hiện "chưa ký: do admin cung cấp"): bình thường. Nhưng addon đang cài đã
được admin ký thì zip chưa ký **không thay được** nó (admin gỡ trước, hoặc ký lại).

Lúc chạy Hub tự bảo vệ mình (addon không cần làm gì, nhưng nên biết khi thử):

- Mỗi addon tối đa 4 request cùng lúc (+ 2 stream / SSE); hơn thì chờ 5 giây rồi trả 503 "addon đang bận". Request
  chậm nên trả nhanh hoặc chia nhỏ; stream im lặng 5 phút bị đóng.
- Addon managed dừng bất thường 3 lần trong 5 phút: Hub không chạy lại trong 1 phút (503 "chờ"); xem **Nhật ký**.
- Log của addon managed quá 50 MB: Hub dừng addon (lần dùng sau chạy lại). Đừng in mỗi request ra log.

## 8. Đóng gói, cài, thử

```
npm install          # một lần (cần Node.js 22+)
npm run build        # src/main.mjs → main.mjs (nếu có), web/ → ui/ (nếu có), rồi check
npm run check        # chỉ kiểm tra như lúc cài: addon.json, file, GUIDE.md, quy tắc bảo mật (§7); không build
npm test             # test trong test/: Python = unittest với SDK thật (.sdk/python), Node = node --test
npm run zip          # build + check + dist/<id>-<version>.zip
```

Rồi **Cài đặt → Addon → Cài addon (.zip)**. Cài lại bản mới đè bản cũ, giữ dữ liệu. Không có Node: nén **cả thư
mục addon** thành zip (Explorer: chuột phải → Send to → Compressed folder; macOS: Compress) cũng được, Hub bỏ
các file phát triển ở §2 (nhưng `ui/`, `main.mjs` phải đã build sẵn).

Test Python không cần Hub (mẫu `simple` có sẵn `test/test_main.py`): đặt `VIEWER_HUB_ADDON_DATA` về thư mục tạm
**trước** khi `import main`, rồi gọi thẳng

```python
status, body = addon.handle_api("GET", "/notes", {}, None, {})          # (method, path, query, body, headers)
reply = addon.handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "notes_read", "arguments": {"id": "1"}}})
text = reply["result"]["content"][0]["text"]; failed = reply["result"].get("isError", False)
```

`npm test` tìm `python3` / `python` / `py` (hoặc `VIEWER_HUB_PYTHON=<đường dẫn>`), thêm `.sdk/python`, `lib/` và thư
mục addon vào `PYTHONPATH`.

Thử trên Hub:

1. Mở `/x/<id>` (mục mới trên menu). Lỗi khi chạy: nút **Nhật ký** trên trang addon (hoặc `<data>/logs/addon-<id>.log`).
2. Sửa trang mà không cài lại: `npm run watch -- --out <data>/addons/<id>/ui`, F5 trình duyệt.
3. Sửa code Python / Node: `npm run zip` và cài lại (Hub dừng bản cũ trước khi thay).
4. MCP: `{{hub}} mcp <mcp.command>` (stdio) hoặc HTTP `http://127.0.0.1:<port>/x/<id>/mcp`.

## 9. Checklist trước khi gửi

- [ ] `addon.json`: `id` mới, `version` tăng, `menu` tiếng Việt, mọi tool có trong `mcp.tools`
- [ ] `GUIDE.md` bắt đầu bằng `## <menu.label>`, có bảng `### Tool cho AI` nếu có MCP
- [ ] Chỉ ghi vào `VIEWER_HUB_ADDON_DATA`; không cổng TCP nào ngoài `127.0.0.1` (managed) / không cổng nào (daemon)
- [ ] Tool MCP chỉ đọc; lỗi người dùng thấy là tiếng Việt
- [ ] Xoá / dừng / tắt / cấp quyền rộng đều hỏi bằng `useConfirm()`; màu đúng nghĩa (§6.1)
- [ ] `npm test` qua; `npm run zip` không báo lỗi (build lại sau lần sửa `web/` / `src/` cuối cùng)
- [ ] Đã cài thử trên Viewer Hub, mở trang, gọi thử tool
