# Viết addon cho Viewer Hub (SDK {{sdk}})

Tài liệu cho AI agent (và người) viết **addon**: tính năng thêm cho Viewer Hub, đóng thành một file zip, người dùng
cài ở **Cài đặt → Addon** mà không cần bản Viewer Hub mới. Đọc hết file này trước khi viết code. Mọi chữ hiện cho
người dùng (menu, nút, thông báo, GUIDE.md) viết **tiếng Việt**; tên trong code, comment viết tiếng Anh.

Bản SDK này đi kèm Viewer Hub {{version}}. `.sdk/python/viewer_hub/` là mã thật của SDK Python (`addons/sdk.py` và
những gì nó import): đọc để biết chi tiết, `npm test` dùng nó để chạy test không cần Hub (§8). Đừng chép vào addon:
lúc chạy, Hub cung cấp nó.

> **Hub vẽ sẵn, addon không tự làm** (lúc cài và `npm run check` đều **từ chối** nếu vi phạm, §6):
>
> - Phần đầu mọi trang addon là của Hub: mô tả, trạng thái (`Đang chạy` / `Đã dừng`), nút **Cài đặt**, **Nhật ký**,
>   chạy / dừng / khởi động lại. Trang của bạn **không** vẽ lại các nút / nhãn đó, không có form cài đặt riêng, không
>   gọi `/api/addons/...` của Hub, không có API `/settings` / `/config` riêng để trang đọc / ghi cấu hình.
> - Cấu hình = mảng `settings` trong `addon.json` (§3). Bắt buộc phải nhập → `"required": true`: Hub tự hiện banner
>   "Cần điền …" kèm nút mở hộp Cài đặt. **Không** tự làm banner "Chưa cấu hình / Hãy vào Cài đặt" (`md-banner`).
> - Trang cần chỗ cho người dùng mở hộp Cài đặt (vd. trạng thái trống "Chưa có kết nối") → nút gọi
>   `useAddon().openSettings("<key>")`. Đọc giá trị: `addon?.values` (trang), `addon.settings()` (Python), file
>   `VIEWER_HUB_ADDON_SETTINGS` (Node).

---

## 1. Chọn loại addon

| Loại | Khi nào | Ví dụ |
|---|---|---|
| `managed` + `python` (**mặc định, chọn cái này nếu không chắc**) | Hàm, API cho trang, tool MCP cho AI; không cần chạy khi không ai dùng | đọc Jira, tra cứu file, ghi chú |
| `managed` + `node` | Như trên nhưng code sẵn có là Node (không có SDK, tự làm HTTP: §4.2) | thư viện chỉ có cho JS |
| `managed` + `dotnet` | Như trên nhưng cần thư viện .NET (không có SDK, tự làm HTTP: §4.4); máy phải cài .NET 8+ | driver Oracle cũ mà Node không hỗ trợ |
| `daemon` + `node` hoặc `python` | Một chương trình **chạy lâu, có vòng đời riêng** (vẫn chạy khi đóng Viewer Hub), Hub chỉ bật / tắt / hỏi trạng thái | MCP Bridge, đồng bộ nền |
| `external` | Chương trình **đã có sẵn, viết bằng ngôn ngữ khác** (.NET, Java, Go…), người dùng tự cài và tự chạy; khó chuyển sang Python / Node | công cụ nội bộ .NET có web API |

- `managed`: Hub chạy tiến trình khi có request đầu tiên, dừng khi Hub thoát. Hub giữ tiến trình.
  (Chỉ `managed` + `dotnet` được kèm `.dll`, và chỉ assembly .NET: §4.4. Còn lại không bao giờ đóng `.exe` / `.dll`.)
- `daemon`: chương trình tự sống; Hub gọi các lệnh `init` / `start` / `status` của nó và nói chuyện qua **kênh
  quản trị** (named pipe / Unix socket).
- `external`: Hub **không chạy gì**: addon chỉ có `addon.json`, `GUIDE.md`, trang `ui/`; Hub chuyển request của trang
  và của AI tới chương trình của người dùng trên `127.0.0.1:<cổng>` (§5.4). Không bao giờ đóng `.exe` / `.dll` vào addon.

Bắt đầu: `npm run new -- simple <id>` (managed python + trang + 2 tool MCP), `npm run new -- daemon <id>`
(daemon node + trang + SSE) hoặc `npm run new -- external <id>` (nối tới chương trình có sẵn) ngay trong thư mục này; rồi sửa `name`, `menu` và code. Loại nào cũng **cùng một cấu
trúc** (§2) và cùng một cách đóng gói (§8).

## 2. Cấu trúc một addon (một kiểu duy nhất)

Hai thứ tách hẳn nhau: **project** (nguồn bạn viết) và **gói** (thứ Hub cài). Build lắp gói từ project vào
`build/<id>/`; không bao giờ ghi vào thư mục nguồn.

**Project** (thư mục SDK này; mỗi addon một thư mục, giải nén SDK một lần cho mỗi addon):

```
<project>/
  addon/                  addon.json (§3) và GUIDE.md (§7): khai báo + hướng dẫn cho người dùng
  src/                    chương trình: python = main.py (+ lib/), node = main.mjs (+ file import), dotnet = dự án .NET
  web/                    trang: web/index.jsx → ui/
  assets/                 (tuỳ chọn) dữ liệu chỉ đọc đi kèm addon (vd. packs/)
  legal/                  (tuỳ chọn) SBOM, giấy phép bên thứ ba
  test/                   test của bạn
  build/<id>/             sinh ra: gói addon (thứ Hub cài)
  dist/                   sinh ra: <id>-<version>.zip
  package.json AGENTS.md README.md .sdk/ .gitignore
```

**Gói** (`build/<id>/`, và trong zip dưới một thư mục `<id>/`): gốc chỉ có **3 file và 4 thư mục** có tên cố định,
thứ gì khác ở gốc thì bị từ chối:

```
<id>/
  addon.json              khai báo (§3)
  GUIDE.md                hướng dẫn cho người dùng (§7)
  signature.json          chữ ký (do công cụ đóng gói của admin tạo, không phải của bạn)
  ui/                     trang đã build
  app/                    chương trình và mọi thứ nó cần; "entry" là tên một file ở đây (external: không có)
  assets/                 dữ liệu chỉ đọc
  legal/                  giấy phép
```

- Mọi code chạy (`.py`, `.mjs`, `.dll` .NET) nằm trong `app/`. Hub chạy chương trình với thư mục làm việc là `app/`.
  `.exe` / `.dll` / native ở bất cứ đâu đều bị từ chối, trừ assembly .NET trong `app/` của addon `dotnet` (§4.4). Addon
  Node không mang `node.exe`: Hub chạy bằng `node` của máy (PATH).
- **Python**: `src/main.py` + `src/lib/` (package thuần Python chép vào, tự thêm vào `sys.path`), chép nguyên vào `app/`.
  Chỉ thư viện chuẩn (§4.1).
- **Node có package npm** (vd. `oracledb`): viết ở `src/main.mjs`, `npm install <package>`; `npm run build`
  bundle tất cả vào `app/main.mjs` (esbuild), đã **minify**. Nguồn ở `src/` không đi vào gói, nên code nguồn không
  theo bản phát hành. Package có file native (`.node`) không cài được (§7): chọn bản JS thuần (vd. oracledb "thin mode").
- **.NET**: dự án ở `src/`; `npm run build` chạy `dotnet publish src -c Release -o build/<id>/app` (§4.4).
- Đọc dữ liệu đi kèm: Python `addon.assets` (thư mục `assets/` của gói); Node / .NET biến `VIEWER_HUB_ADDON_ASSETS`.
- Daemon là chương trình lớn ở repo riêng? Xem §5.2.

Addon được cài vào `<data>/addons/<id>/` (**chỉ đọc**: bị thay khi cập nhật); dữ liệu của nó ở
`<data>/user/addons/<id>/` (giữ qua cập nhật, gỡ, sao lưu).

## 3. addon.json

```json
{
  "schema": "viewer-hub/addon", "schemaVersion": 3, "sdk": "{{sdk}}",
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
| `id` | `^[a-z][a-z0-9-]{1,40}$`, duy nhất; không trùng mục có sẵn (`codemap`, `fsearch`, `csv`, `docs`, `monitor`, `settings`, `help`, `premium`, `api`, `sdk`, `static`, `x`, `call`, `staged`, `contracts`: bị từ chối). Trùng id addon đã cài = cập nhật addon đó (kể cả addon mặc định như `svn`), nên chọn id riêng. Trang ở `/x/<id>` |
| `version` | `1.2.3` (thêm `-beta.1` được). Tăng mỗi lần gửi bản mới |
| `schemaVersion` | Luôn `3` (cấu trúc gói ở §2). Bản Hub cũ hơn từ chối addon này thay vì cài rồi lỗi |
| `runtime` / `entry` | `python` + `main.py`, `node` + `main.mjs`, hoặc `dotnet` + `<Tên>.dll`; `entry` là tên file trong `app/` |
| `lifecycle` | `managed`, `daemon` hoặc `external` (§1) |
| `menu` | `label` (≤ 40 ký tự, tên trên menu), `icon` (tên [Material Symbols](https://fonts.google.com/icons), vd. `bug_report`), `summary` (một câu) |
| `ui` | Tuỳ chọn. `script` (`ui/<tên>.js`), `style` (`ui/<tên>.css`). Không có `ui`: Hub tự làm trang (trạng thái, cài đặt, MCP, GUIDE.md) |
| `mcp` | `managed` hoặc `external` (daemon không có). `command`: tên lệnh (`viewer-hub mcp <command>`), không trùng lệnh có sẵn (`codemap`, `search`, `csv`, `monitor`) hay của addon khác; `scope`: AI đọc được gì; `tools`: tên mọi tool (`^[a-z0-9_]+$`, nên có tiền tố chung) |
| `settings` | Form cài đặt trên trang addon. Mỗi mục: `key`, `label`, `type` (`text`, `folder`, `list`, `switch`, `select` + `options`, `records` + `fields`: mỗi dòng nhiều ô, mỗi ô `key`, `label`, `type` `text`/`select`, `options`, `required`, `placeholder`, `help`, `showWhen` `{ô khác: [giá trị]}`; giá trị là danh sách object `{key: chuỗi}`, tối đa 100 dòng), `default`, `help`, `required` (true: trang báo "Cần điền …" tới khi có giá trị). Daemon: thêm `arg` (`--ten`) và `on` (`init` / `start`): Hub truyền `<arg> <giá trị>` cho lệnh đó |
| `commands` | Chỉ `daemon`, bắt buộc: `{"init": [...], "start": [...], "status": [..., "--json"]}`: tham số đơn giản, không có shell |
| `minNode` | (node) phiên bản Node tối thiểu, vd. `"22"` |
| `provides` | (daemon) `["mcp-servers"]` nếu daemon gom MCP server (như MCP Bridge, §5.3). Không thì bỏ |
| `premium` | `null`. (Tên tính năng nếu admin bán kèm mã mở khoá; chỉ admin của Viewer Hub đặt) |
| `exports` / `uses` / `requires` | Đọc dữ liệu giữa các addon (§4.3). Không dùng thì bỏ |

## 4. Addon managed

Biến môi trường Hub truyền cho mọi addon:

| Biến | Là gì |
|---|---|
| `VIEWER_HUB_ADDON_ID` | id |
| `VIEWER_HUB_ADDON_FOLDER` | thư mục gói của addon (chứa `addon.json`, `app/`, `ui/`…), chỉ đọc |
| `VIEWER_HUB_ADDON_ASSETS` | thư mục `assets/` của gói (dữ liệu chỉ đọc đi kèm) |
| `VIEWER_HUB_ADDON_DATA` | thư mục dữ liệu riêng, **chỗ duy nhất addon được ghi** |
| `VIEWER_HUB_ADDON_SETTINGS` | file JSON các giá trị form cài đặt (Hub ghi, addon đọc) |
| `VIEWER_HUB_ADDON_TOKEN` | managed: token của lần chạy này |

### 4.1 Python: dùng SDK

Chạy bằng Python của Viewer Hub (`python -I`). **Chỉ thư viện chuẩn** + package thuần Python chép vào `src/lib/`
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

### 4.4 .NET (managed): `runtime: "dotnet"`

```json
{ "lifecycle": "managed", "runtime": "dotnet", "entry": "DbQuery.dll" }
```

Hub chạy `dotnet <entry>.dll serve --port N` bằng .NET **có sẵn trên máy** (lệnh `dotnet` trong PATH, hoặc Program Files
trên Windows); chưa có thì trang addon báo "Cần .NET 8+". Hợp đồng HTTP **giống hệt §4.2** (token `X-Viewer-Hub-Token`,
`/health`, `/api/*`, `/mcp`, `/shutdown`, pipe cha `VIEWER_HUB_PARENT_PIPE=1`), cùng các biến môi trường
(`VIEWER_HUB_ADDON_SETTINGS`: file `settings.json` của form Cài đặt, `VIEWER_HUB_ADDON_DATA`…).

Cấu trúc: dự án .NET ở `src/` (và test ở `test/`, hoặc `tests/` nếu là dự án xunit riêng). `npm run build` chạy
`dotnet publish src -c Release -o build/<id>/app`, nên `app/` chứa `<Tên>.dll`, `<Tên>.runtimeconfig.json` và các
assembly phụ thuộc, tách khỏi `addon.json`, `GUIDE.md`, `ui/`. Cần .NET SDK 8+ trên máy build.

Quy tắc khi quét (lúc cài và `npm run check`): chỉ nhận `.dll` là **assembly .NET** nằm trong `app/` (có CLR header); `.exe`, DLL native,
`.so`, `.node`… vẫn bị từ chối. Trong `.csproj` đặt `<UseAppHost>false</UseAppHost>` (không sinh `.exe`) và
`<IsTransformWebConfigDisabled>true</IsTransformWebConfigDisabled>`; xoá `web.config` và DLL tài nguyên native (vd.
`System.Diagnostics.EventLog.Messages.dll`) khỏi bản publish. Hub không đọc được code đã biên dịch nên hiện ghi chú cho
admin lúc cài: nên ký addon (`npm run zip` rồi ký như addon khác) và chỉ phát hành addon .NET của người tin cậy.
Mẫu đầy đủ (ASP.NET Core, `Oracle.ManagedDataAccess.Core`, xunit): addon `db-query` (dự án `viewer-hub-addons/db-query`).

### 4.3 Dùng dữ liệu addon khác (`uses`) và cho addon khác dùng (`exports`)

Addon không đọc thư mục, không gọi cổng của nhau. Mọi lời gọi đi qua Hub: Hub kiểm quyền và contract, tự chạy addon
kia, ghi vào trang Giám sát. Chỉ đọc, như MCP.

**Có gì để dùng:** `.sdk/addons/<id>.md` (mô tả cho bạn: tham số, kết quả, ví dụ, đoạn `uses` chép được) và
`.sdk/addons/<id>.json` (contract máy đọc) của mỗi addon trên Hub đã tải SDK. Cũ / thiếu: `npm run exports` khi
Viewer Hub đang chạy (`npm run exports -- http://127.0.0.1:<cổng>`). **Chỉ dùng export có trong đó**, không đoán.

**Dùng (A):** khai trong `addon/addon.json`, chỉ những export cần:

```json
"uses": {"svn": {"version": "^1.2.0", "exports": ["svn_log"], "optional": true}}
```

`version`: khoảng semver (`^1.2.0`, `~1.2.0`, `>=1.2.0 <2`). `optional: true` khi addon vẫn chạy được không có addon
kia (khuyên dùng). `npm run build` tự thêm `built` (contract lúc build) từ `.sdk/addons/`: đừng viết tay. Gọi:

```python
from viewer_hub.addons.sdk import CallError

try:
    log = addon.call("svn", "svn_log", {"repo": "core", "limit": 20})     # dict đúng "returns" của svn_log
except CallError as exc:   # exc.code: dependency_missing, dependency_incompatible, export_unknown, bad_params,
    ...                    # bad_reply, dependency_unavailable, call_depth, forbidden; exc.message: tiếng Việt
```

```js
import { pathToFileURL } from "node:url";
const hub = await import(pathToFileURL(process.env.VIEWER_HUB_NODE_SDK ?? "./.sdk/node/hub_client.mjs").href);
const log = await hub.call("svn", "svn_log", { repo: "core", limit: 20 });   // lỗi: hub.CallError {code, reason}
```

- Luôn bắt `CallError`: addon kia có thể chưa cài, bị gỡ, khoá premium hay đang lỗi. Tắt phần đó một cách nhẹ nhàng,
  báo bằng tiếng Việt, không để cả trang hay tool lỗi.
- Kết quả có thể có **thêm trường mới**: bỏ qua trường lạ, đừng kiểm "đúng y" schema.
- Không gọi `addonApi("<id khác>")` từ trang: trang gọi API của chính addon, backend gọi addon kia.
- Test: không có Hub thì `addon.call` trả `example` trong `.sdk/addons/<id>.json` (tham số vẫn được kiểm), hoặc giá
  trị đặt bằng `addon.fake("svn", "svn_log", {...})` (Node: `hub.fake(...)`); đặt một `CallError` để thử nhánh lỗi.

**Cho dùng (B):** khai `exports` trong `addon.json` và viết hàm cho từng cái:

```json
"exports": [{"name": "svn_log", "description": "Lịch sử commit của một branch",
  "params":  {"type": "object", "required": ["repo"], "properties": {
               "repo": {"type": "string"}, "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100}}},
  "returns": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
               "type": "object", "required": ["revision", "author"],
               "properties": {"revision": {"type": "integer"}, "author": {"type": "string"}}}}}},
  "example": {"items": [{"revision": 120, "author": "an"}]}, "since": "1.2.0"}]
```

```python
@addon.export("svn_log")
def svn_log_export(params):        # params đã được Hub kiểm theo "params", default đã điền
    return {"items": [...]}         # dict đúng "returns"; lỗi: raise ApiError("no_repo", "Không có repo …", 404)
```

Node: trong server, trước `/api`: `if (await hub.serveExport(req, res, { svn_log: async (params) => ({ items: [] }) })) return;`
(sau khi đã kiểm token như mọi request).

- Schema chỉ dùng: `type` (object, array, string, integer, number, boolean, null), `properties`, `required`, `items`,
  `enum`, `default`, `description`, `minLength` / `maxLength`, `minimum` / `maximum`. `params` và `returns` là object.
  `example` phải đúng `returns`. Thiếu hàm cho một export: addon không chạy (log ghi rõ).
- **Đổi export là đổi hợp đồng với addon khác.** Phá vỡ = bỏ export, bỏ / đổi kiểu một tham số hay một trường bắt buộc
  của kết quả, thêm tham số bắt buộc, thu hẹp giá trị nhận được, thêm giá trị `enum` vào kết quả. Phá vỡ thì phải tăng
  **major** (`1.4.0` → `2.0.0`), nếu không Hub từ chối bản mới; tăng major thì Hub hỏi admin trước khi làm hỏng addon
  đang dùng. Không phá vỡ (tăng minor): thêm export, thêm tham số không bắt buộc, thêm trường vào kết quả.
- Export là **đọc**: không ghi, không xoá. Chỉ trả những gì addon đã cho AI / trang đọc (theo setting của addon).

Lúc cài, Hub kiểm cả hai chiều: addon được dùng có chưa, đúng version, còn export, contract còn khớp `built`; bản mới
của B có làm hỏng A không; vòng `uses` (A → B → A) bị từ chối. Trang addon hiện "dùng dữ liệu của / được dùng bởi".

## 5. Addon daemon

### 5.1 Hợp đồng

Hub chạy `<node|python> <entry> <commands.X> <tham số từ settings>` (thư mục làm việc = `app/`, cùng biến
môi trường §4, `node` là của máy; Windows không mở cửa sổ console):

| Lệnh | Phải làm |
|---|---|
| `init` | Chuẩn bị (thư mục, config, nhận `arg` của settings `on: "init"`). Thoát 0 khi xong. Chạy **trước mỗi lần** start, nên phải chạy lại được nhiều lần và **không được đè** config user đã chỉnh: không có `arg` thì giữ nguyên. Hub chỉ truyền một `arg` của init khi user vừa đổi giá trị đó trên Hub (so với lần truyền trước), nên chỉnh bằng CLI / trang riêng của daemon không bị Hub ghi đè lúc khởi động lại. `arg` của `on: "start"` thì luôn được truyền (chỉ cho lần chạy đó) |
| `start` | Chạy **foreground** tới khi được bảo dừng. Hub tự đưa vào nền (Windows: process group riêng, không cửa sổ console; macOS/Linux: session riêng) và ghi **mọi dòng stdout / stderr** vào log của Hub (`addon-<id>.log`, xoay vòng ~2 MB, xem ở nút **Nhật ký**): in log ra stdout, không cần tự làm trang log. Đã có bản đang chạy thì thoát 0 |
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

Mẫu đầy đủ, không dependency: `npm run new -- daemon <id>` → `src/main.mjs`. Chạy thử không cần Hub:
`node src/main.mjs init && node src/main.mjs start` rồi (cửa sổ khác) `node src/main.mjs status --json`.

### 5.2 Daemon là chương trình lớn ở repo riêng

Addon zip phải **tự chứa đủ**: chương trình nằm trong `app/` của gói. Cách đơn giản nhất vẫn là cấu trúc §2: code
ở `src/` (TypeScript / nhiều file được: `src/main.mjs` import chúng), `npm run build` gom thành `app/main.mjs`.

Repo đã có sẵn (có build và zip phát hành riêng, vd. MCP Bridge) thì repo đó tự lắp gói đúng §2 (chương trình đã bundle
vào `app/`, giấy phép vào `legal/`, giao diện vào `ui/`) rồi nén thành `<id>-<version>.zip`; `{{hub}} addon pack <thư
mục gói>` kiểm tra và (với admin) ký gói đó.

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
  Lúc cài (và `npm run check`) Hub **từ chối** trang có: lời gọi `/api/addons/...`; lời gọi API `"/settings"` /
  `"/config"` của addon; chữ `Cài đặt`, `Mở cài đặt`, `Lưu cài đặt`, `Nhật ký`, `Xem nhật ký`, `Xem log`,
  `Khởi động lại` làm nút / nhãn; `md-banner` nói về cấu hình / cài đặt / thiết lập / chưa nhập / chưa chọn.
  Banner cho lỗi khác (vd. "Chưa có lệnh svn") vẫn được.

  ```jsx
  // ĐÚNG: thiếu cấu hình → settings[].required trong addon.json (Hub hiện banner); trạng thái trống mở hộp của Hub
  const { openSettings } = useAddon();
  if (!addon?.values?.workspacePath) return <Empty icon="folder_open" title="Chưa chọn thư mục">
    <Button icon="folder_open" onClick={() => openSettings("workspacePath")}>Chọn thư mục</Button></Empty>;
  // SAI: <div className="md-banner">Chưa cấu hình… </div>, <TextField> + api.put("/settings"), <Button>Cài đặt</Button>
  ```
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

- file thực thi / native: `.exe .dll .pyd .so .dylib .node .bat .cmd .ps1 .sh .vbs .com .scr .msi .jar` (trừ assembly .NET của addon `dotnet`)
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
npm run build        # lắp gói vào build/<id>/: addon/ → addon.json + GUIDE.md, src/ → app/, web/ → ui/, assets/, legal/
npm run check        # build rồi kiểm tra như lúc cài: addon.json, cấu trúc gói, GUIDE.md, quy tắc bảo mật (§7)
npm test             # test trong test/: Python = unittest với SDK thật (.sdk/python), Node = node --test
npm run zip          # build + check + dist/<id>-<version>.zip
npm run exports      # contract của các addon trên Viewer Hub đang chạy → .sdk/addons/ (§4.3)
```

Rồi **Cài đặt → Addon → Cài addon (.zip)**. Cài lại bản mới đè bản cũ, giữ dữ liệu. Hub chỉ cài zip đúng cấu trúc §2:
đừng nén tay thư mục project, hãy dùng `npm run zip`.

Test Python không cần Hub (mẫu `simple` có sẵn `test/test_main.py`): đặt `VIEWER_HUB_ADDON_DATA` về thư mục tạm
**trước** khi `import main` (`src/` đã nằm trên `PYTHONPATH`), rồi gọi thẳng

```python
status, body = addon.handle_api("GET", "/notes", {}, None, {})          # (method, path, query, body, headers)
reply = addon.handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "notes_read", "arguments": {"id": "1"}}})
text = reply["result"]["content"][0]["text"]; failed = reply["result"].get("isError", False)
```

`npm test` tìm `python3` / `python` / `py` (hoặc `VIEWER_HUB_PYTHON=<đường dẫn>`), thêm `.sdk/python`, `src/` và `src/lib/`
vào `PYTHONPATH`.

Thử trên Hub:

1. Mở `/x/<id>` (mục mới trên menu). Lỗi khi chạy: nút **Nhật ký** trên trang addon (hoặc `<data>/logs/addon-<id>.log`).
2. Sửa trang mà không cài lại: `npm run watch -- --out <data>/addons/<id>/ui` (đã cài một lần), F5 trình duyệt.
3. Sửa code Python / Node: `npm run zip` và cài lại (Hub dừng bản cũ trước khi thay).
4. MCP: `{{hub}} mcp <mcp.command>` (stdio) hoặc HTTP `http://127.0.0.1:<port>/x/<id>/mcp`.

## 9. Checklist trước khi gửi

- [ ] `addon.json`: `id` mới, `version` tăng, `menu` tiếng Việt, mọi tool có trong `mcp.tools`
- [ ] `GUIDE.md` bắt đầu bằng `## <menu.label>`, có bảng `### Tool cho AI` nếu có MCP
- [ ] Chỉ ghi vào `VIEWER_HUB_ADDON_DATA`; không cổng TCP nào ngoài `127.0.0.1` (managed) / không cổng nào (daemon)
- [ ] Tool MCP chỉ đọc; lỗi người dùng thấy là tiếng Việt
- [ ] `uses`: chỉ export có trong `.sdk/addons/`, luôn bắt `CallError`; `exports`: đổi phá vỡ thì tăng major (§4.3)
- [ ] Xoá / dừng / tắt / cấp quyền rộng đều hỏi bằng `useConfirm()`; màu đúng nghĩa (§6.1)
- [ ] Trang không vẽ lại phần đầu của Hub: không form / banner cài đặt, nút Cài đặt / Nhật ký / chạy / dừng; cấu hình chỉ
      qua `settings` (+ `required`) và `useAddon().openSettings()` (đầu file)
- [ ] `npm test` qua; `npm run zip` không báo lỗi (build lại sau lần sửa `web/` / `src/` cuối cùng)
- [ ] Đã cài thử trên Viewer Hub, mở trang, gọi thử tool
