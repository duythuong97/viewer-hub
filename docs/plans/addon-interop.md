# Plan: addon dùng dữ liệu của nhau (`exports` / `uses`)

Trạng thái: bước 1–7 xong (2026-11-15); addon svn 1.2.0, api-specs 0.3.0, diagram 0.4.0, db-query 0.4.0 đã khai `exports` (schemaVersion 2) và nằm trong `addons/`. Khác với plan: xem §8.

## 0. Hiện trạng (đã kiểm trong code)

- Mỗi addon managed là một tiến trình riêng (`runner.Managed`, `subprocess.Popen`). Không có cách gọi function trực tiếp.
- Addon chỉ nhận `VIEWER_HUB_ADDON_ID/DATA/SETTINGS/TOKEN` (`runner.py`): không biết cổng Hub, cổng / token addon khác.
- `scan_addon`: gọi mạng trong addon Python chỉ là **ghi chú** cho admin, không bị từ chối. Rào chắn thật là không có
  địa chỉ + token, không phải scanner.
- Trang web của addon gọi được `addonApi("<id khác>")` (cùng origin), không có tài liệu, không kiểm tra gì.
- `install.py` chỉ kiểm chỗ đứng (id, `mcp.command`, chữ ký); không có khái niệm phụ thuộc giữa addon.

## 1. Mục tiêu và nguyên tắc

1. Addon B **tự khai** những hàm cho addon khác dùng (`exports`), kèm schema tham số và kết quả. Route nội bộ của B vẫn đóng.
2. Addon A **khai** mình dùng gì của ai (`uses`), kèm khoảng version và ảnh chụp contract lúc build.
3. Mọi lời gọi đi **qua Hub** (A → Hub → B): Hub kiểm quyền, kiểm schema, tự start B, ghi monitor; một cách gọi cho cả
   managed / daemon / external.
4. **Không cài được thứ sẽ làm hỏng addon khác mà không biết**: kiểm tương thích ở cả hai chiều khi import zip, khi gỡ,
   khi Hub tự cập nhật addon mặc định; kiểm lại lúc chạy (trạng thái có thể đổi sau khi cài: gỡ, khoá premium).
5. Chỉ đọc (như MCP): export không được ghi dữ liệu của B. Dữ liệu user không bao giờ mất (gỡ / thay không chạm `user/addons`).
6. AI viết addon **thấy được** contract của các addon đã cài ngay trong kit.

## 2. Hợp đồng trong `addon.json`

### 2.1 `exports` (bên cung cấp, B)

```json
"exports": [
  {"name": "svn_log_search",
   "description": "Tìm commit theo từ khoá / tác giả / khoảng ngày",
   "params":  {"type": "object", "required": ["q"],
               "properties": {"q": {"type": "string"}, "limit": {"type": "integer", "default": 50}}},
   "returns": {"type": "object", "required": ["items"],
               "properties": {"items": {"type": "array", "items": {"type": "object", "required": ["rev", "author"],
                 "properties": {"rev": {"type": "integer"}, "author": {"type": "string"}, "msg": {"type": "string"}}}}}},
   "example": {"items": [{"rev": 123, "author": "an", "msg": "fix login"}]},
   "since": "1.2.0"}
]
```

- `name`: `TOOL_RE`, duy nhất toàn Hub thì không cần (gọi luôn kèm id), nhưng nên có tiền tố của addon.
- `params` / `returns`: **tập con JSON Schema** do Hub tự kiểm (không thêm dependency): `type` (object, array,
  string, integer, number, boolean, null), `properties`, `required`, `items`, `enum`, `default`, `description`,
  `maxLength`/`maximum` tuỳ chọn. Từ khoá khác → `AddonError` lúc parse (để phép so tương thích ở §4 luôn quyết định được).
- `example` bắt buộc, phải hợp lệ theo `returns` (kiểm lúc parse): dùng cho kit, cho B giả khi test, cho trang Hướng dẫn.
- Giới hạn: tối đa 64 export, manifest ≤ 256 KB, độ sâu schema ≤ 6.
- Chỉ lifecycle có cổng gọi được (managed, external, daemon qua kênh quản trị): cả ba đều nhận được.

### 2.2 `uses` (bên dùng, A)

```json
"uses": {
  "svn": {"version": "^1.2.0", "exports": ["svn_log_search"], "optional": false,
          "built": {"version": "1.3.0", "contract": {"svn_log_search": {"params": {…}, "returns": {…}}}}}
}
```

- `version`: khoảng semver, cú pháp tối thiểu `^x.y.z`, `~x.y.z`, `>=a <b`, `x.y.z` (tự viết parser trong
  `addons/semver.py`, có test; `version_key` hiện tại không đủ vì bỏ qua prerelease).
- `exports`: tên export A gọi. A **chỉ** gọi được các tên này (Hub kiểm lúc chạy).
- `optional`: `true` = A vẫn chạy được khi thiếu B (tính năng liên quan tắt); `false` = A cần B.
- `built`: **ảnh chụp contract** của B lúc A được build. `npm run build` / `addon pack` tự điền từ
  `.sdk/addons/<id>.json` (§6), tác giả không viết tay. Thiếu `built` vẫn cài được nhưng chỉ kiểm được version + tên
  (ghi chú khi cài: "không kiểm được schema").
- Không được `uses` chính mình; không trùng key.

### 2.3 `requires.hub`

Addon có `exports` / `uses` mà cài lên Hub cũ thì Hub cũ bỏ qua key lạ và A hỏng lúc chạy. Thêm
`"requires": {"hub": ">=0.2.0"}` (Hub kiểm với `viewer_hub.__version__`); kit tự thêm khi addon có `exports`/`uses`.
Hub cũ không biết `requires` thì không cứu được, nên **đồng thời** tăng `SCHEMA_VERSION` lên 2 khi có `exports`/`uses`
(`parse` của Hub cũ từ chối schemaVersion 2 với thông báo rõ). Addon không dùng tính năng này giữ schemaVersion 1.

## 3. Đường gọi lúc chạy

```
A ──HTTP 127.0.0.1──▶ Hub  POST /api/addons/<A>/call/<B>/<export>   header X-Viewer-Hub-Caller: <token gọi ngược của A>
                        │ 1 token khớp A (mỗi lần chạy một token, không trao cho trình duyệt)
                        │ 2 A khai uses[B] chứa export đó; B đã cài, không bị khoá premium, version trong khoảng
                        │ 3 kiểm params theo schema của B (áp default)
                        │ 4 độ sâu gọi ≤ 3 (header X-Viewer-Hub-Depth), chống vòng A→B→A
                        │ 5 runner.ensure() B → B: POST /export/<name> (managed / external) hoặc kênh quản trị (daemon)
                        │ 6 kiểm kết quả theo returns (sai: lỗi `bad_reply`, ghi log B) · giới hạn kích thước, timeout
                        ▼ ghi monitor.db: server "addon:A→B", tool = export
```

- `runner.env()` thêm `VIEWER_HUB_URL` (http://127.0.0.1:<cổng>) và `VIEWER_HUB_CALLER_TOKEN`.
- Route chỉ nhận từ tiến trình addon: không có header `X-Viewer-Hub` của trình duyệt, Origin bị từ chối, chỉ token.
- Mã lỗi: `dependency_missing`, `dependency_incompatible`, `export_unknown` (không có trong `uses` hoặc trong
  `exports` của B), `bad_params`, `bad_reply`, `dependency_unavailable` (503: B không chạy được), `call_depth`.
- **SDK Python** (`addons/sdk.py`): `addon.call("svn", "svn_log_search", {"q": "fix"}) -> dict`, giữ một kết nối
  keep-alive tới Hub; `@addon.export("svn_log_search")` đăng ký handler ở `/export/<name>`, lúc start kiểm mọi export
  trong manifest đều có handler (thiếu → không start, log rõ).
- **Node**: mã mạng phải nằm trong file của Hub, không chép vào addon. Hub truyền `VIEWER_HUB_NODE_SDK` = đường dẫn
  `hub-client.mjs` trong bản phát hành; addon `await import(pathToFileURL(process.env.VIEWER_HUB_NODE_SDK))`. Helper
  có `call()` và `serveExport()`.
- **Trang web**: không thêm đường mới. `addonApi("<id khác>")` vẫn chỉ là API của trang; dữ liệu liên addon đi qua
  backend của A (một chỗ kiểm). Ghi rõ trong `kit/AGENTS.md` là không gọi `addonApi` của addon khác.

## 4. Kiểm tương thích khi import zip (trọng tâm)

### 4.1 Cài thành hai bước: xem trước → xác nhận

Hiện `POST /api/addons` cài luôn. Đổi thành:

1. `POST /api/addons/preview` (upload): unpack + `check()` như hiện tại + **báo cáo tương thích** (§4.3). Zip giữ ở
   `tmp/addon-staged-<token>.zip` (hết hạn 15 phút, xoá khi Hub mở lại). Trả `{token, addon, report}`.
2. `POST /api/addons/install {token, accept: [<mã cảnh báo đã đồng ý>]}`: **chạy lại toàn bộ kiểm tra** (trạng thái có
   thể đã đổi giữa hai bước), rồi cài như `install_zip` hiện tại.

Báo cáo chia ba mức: **chặn** (không có nút cài), **cảnh báo** (phải tick đồng ý từng mục), **ghi chú** (chỉ hiện).
`POST /api/addons` cũ giữ cho CLI / test: tương đương preview + install và từ chối nếu có mục chặn hoặc cảnh báo
(trừ khi truyền `accept`).

### 4.2 Đồ thị phụ thuộc

`addons/deps.py` (mới, thuần hàm, không Flask): từ danh sách manifest đã cài + manifest sắp cài dựng đồ thị
`A --uses--> B` và trả về các vấn đề. Dùng chung cho: preview, install, uninstall, `install_bundled`, `Registry.refresh`
(trạng thái hiển thị), kiểm lúc chạy.

### 4.3 Các phép kiểm

Ký hiệu: **N** = addon trong zip, **cũ** = bản N đang cài (nếu có).

**a) N là bên dùng (`N.uses`)**

| # | Kiểm | Kết quả khi sai |
|---|---|---|
| U1 | `requires.hub` khớp Hub này | chặn |
| U2 | Không `uses` chính mình | chặn (lỗi manifest) |
| U3 | Mỗi B trong `uses` đã cài | `optional: false` → **cảnh báo** "N cần B ≥ x, chưa cài: N chạy nhưng tính năng … lỗi cho tới khi cài B". `optional: true` → ghi chú. (Không chặn: user có thể cài N trước rồi cài B.) |
| U4 | Version B đang cài nằm trong `uses.B.version` | cảnh báo (như U3) |
| U5 | Mỗi tên trong `uses.B.exports` có trong `B.exports` | cảnh báo, liệt kê tên thiếu |
| U6 | So `uses.B.built.contract` với contract hiện tại của B theo §4.4 | không tương thích → cảnh báo, liệt kê từng khác biệt |
| U7 | B bị khoá premium | ghi chú "cần mở khoá B" |
| U8 | Thêm N tạo vòng phụ thuộc (A→…→N→…→A, cả `optional`) | **chặn**: vòng gọi dễ treo cả hai tiến trình |

**b) N là bên cung cấp (`N.exports`), xét mọi addon X đang cài có `uses` N**

| # | Kiểm | Kết quả khi sai |
|---|---|---|
| P1 | Contract của N **tự nhất quán**: schema đúng tập con, `example` hợp lệ theo `returns`, tên không trùng | chặn (lỗi manifest) |
| P2 | So `cũ.exports` với `N.exports` theo §4.4: có thay đổi phá vỡ mà **major không tăng** | **chặn**: lỗi của tác giả N ("đổi `svn_log_search` phá vỡ: bỏ trường `msg` khỏi kết quả; tăng version lên 2.0.0") |
| P3 | Version N vẫn nằm trong `X.uses.N.version` | cảnh báo "X 1.0 cần N ^1.2: sau khi cài N 2.0, X không gọi được N" |
| P4 | Mỗi export X dùng vẫn còn trong N | cảnh báo (liệt kê X, export) |
| P5 | Contract N tương thích với `X.uses.N.built.contract` (§4.4) | cảnh báo, chi tiết từng khác biệt |
| P6 | Hạ version (N < cũ) | cảnh báo "hạ cấp", và P3–P5 vẫn chạy |
| P7 | Export bị bỏ mà không addon nào dùng | ghi chú |

**c) Khác**

| # | Kiểm | Kết quả |
|---|---|---|
| O1 | Gỡ B khi còn X `uses` B (`optional: false`) | hộp xác nhận liệt kê X; gỡ thì X chuyển trạng thái "thiếu phụ thuộc" |
| O2 | `install_bundled` (lúc mở Hub, không có ai xác nhận) | cài theo **thứ tự topo** (B trước A). Gặp mục **cảnh báo** loại P3–P5 → **không cập nhật** addon đó, log lỗi và hiện trên trang Cài đặt ("bản mặc định mới của N sẽ làm hỏng X: chưa cập nhật"). Gặp chặn → bỏ qua như hiện tại |
| O3 | Thay addon đã ký bằng zip chưa ký | giữ nguyên quy tắc hiện tại (chặn) |

### 4.4 So hai contract (`deps.compare(old, new) -> list[Change]`)

Quy tắc theo hướng dữ liệu, mỗi `Change` có `breaking: bool` và một câu tiếng Việt chỉ đúng đường dẫn
(`params.limit`, `returns.items[].msg`):

**params** (A gửi, B nhận): B phải nhận mọi thứ A từng gửi được.
- Phá vỡ: thêm trường `required` mới; bỏ một trường; đổi `type`; thu hẹp `enum`; giảm `maxLength`/`maximum`;
  trường optional thành required.
- Không phá vỡ: thêm trường optional; nới `enum`; required thành optional; đổi `default`, `description`.

**returns** (B trả, A đọc): A phải luôn nhận được những gì A từng dựa vào.
- Phá vỡ: bỏ trường đang `required`; required thành optional; đổi `type`; nới `enum` (A có thể gặp giá trị lạ).
- Không phá vỡ: thêm trường (A bỏ qua trường lạ, ghi trong AGENTS.md); optional thành required; thu hẹp `enum`.

**export**: bỏ export = phá vỡ; thêm export = không.

Không quyết định được (schema ngoài tập con) không thể xảy ra vì P1 đã từ chối lúc parse.

### 4.5 Trạng thái sau khi cài

`Registry.refresh()` chạy `deps` trên mọi addon đã cài, mỗi addon có `deps_status`: `ok` | `degraded` (thiếu optional)
| `broken` (thiếu / lệch phụ thuộc bắt buộc) kèm lý do. Hiện:

- Trang Cài đặt: badge trên thẻ addon + lý do.
- Trang addon (`AddonPanel`): hai dòng "Dùng dữ liệu của: …" / "Được dùng bởi: …", phụ thuộc lỗi tô đỏ, có link.
- `/help`: mục của B có bảng "Dữ liệu cho addon khác" (từ `exports`, như bảng Tool cho AI).
- Lúc chạy Hub vẫn kiểm lại (§3), nên trạng thái hiển thị chỉ để báo, không phải chỗ duy nhất chặn.

## 5. Kit cho AI viết addon

- `sdk_kit.build()` sinh `.sdk/addons/<id>.json` (contract máy đọc: version, exports) và `addons/<id>.md`
  (cho AI: mô tả, bảng tham số, ví dụ kết quả, `uses` mẫu chép được) cho **mỗi addon đã cài có `exports`**.
- `kit/AGENTS.md` thêm mục "Dùng dữ liệu addon khác": đọc `addons/`, khai `uses`, gọi `addon.call`, xử lý lỗi
  `dependency_*` (tính năng tắt nhẹ nhàng, không crash), bỏ qua trường lạ trong kết quả, không gọi `addonApi` của addon khác.
  Mục "Cho addon khác dùng dữ liệu": khai `exports`, `@addon.export`, quy tắc §4.4, tăng major khi phá vỡ.
- `npm run exports` (và `{{hub}} addon exports`): lấy contract mới nhất từ Hub đang chạy vào `.sdk/addons/` khi kit cũ.
- `npm run build` / `addon pack`: điền `uses.<id>.built` từ `.sdk/addons/<id>.json`; báo lỗi nếu export A dùng không
  có trong contract đã chụp. `npm run check` chạy §4.3 (U5, U6, P1, P2 với bản đã chụp) ngay trên máy tác giả.
- `npm test` / `addon test`: B giả trả `example`, kiểm params A gửi theo schema của B, nên test được mà không cần cài B.

## 6. Thứ tự làm (mỗi bước có test, chạy `just check`)

1. **Contract + semver**: `addons/semver.py`, tập con schema + validator + `compare` trong `addons/contract.py`;
   `manifest.parse` đọc `exports` / `uses` / `requires`, schemaVersion 2. Test: parse, validator, mọi dòng bảng §4.4.
2. **Đồ thị + kiểm tương thích**: `addons/deps.py` (U1–U8, P1–P7, O1, topo order). Test bằng manifest giả trong
   `tmp_path`, không cần chạy tiến trình.
3. **Cài hai bước**: `install.py` tách `stage()` / `commit()` (chạy lại kiểm khi commit), `routes.py` preview / install,
   giữ `POST /api/addons` cho CLI; `uninstall` trả dependents; `install_bundled` theo topo + O2.
   Test: cài A trước B, B 2.0 phá A, hạ version, vòng, zip đổi giữa preview và install, staged hết hạn.
4. **UI cài đặt**: `Settings.jsx` hộp báo cáo (chặn / cảnh báo tick / ghi chú), xác nhận gỡ; `addon.jsx` khối phụ thuộc.
5. **Đường gọi**: `runner.env` (URL, caller token), route `call`, `proxy` thêm `/export/<name>`, depth, monitor;
   kênh quản trị daemon thêm lệnh export. SDK Python `call` / `export`; `hub-client.mjs` cho Node.
   Test: tiến trình thật hai addon mẫu (như `test_addon_isolation.py`), mọi mã lỗi §3.
6. **Kit**: `sdk_kit` sinh `addons/`, `build.mjs` điền `built`, `check` / `test` với B giả, `kit/AGENTS.md`,
   `docs/addons.md`; `tests/test_addon_sdk.py` giữ AGENTS.md khớp manifest.
7. **Bảo mật** (`docs/GUIDELINE.md` §5): `check_security.py` cho phép `hub-client.mjs` và `sdk.py` gọi mạng (chỉ
   127.0.0.1); xác nhận route `call` không nhận từ trình duyệt; caller token không lộ qua `/api/addons/<id>`.

Bước 1–4 tự đứng được (chỉ kiểm, chưa gọi). Có thể phát hành sớm để các addon bắt đầu khai `exports`.

## 7. Câu hỏi còn mở

- U3/U4 đang là **cảnh báo**, không chặn (cho phép cài A trước B). Muốn chặt hơn: chặn khi `optional: false` trừ
  khi B nằm trong `addons/` mặc định của bản phát hành.
- Export có cần quyền theo user / setting của B không (vd. B chỉ cho A đọc repo đã chọn)? Bản đầu: B tự lọc theo
  setting của nó, như MCP.
- Có tự sinh tool MCP từ `exports` không (khai một lần, có cả API cho addon và tool cho AI)? Đề xuất làm sau bước 6.

## 8. Đã làm khác plan

- **Cài hai bước không có route preview riêng**: `POST /api/addons` lưu zip tạm (`install.stage`, hết hạn sau 15 phút)
  và kiểm luôn; có cảnh báo / chặn thì trả 409 `needs_review` kèm `token` và báo cáo. Admin xác nhận bằng
  `POST /api/addons/staged/<token>` với danh sách `key` cảnh báo đã chấp nhận; lúc đó kiểm lại từ đầu. CLI: `--yes`.
- **Không có bảng trên `/help`**: phụ thuộc hiện trên Cài đặt → Addon (badge, "dùng" / "được dùng bởi", bản cập
  nhật bị giữ) và banner trên trang addon khi `deps.state` khác `ok`; danh sách export ở `GET /api/addons/contracts`.
- **Không qua `/x/<id>/`**: route `call` gọi thẳng `POST /export/<name>` của addon đích (`proxy.request` cho managed /
  external, kênh quản trị cho daemon), kiểm `params` / `returns` theo contract, ghi monitor.
- **Addon mặc định cập nhật lúc khởi động**: không ai xác nhận, nên bản mới làm hỏng addon khác hoặc hạ version bị
  **giữ lại** (`user/addons-held.json`), hiện trên Cài đặt, thay vì cài.
- **db-query** chỉ export cấu trúc (`db_connections`, `db_tables`, `db_describe`), không export dữ liệu
  (`db_query`): addon khác không đọc được dòng dữ liệu thật.
- **mcp-bridge** giữ schemaVersion 1 (không có dữ liệu để chia sẻ); manifest v1 vẫn hợp lệ.
- Ported addon không khai `requires.hub`: schemaVersion 2 đã khiến Hub cũ từ chối.

