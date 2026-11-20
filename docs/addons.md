# Viewer Hub: Addon

> Tài liệu tham chiếu kiến trúc hiện tại · code: `viewer_hub/addons/` (+ `kit/`: SDK cho người dùng), `web/src/sdk/`,
> `packaging/addon.py`, `addons/` (addon mặc định)
> Liên quan: [design.md](design.md), [GUIDELINE.md](GUIDELINE.md) §5 (bảo mật), §10 (thêm tính năng).

Addon = tính năng viết ở project riêng, đóng thành zip, cài vào Viewer Hub đã cài (upload trên trang Cài đặt hoặc
addon mặc định), **không build lại Hub, không khởi động lại**. Ba vòng đời:

1. **`managed`** (như `svn`): function, MCP, có hoặc không có UI; Hub chạy và dừng tiến trình.
2. **`daemon`** (như MCP Bridge): chương trình chạy lâu, vòng đời riêng; Hub chỉ start / stop / status.
3. **`external`**: chương trình có sẵn (.NET, Java…) người dùng tự chạy; Hub chỉ nối tới `127.0.0.1:<cổng>`.

Module builtin (`codemap`, `fsearch`, `csv`, `docs`, `monitor`) nằm trong `PACKAGES` và **không bao giờ premium**
(`modules.all_modules()` từ chối); tính năng premium luôn là addon (`"premium": "<key>"`, ví dụ `db-query`).
Addon giả định do tác giả / admin cung cấp (§7), không phải bên thứ ba không tin cậy.

---

## 2. Nguyên tắc

1. **Addon chạy ngoài tiến trình Hub.** Không bao giờ `import` code addon vào tiến trình đang giữ `hub.db`. Addon lỗi không
   kéo Hub chết theo; chỉ một file của Hub được spawn tiến trình (GUIDELINE §5).
2. **Addon trở thành một `Module`.** Hub đọc manifest và tạo `Module` như module builtin, nên menu, trang chủ, `/help`,
   bảng MCP và MCP Bridge tự có, không sửa chỗ nào khác.
3. **Hub là host:** proxy API / MCP, phục vụ file UI, vẽ form setting, giữ thư mục dữ liệu riêng cho addon.
4. **Một hợp đồng, ba vòng đời** (`managed` / `daemon` / `external`), thay vì nhiều cơ chế khác nhau.
5. **Mọi quy tắc của Hub vẫn áp dụng cho addon:** không tải gì lúc chạy, không native addon, chạy tiến trình bằng argv,
   MCP chỉ đọc, giao diện Material 3.

---

## 3. Gói addon

Một cấu trúc cho mọi loại addon và mọi runtime. Gốc gói chỉ có **3 file và 4 thư mục** có tên cố định; thứ gì khác ở gốc
thì Hub từ chối (`core/scan.py` `layout_errors`, `PACKAGE_FILES` / `PACKAGE_DIRS`):

```
<id>-<version>.zip            một thư mục gốc duy nhất
  <id>/
    addon.json                manifest (§3.1)
    GUIDE.md                  mục hướng dẫn: "## <label>" … "### Tool cho AI"
    signature.json            chữ ký Ed25519 (addon do `just addon` build)
    ui/ui.js, ui/ui.css       trang React đã build (tuỳ chọn, §5)
    app/                      chương trình và mọi thứ nó cần; `entry` là tên một file ở đây
      main.py + lib/          Python: code + dependency thuần Python đã vendor
      main.mjs                Node: một file bundle; node/node.exe nếu mang Node theo (Windows)
      <Tên>.dll + …           .NET: kết quả `dotnet publish`
    assets/                   (tuỳ chọn) dữ liệu chỉ đọc đi kèm (vd. packs/); biến VIEWER_HUB_ADDON_ASSETS, `addon.assets`
    legal/                    (tuỳ chọn) SBOM, giấy phép bên thứ ba
```

Hub chạy chương trình với thư mục làm việc là `app/` (Python: `app/` và `app/lib/` được thêm vào `sys.path`). Code chạy
(`.py`, `.mjs`, `.dll` .NET, `node/node.exe`) chỉ nằm trong `app/`; `.exe` / `.dll` / native ở bất kỳ chỗ nào khác bị từ chối.

Sau khi cài: `<data>/addons/<id>/` (gói, chỉ đọc) và `<data>/user/addons/<id>/` (dữ liệu + setting của addon). Project nguồn
của tác giả khác gói: xem §8.1.

### 3.1 `addon.json`

```json
{
  "schema": "viewer-hub/addon", "schemaVersion": 3,
  "id": "jira-reader", "name": "Jira Reader", "version": "0.1.0",
  "sdk": "1",
  "runtime": "python",
  "entry": "main.py",
  "lifecycle": "managed",
  "menu": {"label": "Jira", "icon": "bug_report", "summary": "Đọc ticket Jira cho AI và trên web"},
  "ui": {"script": "ui/ui.js", "style": "ui/ui.css"},
  "mcp": {"command": "jira", "scope": "chỉ project đã thêm", "tools": ["jira_search", "jira_read"]},
  "settings": [
    {"key": "baseUrl", "label": "Địa chỉ Jira", "type": "text"},
    {"key": "projects", "label": "Project được đọc", "type": "list"}
  ],
  "premium": null
}
```

| Trường | Ý nghĩa |
|---|---|
| `id` | `^[a-z][a-z0-9-]{1,40}$`, là key của module và URL `/x/<id>` |
| `sdk` | major version của SDK addon cần (§5.3); Hub từ chối nếu không khớp |
| `schemaVersion` | luôn `3` (cấu trúc gói §3); Hub chỉ đọc cấu trúc này |
| `runtime` | `python` (dùng `python.exe` embed của Hub), `node` (`app/node/node.exe` mang trong addon trên Windows) hoặc `dotnet` (`dotnet` có sẵn trên máy, `entry` là `.dll` đã publish; chỉ `managed`) |
| `entry` | tên file trong `app/`: `main.py`, `main.mjs` hoặc `<Tên>.dll` |
| `lifecycle` | `managed`, `daemon` hoặc `external` (§4) |
| `service` | chỉ cho `external`: `{"port": N}`, cổng mặc định của chương trình trên `127.0.0.1` (không có `runtime` / `entry`) |
| `menu` | `label`, `icon` (Material Symbols), `summary`: như `Module` |
| `ui` | bỏ trống: Hub dùng trang tự sinh (§5.4) |
| `mcp` | bỏ trống nếu không có MCP; mỗi tool phải có một dòng trong `GUIDE.md` (như `tests/test_modules.py`) |
| `settings` | form do Hub vẽ; `type`: `text`, `folder`, `list`, `switch`, `select`, `records` (mỗi dòng nhiều ô: khai `fields` gồm `key`, `label`, `type` `text`/`select` + `options`, `required`, `placeholder`, `help`, `showWhen` `{ô khác: [giá trị]}` để chỉ hiện ô theo giá trị ô khác; lưu dạng danh sách object, tối đa 100 dòng) |
| `premium` | key premium khoá addon, hoặc `null` |
| `commands` | chỉ cho `daemon`: `init`, `start`, `status` |
| `exports` | hàm cho addon khác đọc (`name`, `description`, `params`, `returns`, `example`, `since`); schema là tập con JSON Schema của `addons/contract.py` |
| `uses` | `{"<id>": {"version": "^1.2.0", "exports": [...], "optional", "built"}}`, addon khác mà addon này đọc |
| `requires` | `{"hub": ">=0.2.0"}`, Hub từ chối khi version của nó không khớp |

Manifest được kiểm trong `addons/manifest.py`: tham số lệnh chỉ là chuỗi đơn giản, `entry` là tên một file trong `app/`.
`exports` / `uses`: §3.2.

**Danh sách MCP cho công cụ bên ngoài:** `GET /api/mcp` trả mọi server MCP của Hub (module có sẵn và addon, theo thứ tự
menu): `{servers: [{key, label, kind: "builtin" | "addon", command, path, url, scope, tools: [tên tool]}]}`. Đọc từ khai
báo nên không chạy addon nào. Thêm `?detail=1` để lấy cả mô tả: mỗi tool thành `{name, description, inputSchema, readOnly}`
(Hub hỏi `tools/list` của từng server, nên addon chưa chạy sẽ được khởi động như với mọi client MCP; server không trả lời
giữ nguyên danh sách tên và có thêm `unavailable` ghi lý do). Premium đang khoá không có trong danh sách.

### 3.2 Addon đọc dữ liệu của nhau (`exports` / `uses`)

Thiết kế đầy đủ và lý do: `docs/plans/addon-interop.md`. Hướng dẫn cho tác giả addon: `kit/AGENTS.md` §4.3.

| Phần | File |
|---|---|
| Khoảng version (`^`, `~`, `>=a <b`, `\|\|`) | `addons/semver.py` |
| Tập con JSON Schema, kiểm dữ liệu, so hai bản contract (phá vỡ hay không, theo chiều params / returns) | `addons/contract.py` |
| Tương thích khi cài / gỡ / mở Hub, trạng thái ok / degraded / broken, kiểm lúc gọi | `addons/deps.py` |
| Cài hai bước (409 `needs_review` + token, `POST /api/addons/staged/<token>` với `accept`), addon mặc định theo thứ tự phụ thuộc, bản mặc định bị giữ lại (`user/addons-held.json`) | `addons/install.py` |
| `POST /api/addons/call/<id>/<export>` (token gọi ngược của tiến trình addon, độ sâu ≤ 3, kiểm params / kết quả, ghi Giám sát), `GET /api/addons/contracts` | `addons/routes.py` |
| Module có sẵn làm provider (`Module(exports=…)`) | `addons/builtin.py` |
| `addon.call`, `@addon.export`, `addon.fake` | `addons/sdk.py`; Node: `addons/hub_client.mjs` (Hub truyền đường dẫn qua `VIEWER_HUB_NODE_SDK`) |
| Kit: `.sdk/addons/<id>.json/.md`, `npm run exports`, `built` tự điền khi build, B giả khi test | `addons/sdk_kit.py`, `kit/sdk/build.mjs` |

Chỉ addon `managed` gọi được addon khác (Hub cấp `VIEWER_HUB_URL` + `VIEWER_HUB_CALLER_TOKEN` mỗi lần chạy); addon
nào cũng cho gọi được (managed / external qua HTTP `POST /export/<name>`, daemon qua kênh quản trị).

**Module có sẵn cũng cho gọi được.** Một module trong `viewer_hub/` khai `exports=Exports(contract=<file json>,
call=<hàm>)` trong `Module(...)` (`app/modules.py`); file json cùng định dạng `exports` của `addon.json`, `contract.py`
kiểm như với addon. Với `deps.py` module là một provider (`addons/builtin.py`): id = key module, version = version của
Hub, không `uses`, luôn có mặt (module có sẵn không bao giờ premium). Route gọi chạy hàm ngay trong tiến trình Hub nhưng
vẫn kiểm params / kết quả, giới hạn số lời gọi cùng lúc và ghi Giám sát (`<addon>→<module>`); hàm báo lỗi bằng
`contract.ExportError(code, message, status)`. `GET /api/addons/contracts` liệt kê cả module (`"builtin": true`), nên
`.sdk/addons/<key>.md` gợi ý `"version": ">=<bản Hub>"` thay vì `^` (version của Hub tăng minor thường xuyên).

| Module | Export | Trả về |
|---|---|---|
| `codemap` (`codemap/exports.json`, `exports.py`) | `erd_model` | Model ERD (`erd.build`) theo `table` / `schema` / `system` / `tables`, tuỳ chọn kèm chữ Mermaid / DBML |
| | `db_objects` | Tìm bảng (tên kỹ thuật, tên logic, hệ thống), danh sách schema / hệ thống / pack |
| | `table_usage` | Tính năng (màn hình, API, job…) và code đọc / ghi một bảng, chữ CRUD |

Addon `erd` (ERD cả cơ sở dữ liệu, project `viewer-hub-addons/erd`) dùng ba export này; Code map chỉ còn ERD của các
bảng một tính năng dùng (tab **Dữ liệu**) và chuyển trang ERD cũ (`#/erd`) sang `/x/erd` khi addon đã cài.

---

## 4. Tiến trình và vòng đời

| | `managed` (kiểu svn) | `daemon` (kiểu bridge) |
|---|---|---|
| Ai bật | Hub, ở request đầu tiên tới `/x/<id>/…` | User bấm Start (hoặc autostart đã bật) |
| Ai tắt | Hub, khi thoát hoặc khi addon nhàn rỗi lâu | User bấm Stop; daemon sống tiếp khi Hub đóng |
| Cổng | Hub chọn cổng trống, truyền `--port` | Daemon tự báo `adminChannel` qua lệnh `status` |
| Lệnh | `<runtime> <entry> serve --port N` (stdin là pipe cha, §7.2) | `init` / `start` / `status` (hợp đồng `addons/runner.py` `Daemon`) |

Biến môi trường Hub truyền vào (cả hai loại):

- `VIEWER_HUB_ADDON_TOKEN`: token ngẫu nhiên mỗi lần chạy; addon từ chối request không có header `X-Viewer-Hub-Token` đúng.
- `VIEWER_HUB_ADDON_DATA`: `<data>/addons/<id>/`; addon chỉ ghi ở đây (ghi atomic). Không bao giờ chạm `hub.db`.
- `VIEWER_HUB_ADDON_SETTINGS`: đường dẫn file `settings.json` Hub đã ghi từ form.

HTTP addon phải trả lời (chỉ bind `127.0.0.1`):

| Endpoint | Ý nghĩa |
|---|---|
| `GET /health` | 200 khi sẵn sàng |
| `/api/*` | API của addon cho UI; lỗi dạng `{"error": {"code", "message"}}` như `spa.ApiError` |
| `POST /mcp` | MCP JSON-RPC (nếu khai `mcp`) |
| `POST /shutdown` | dừng êm (`managed`); `daemon` dùng `/api/daemon/shutdown` như hiện tại |
| stdin (pipe) | `managed`, khi `VIEWER_HUB_PARENT_PIPE=1`: hết stdin thì thoát. Hub bị kill / crash thì không gọi được `/shutdown`; pipe tự đóng nên addon không bị bỏ lại. Python: `addons/host.py` làm sẵn; Node: tự làm |

**`external`** (chương trình .NET, Java… có sẵn, khó chuyển sang Python / Node): Hub **không chạy, không dừng** gì
(`runner.External`). Người dùng tự cài và mở chương trình; nó phục vụ `/health`, `/api/*`, `/mcp` như bảng trên trên
`127.0.0.1:<cổng>`. Hub thêm setting `port` (mặc định `service.port`), coi `GET /health` = 200 là "đã kết nối", không
gửi token (không trao được cho chương trình mình không chạy), không có nhật ký. `start` / `stop` / `restart` trả 404;
gỡ addon không đụng tới chương trình. Lọc MCP chỉ đọc vẫn như `managed`. Gói addon chỉ có `addon.json`, `GUIDE.md`,
`ui/`: không bao giờ chứa `.exe` / `.dll` (§7). Trang: thẻ **Chương trình ngoài** (đã kết nối / chưa, kiểm tra lại).

Addon Python được chạy bằng chính python embed nên dùng lại `viewer_hub.core.mcp` (`dispatch`, `ToolError`, `READ_ONLY`,
`int_arg`). Addon Node dùng `mcp.mjs` trong template (§8).

---

## 5. Giao diện

### 5.1 Ý tưởng

Addon tự build UI ở project riêng, ra `ui.js` (ES module) và `ui.css`. **Nhưng không đóng gói React và Material 3**: dùng
chung bản của Hub lúc chạy, qua SDK.

- Một bản React duy nhất, nếu không hooks và context (`useTitle`, `useLayout`, `AppContext`) hỏng.
- `@material/web` chỉ define custom element một lần; `md.js` của Hub đã đăng ký, addon đăng ký lại sẽ báo lỗi.
- React Flow là của Hub (`@vh/flow`, `web/src/sdk/flow.js`: export lại `@xyflow/react` cùng React của Hub, thêm CSS,
  `layoutGraph()` sắp xếp đồ thị lồng nhau trong Web Worker `graph-layout.worker.js`). Thư viện khác (chart…) addon tự đóng gói.
- Mermaid là của Hub (`@vh/mermaid`, `web/src/sdk/mermaid.js`, khoá `securityLevel: strict`): Mermaid / d3 dùng
  `innerHTML` nên addon không tự đóng gói được (bị quét từ chối); Hub chịu trách nhiệm cập nhật nó.

```
Project addon                              Viewer Hub (đã cài)
  web/src/index.jsx                          /static/dist/sdk/react.js
    import { Button } from "@vh/md"    ──►   /static/dist/sdk/jsx-runtime.js
    import { useLoad } from "@vh/ui"         /static/dist/sdk/md.js      Button, Dialog, FilterBar…
  vite build ─► ui.js, ui.css                /static/dist/sdk/ui.js      PageHeader, SearchBar, useLoad, http…
                                             /static/dist/sdk/mermaid.js render, parse, svgElement (Mermaid: chunk lười)
                                             /x/<id>/ui.js  ← Shell import() khi mở menu của addon
```

### 5.2 Hợp đồng trang

Giống `web/src/modules/<key>/index.jsx`, thêm `api` và `addon`. Trang nằm **trong khung của Hub**
(`web/src/app/pages/AddonFrame.jsx`, `HubAddonPanel` trong `web/src/app/addon.jsx`): một hàng `PageHeader`, mô tả
(`summary`) bên trái; bên phải trạng thái (daemon: bấm mở hộp chạy / dừng / khởi động lại có xác nhận, tự chạy, gateway;
external: đã kết nối), **Nhật ký**, **Cài đặt** (form `settings` trong hộp thoại). Banner chỉ khi cần người dùng làm
gì (dịch vụ dừng, chưa kết nối, lỗi, thiếu setting `required`). Addon managed không có nút chạy / dừng. Rồi tới trang
của addon; nó mở hộp cài đặt bằng `useAddon().openSettings(key)`.
Điều khiển tiến trình và log luôn là của Hub: trang addon bị lỗi hay quên thì vẫn dừng được, vẫn đọc được log.

```jsx
import { Loading } from "@vh/md";
import { useLoad, useTitle } from "@vh/ui";

export default function Page({ module, subpath, api, addon }) {   // api = http trỏ sẵn vào /x/<id>/api
  useTitle(module.label);                                         // addon = thông tin thẻ của Hub (addon?.running)
  const { data } = useLoad(() => api.get("/items"));
  return data ? <List items={data.items} /> : <Loading />;
}
```

- Log: Hub ghi stdout / stderr của tiến trình addon vào `<logs>/addon-<id>.log` (xoay vòng ~2 MB, giữ một file
  `.1`). Daemon chạy qua `runner.tee` (Python của Hub): Windows vẫn có cửa sổ console thu nhỏ hiện output (không cửa
  sổ ẩn), đồng thời ghi log. `GET /api/addons/<id>/log` trả toàn bộ log, `GET /api/addons/<id>/status` để trang hỏi
  nhẹ mỗi 10 giây (daemon dừng / chạy ở nơi khác).
- Gỡ / cập nhật addon dừng daemon trước, cả khi daemon chạy từ lần mở Hub trước; dừng không được thì báo lỗi, không
  xoá thư mục.

- `subpath`: phần URL sau `/x/<id>`, addon tự route bên trong.
- CSS: dùng token / class của `md.css`; class riêng có tiền tố `<id>-`.
- Quy tắc giao diện giữ nguyên: chữ tiếng Việt, `SearchBar` + `FilterBar`, không `dangerouslySetInnerHTML` với dữ liệu.

### 5.3 SDK (phía Hub)

- `web/vite.config.js` thêm entry `sdk/react`, `sdk/jsx-runtime`, `sdk/md`, `sdk/ui` với
  `preserveEntrySignatures: 'strict'`. `app.js` cũng import qua các entry này, để Hub và addon chắc chắn cùng một bản.
- Những gì `sdk/*` export là **public API**, có version (`sdk: "1"`). Đổi chữ ký / xoá export = tăng major; thêm export =
  không đổi major.
- Phát kèm `@vh/sdk-types` (chỉ `.d.ts`) để editor gợi ý khi viết addon.

### 5.4 Hub thay đổi gì

1. `GET /api/app`: addon có UI thì `scripts[id] = "/x/<id>/ui.js"`, `styles[id] = "/x/<id>/ui.css"`. `pages.js` đã có nhánh
   `app.scripts`; thêm nạp CSS.
2. Shell bọc trang addon trong `ErrorBoundary`: addon lỗi chỉ hiện banner, menu và trang khác vẫn chạy.
3. **Trang tự sinh** khi addon không có `ui`: trạng thái (chạy / dừng, nút Start / Stop cho daemon), form setting từ
   `settings`, nội dung `GUIDE.md` (địa chỉ MCP nằm ở trang Hướng dẫn). Addon chỉ có MCP không cần viết JSX.
4. `/x/<id>/*` (file tĩnh của addon) trả `Cache-Control: no-cache` để vòng dev không cần build lại Hub.

### 5.5 Addon daemon

UI giống hệt: gọi `api.get(...)` → `/x/<id>/api/*` → Hub relay sang `adminChannel` của daemon (`addons/channel.py`, kênh quản trị của
daemon). UI không cần biết daemon chạy ở cổng nào.

---

## 6. Hub: các thành phần

```
viewer_hub/addons/
  manifest.py    đọc + kiểm addon.json
  install.py     cài zip (§7.1): giải nén vào thư mục tạm, kiểm, rồi mới thay bản cũ; addon mặc định; nhớ addon đã gỡ
  pack.py        đóng zip (cùng bộ kiểm với install.py)
  signature.py   chữ ký Ed25519 (signature.json)
  runner.py      managed (Popen, chờ /health, pipe cha, crash backoff, log) + daemon (init / start / status) + external
  limits.py      số request đồng thời mỗi addon (§7.2)
  proxy.py       HTTP tới addon: JSON, stream (SSE, timeout nhàn rỗi), MCP (lọc tool chỉ đọc, ghi monitor.db)
  channel.py     kênh quản trị của daemon (named pipe / unix socket)
  registry.py    addon → Module(key, label, icon, prefix="/x/<id>", guide, mcp, premium)
  routes.py      blueprint /x/<id>/…: trang (spa.page()), file tĩnh, relay /api/* và /mcp; /api/addons (cài / gỡ)
  host.py, sdk.py  SDK Python cho addon (Addon, tool, route, watch_parent)
  sdk_kit.py, kit/ SDK người dùng tải về (§8.1)
  legacy.py      chuyển setting `svn.repos` cũ sang addon svn, 308 /svn/* → /x/svn/*
  gateway.py     địa chỉ gateway cho daemon
```

- `app/modules.all_modules()` = builtin `PACKAGES`; `Hub.every_module` = builtin + addon đã cài (đọc lúc gọi).
- Một blueprint `/x/<id>/…` duy nhất, chọn addon theo id lúc nhận request, nên **cài / gỡ addon không cần khởi động lại**.
- `viewer-hub mcp <command>`: với addon, chuyển stdio ↔ HTTP `/x/<id>/mcp`; addon không cần tự viết stdio.
- Proxy MCP kiểm `tools/list`: tool thiếu `readOnlyHint` bị ẩn (quy tắc MCP chỉ đọc).
- Mọi lời gọi MCP tới addon (HTTP hay stdio) đi qua `addons/proxy.mcp_call` nên được ghi vào `monitor.db` (trang
  Giám sát); addon không phải làm gì. Hub lấy mẫu RAM / CPU của addon 30 giây một lần và ghi sự kiện chạy / dừng /
  dừng bất thường / ghi log quá nhiều.
- `packaging/check_security.py`: chỉ `addons/runner.py` (và vài file builtin có danh sách) được dùng `subprocess`.
- Addon premium: `routes.py` kiểm khoá mỗi request, nên nhập mã mở khoá là dùng được ngay. Tên tính năng premium
  chưa mở khoá không bao giờ hiện trên `/api/app`, `/api/home`, `/api/help`.

---

## 7. Bảo mật và tin cậy

`ui.js` chạy cùng origin `127.0.0.1` với Hub nên gọi được mọi API của Hub; tiến trình addon chạy với quyền của user. Vì
vậy addon có quyền ngang Hub, và chỉ cài addon tin cậy:

- **Chữ ký:** `signature.json` ký `addon.json` + sha256 từng file bằng khoá Ed25519 (cùng gốc tin cậy với mã mở
  khoá premium, `core/unlock.py`, khoá `~/.viewer-hub/unlock-signing.key` không bao giờ vào repo). Addon chưa ký
  vẫn cài được, giao diện ghi rõ "addon do admin cung cấp".
- **CSP** giữ `script-src 'self'`: addon không tải được code từ ngoài.
- Token mỗi lần chạy (§4) để trang khác trên máy không gọi thẳng được tiến trình addon.
- `external`: Hub chỉ nối tới `127.0.0.1` (không bao giờ host khác), không tới cổng của chính Hub; chương trình tự chịu
  trách nhiệm chỉ nghe `127.0.0.1` vì không có token.

### 7.1 Kiểm tra lúc cài (`install.py`, `core/scan.py`)

Zip được giải nén vào thư mục tạm và kiểm hết; **chỉ khi qua mọi bước** Hub mới dừng bản đang chạy (`before_swap`)
và thay. Upload lỗi không bao giờ làm dừng addon đang chạy.

| Kiểm | Từ chối khi |
|---|---|
| Zip | zip slip (`..`, `\\`, `:`, đường dẫn tuyệt đối), symlink, zip bomb (tổng kích thước / số file / tỉ lệ nén), không có `addon.json` ở gốc hoặc trong đúng một thư mục |
| Cấu trúc gói | gốc gói có thứ ngoài `addon.json`, `GUIDE.md`, `signature.json`, `ui/`, `app/`, `assets/`, `legal/` (project nguồn nén tay bị từ chối) |
| Tên file | tên Windows không giữ được (`CON`, `NUL`, `COM1`…, ký tự `<>:"\|?*`, kết thúc bằng `.` hoặc dấu cách), hai tên chỉ khác hoa / thường |
| Manifest | `addon.json` sai schema / `sdk` khác major, `schemaVersion` khác 3, `entry` không phải file trong `app/`, lệnh daemon không phải chuỗi đơn giản |
| Chỗ | `id` trùng module builtin hoặc trang của Hub (`RESERVED_PAGES`: premium, settings, help, api, sdk, static, x, call, staged, contracts); `mcp.command` trùng lệnh builtin hoặc addon khác |
| Chữ ký | `signature.json` hỏng, không đúng id / version, không phải khoá đã biết, file khác bản đã ký; addon đang cài **đã ký** mà bản mới **chưa ký** |
| Quét code (Python) | file thực thi / native (`.exe` `.dll` `.pyd` `.so` `.node` `.ps1` `.bat` `.cmd` `.sh` `.jar`…, trừ `app/node/node.exe`, và trừ `.dll` là assembly .NET trong `app/` của addon `runtime: dotnet`: kiểm CLR header, kèm ghi chú cho admin), `shell=True`, `os.system` / `os.popen`, `eval` / `exec`, PowerShell / `cmd /c`, registry / autostart, `pickle` / `marshal`, `yaml.load` không SafeLoader |
| Quét code (trang `ui/`, `.css`, `.html`) | tải từ CDN (`https://cdn.…`, unpkg, jsdelivr, cdnjs, Google Fonts), `eval` / `new Function`, `innerHTML =` |
| Trang vẽ lại phần đầu của Hub (`core/scan.py` `UI_RULES`, trên `ui/*.js` đã giải mã `\uXXXX`) | gọi `/api/addons/…`; gọi API `"/settings"` / `"/config"` của addon; nút / nhãn `Cài đặt`, `Nhật ký`, `Khởi động lại`…; `md-banner` nói về cấu hình. Cấu hình chỉ qua `settings` (+ `required`) và `useAddon().openSettings()` |
| Quét code (Node của addon) | `child_process` với `shell: true` |

**Chỉ ghi chú** (hiện cho admin sau khi cài, không từ chối): `GUIDE.md` thiếu dòng cho một tool MCP; code Python của
addon gọi mạng, `subprocess`, socket, base64; Node có `child_process`, `eval`, nhắc PowerShell. Addon là tiến trình
riêng nên được làm những việc này, admin cần biết. Dòng có `# noqa: security` được bỏ qua.

Quét là danh sách chặn (deny-list) cho mô hình tin cậy admin: chặn lỗi hay gặp và code đáng ngờ, không phải sandbox.

### 7.2 Addon không làm chết Hub

| Rủi ro | Hub làm gì |
|---|---|
| Addon crash / lỗi Python | Tiến trình riêng: Hub chỉ trả 503 cho `/x/<id>`, phần còn lại chạy bình thường |
| Crash liên tục | 3 lần dừng bất thường trong 300 giây → không khởi động lại 60 giây (503 "chờ"), không spawn mỗi request |
| Treo / chậm | `limits.py`: mỗi addon tối đa 4 request thường + 2 stream cùng lúc (waitress có 16 thread); hết chỗ thì chờ 5 giây rồi 503 "addon đang bận" |
| Stream im lặng | SSE không có dữ liệu 300 giây thì đóng, trả lại chỗ |
| Ghi log vô hạn | log managed vượt 50 MB → Hub dừng addon, ghi sự kiện `log-flood`, cảnh báo trên Giám sát |
| Hub bị kill (`kill -9`, crash) | managed addon có stdin là pipe (`VIEWER_HUB_PARENT_PIPE=1`): hết stdin thì tự thoát, không bỏ lại tiến trình mồ côi. Hub còn bắt SIGTERM để dừng addon êm |
| Trang addon lỗi | `ErrorBoundary`: chỉ trang đó hiện banner |

Giới hạn còn lại: trang addon chạy cùng tab với Hub, một vòng lặp vô hạn trong `ui.js` làm treo tab (không làm chết
server; tải lại trang hoặc gỡ addon). Cách mạnh hơn (iframe khác origin + `postMessage`) để sau, nếu có addon bên thứ ba.

---

## 8. Phía tác giả addon

Hai đường, cùng một định dạng zip và cùng bộ kiểm tra lúc cài (`viewer_hub/addons/pack.py` = những gì `install.py` kiểm):

| | Tác giả Hub (có source) | Người dùng (chỉ có bản phát hành) |
|---|---|---|
| Lấy công cụ | SDK (`.sdk/`) chép vào thư mục addon: `just addon-sdk-sync <dir>…` | **Cài đặt → Addon → Tải SDK** (`/api/addons/sdk`, `viewer-hub addon sdk`) |
| Build | `just addon <dir>`: sync SDK, `npm install` nếu cần, `node .sdk/build.mjs build` → gói ở `build/<id>/` | `npm install` một lần, `npm run build` (`.sdk/build.mjs`) |
| Đóng zip | `just addon <dir>`: **ký** bằng khoá mã mở khoá | `npm run zip` (chưa ký), `viewer-hub addon pack build/<id>` (kiểm tra, ký bằng khoá admin) |
| Sửa trang nhanh | `just addon-watch <dir> <data>` | `npm run watch -- --out <data>/addons/<id>/ui` |

Cả hai đường build bằng cùng một `.sdk/build.mjs` (không còn cấu hình Vite riêng trong Hub). `just addon-sdk-sync`
thay `.sdk/*` và `AGENTS.md`, thêm `.gitignore` nếu thiếu, gộp `scripts` / `devDependencies` vào `package.json`;
chạy lại sau khi SDK trong Hub đổi.

### 8.1 SDK cho người dùng (`viewer_hub/addons/kit/`, `sdk_kit.py`)

**Project và gói tách nhau.** Người dùng giải nén SDK, đổi tên thư mục, `npm run new -- simple|daemon|external <id>`,
viết, `npm test`, `npm run zip`, tải lên. Build lắp gói vào `build/<id>/` từ nguồn, không bao giờ ghi vào nguồn; Hub chỉ
cài gói đúng cấu trúc §3.

```
my-addon/                (zip SDK: viewer-hub-addon-sdk-<sdk>.zip)
  AGENTS.md              toàn bộ quy tắc cho AI agent: chọn loại, cấu trúc, addon.json, SDK Python, HTTP của managed
                         Node, hợp đồng daemon (lệnh + kênh quản trị), trang (props, @vh/md, @vh/ui), GUIDE.md, bảo mật
  README.md              các bước cho người
  package.json           npm run new | build | watch | check | test | zip
  addon/                 addon.json + GUIDE.md (khai báo và hướng dẫn)
  src/                   chương trình: python = main.py (+ lib/), node = main.mjs, dotnet = dự án .NET
  web/                   trang (index.jsx)
  assets/ legal/         (tuỳ chọn) chép vào gói
  test/                  test của tác giả
  build/<id>/ dist/      sinh ra: gói và zip (gitignore)
  .sdk/build.mjs         assemble build/<id>/: addon/ → addon.json + GUIDE.md, src/ → app/ (Node: esbuild gom package
                         npm; .NET: dotnet publish), web/ → ui/ (vite), assets/ legal/; check (manifest, cấu trúc gói,
                         quy tắc quét của core/scan.py); test; zip
  .sdk/new.mjs           chép mẫu vào thư mục, đặt id; từ chối nếu đã có addon/addon.json
  .sdk/templates/simple  managed Python: API + trang + 2 tool MCP (ghi chú) + test/test_main.py
  .sdk/templates/external nối tới chương trình có sẵn trên 127.0.0.1
  .sdk/templates/daemon  daemon Node không dependency: init / start / status, kênh quản trị, EVENTS, trang SSE
  .sdk/python/viewer_hub/ SDK Python thật của Hub (addons/sdk.py + core/mcp.py, monitor.py): để đọc và để `npm test`
                         chạy test addon không cần Hub
```

`tests/test_addon_sdk.py` giữ AGENTS.md khớp với export của `@vh/ui` / `@vh/md`, giữ `PACKAGE_FILES` / `PACKAGE_DIRS` của
`build.mjs` khớp `core/scan.py`, chạy thật `new` / `check` / `test` / `zip` và daemon mẫu, và chạy cùng mẫu code xấu qua
`core/scan.py` lẫn `scan()` của `build.mjs` (hai bên phải giống).

### 8.2 Daemon ở project riêng

Gói addon luôn **tự chứa** chương trình (trong `app/`). Daemon viết ở repo khác (như `my-bridge`) vào addon bằng cách repo
đó tự lắp gói đúng §3 (chương trình đã bundle vào `app/`, giấy phép vào `legal/`, trang vào `ui/`) rồi nén; `viewer-hub
addon pack <thư mục gói>` kiểm tra và ký. Hoặc code daemon nằm ngay trong project addon (`src/`, `npm run build` gom
thành `app/main.mjs`).

**MCP Bridge** dùng cách 1 theo kiểu riêng: repo `my-bridge` có `addon/` (addon.json, GUIDE.md, `web/index.jsx`) và
`packaging/build_addon.mjs` lắp gói (`app/bridge.mjs`, `legal/`, `ui/` bundle bằng esbuild với React / `@vh/*` để
external), ký bằng Ed25519 của Node (cùng định dạng `signature.json`) và ra `dist/mcp-bridge-<ver>.zip`. Viewer Hub không chứa code nào của bridge.

Chương trình phải hiểu `init` / `start` / `status --json` và nói giao thức kênh quản trị (§4, `channel.py`); mẫu:
`kit/sdk/templates/daemon/src/main.mjs`.


### 8.3 Addon mặc định

`addons/*.zip` trong repo Viewer Hub (đã ký, commit) được `just build` kiểm tra và đóng vào `<release>/addons/`; Hub
cài chúng khi mở (`install_bundled`: thiếu hoặc bản mới hơn; khi dev thì dùng thẳng `addons/` của repo).
`just addon-default <zip>` kiểm tra một zip, bỏ bản cũ của cùng addon rồi chép vào. Người dùng không phải upload.
Hiện có: `svn`, `diagram`, `api-specs`, `db-query` (premium), `mcp-bridge` (premium, khoá cho tới khi nhập mã).

Admin gỡ một addon mặc định thì Hub nhớ (`<data>/user/addons-removed.json`) và không cài lại khi mở; upload lại zip
của addon đó thì bỏ nhớ.

---

## 9. Quyết định

- Khoá ký addon: **dùng chung** khoá với mã premium (`~/.viewer-hub/unlock-signing.key`); không có khoá thì addon build ra *chưa ký* (admin tự chịu, hiện badge).
- `managed` addon: chạy khi có request đầu tiên, **không tắt khi nhàn rỗi**, dừng khi Hub thoát (hoặc nút Dừng).
- Dependency native: **từ chối** lúc cài (`core/scan.py`, chỉ cho `app/node/node.exe` và assembly .NET của addon `dotnet`); addon chỉ mang mã thuần Python trong `lib/`.
- Menu: addon đứng **sau** module builtin, theo `label`.
- Trang addon: `ui/ui.js` (+ `ui/ui.css`), import React/kit của Hub qua `/static/dist/sdk/{react,jsx-runtime,react-dom,md,ui}.js`; quản lý qua `/api/addons`.
- Tính năng premium luôn là addon, module builtin không bao giờ premium.
- SVN là addon mặc định (`viewer-hub-addons/svn`), không còn trong Hub; `legacy.py` giữ link cũ và repo đã lưu.
