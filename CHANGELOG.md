# Changelog

Mọi thay đổi quan trọng của Viewer Hub được ghi nhận tại đây.

## [Unreleased]

## [v0.3.6] - 2026-11-27

### Addon: bật / tắt
- Công tắc cạnh mỗi addon ở **Cài đặt → Addon**. Addon tắt không còn trên menu, trang Hướng dẫn và MCP (cả MCP
  Bridge), tiến trình của nó dừng; addon vẫn cài, cài đặt và dữ liệu giữ nguyên. Bật lại là dùng ngay, không cần mở lại
  Viewer Hub (dịch vụ có "Tự chạy" thì chạy lại).
- Addon khác dùng dữ liệu của addon đang tắt báo **Thiếu phụ thuộc** cho tới khi bật lại.
- Nhãn, công tắc và nút gỡ trên mỗi dòng addon thẳng hàng.

### CSV: xem dữ liệu dài dễ hơn
- Trang CSV dùng hết chiều ngang; bảng kết quả cao gần hết màn hình.
- Chữ dài luôn xuống dòng (trước chỉ xuống dòng khi rê chuột vào, làm bảng nhảy).

## [v0.3.5] - 2026-11-26

### F-Search: hết lỗi hết bộ nhớ trên tài liệu lớn
- Sửa `MemoryError` khi tìm trúng tài liệu lớn, và tab Chrome báo **Out of Memory** / Chrome đơ vì đoạn trích của file
  một dòng (minified, JSON, log) bị gửi gần như nguyên file về trình duyệt.
- Server không còn nạp cả tài liệu vào bộ nhớ (đọc theo khối); tô từ khoá nhanh hơn nhiều với tiếng Việt, và tìm được
  chỗ khớp nằm sâu trong tài liệu (tới 32 MB mỗi trường, trước là 1 triệu ký tự).
- Đoạn trích có giới hạn độ dài và số chỗ tô; dòng code dài được cắt quanh từ khoá. Dựng đoạn trích quá 3 giây thì
  phần còn lại hiện không có đoạn trích, kèm thông báo.
- Kết quả theo nhóm: tối đa 100 tài liệu một trang, **Xem thêm** tối đa 100 tài liệu một nhóm.
- MCP `search_documents` / `read_document` cũng đọc theo khối. Tối đa 2 lần tìm chạy cùng lúc.
- `export-solr` ghi theo lô tính cả dung lượng, đỡ tốn RAM trên máy đóng pack.
- Data pack đang dùng không cần xuất lại.

## [v0.3.4] - 2026-11-22

### 🧩 Addon mặc định: mcp-proxy (1.0.0) và db-query (1.2.0)
- **mcp-proxy** (1.0.0): Addon mới cầu nối và tổng hợp các MCP server bên ngoài vào Viewer Hub, cho phép AI gọi các công cụ ngoài qua `proxy_call`.
- **db-query** (1.2.0): Bổ sung tool `db_connections` để AI xem danh sách kết nối đã cấu hình, schema, mô tả và trạng thái sẵn sàng (đã nhập mật khẩu hay chưa) trước khi thực hiện truy vấn `db_query`.

## [v0.3.3] - 2026-11-20

### Code map: trang Chỗ hở, ghi chú trên node, tổng quan menu
- Trang **Chỗ hở** (thanh trên): lời gọi / đọc / ghi bảng mà code map không theo được, mỗi chỗ kèm các node có thể là
  đích (địa chỉ, lý do). **Nối** thêm liên kết, **Không phải** bỏ khỏi danh sách (AI agent cũng không thấy nữa). Hàm
  Oracle, biến cục bộ, tên cột không còn bị tính là chỗ hở.
- Ô tìm kiếm hiện **địa chỉ** của node và vì sao nó khớp; dán địa chỉ để mở đúng node.
- **Ghi chú nghiệp vụ** trên trang node và thẻ node của luồng; AI viết được (file nhập, MCP) nhưng không đè ghi chú
  của người; code đổi thì hiện **Code của node này đã đổi**.
- Menu và trang đầu code map có **Xuất cho AI / Nhập kết quả AI** để AI đặt tên nghiệp vụ và viết tổng quan từ dưới
  lên; tổng quan cũ khi phần bên dưới đổi thì hiện nút **Vẫn đúng** / **Sửa**.
- MCP `codemap_knowledge_gaps`: thêm loại `note` và `item_doc`.

### Code map: bỏ bước duyệt
- Không còn trang **Chờ duyệt**, nút **Duyệt** hay ô "Duyệt luôn". AI hay người ghi vào (tài liệu luồng, quy tắc, liên kết)
  đều **được dùng ngay**, ghi rõ **AI viết** / **Người viết** (liên kết: "AI thêm"). Phần người đã sửa AI vẫn không viết đè.
- Cờ **Code đã đổi** hiện ngay trên quy tắc và từng phần tài liệu luồng khi code đổi sau lần lưu; gỡ bằng **Sửa** hoặc **Vẫn đúng**.
- Dữ liệu cũ đang chờ duyệt (quy tắc nháp, liên kết AI đề xuất) chuyển sang đang dùng ở lần mở đầu tiên.
- MCP: tool ghi giữ tên cũ (`codemap_propose_*`) nhưng ghi thẳng, kết quả trả về nhắc agent trích là "AI viết".

### Code map: gõ tên gần đúng vẫn ra node, liên kết không mất khi extract lại
- Mỗi node có **địa chỉ** đọc được: `hệ thống › loại › tên đầy đủ` (vd `order-api › method › Shop.Data.OrderRepository.Save`,
  `DB1 › procedure › PKG_ORDER.CREATE_ORDER`). Không chứa file, dòng hay project; chỉ thêm tham số khi có overload.
- Một bộ tìm dùng chung cho file nhập từ AI và tool MCP ghi quy tắc: nhận id, địa chỉ, `loại: tên`,
  tên đầy đủ, phần cuối tên (`OrderRepository.Save`), tên tiếng Nhật / Anh, và tên **sai 1–2 ký tự**. Tên trùng nhiều node:
  node cùng luồng thắng, nếu không thì trả danh sách ứng viên (kèm địa chỉ) và không ghi gì.
- Liên kết tay / AI thêm nhớ địa chỉ hai đầu. Extract lại mà id node đổi: tự gắn lại theo tên, hiện **Code đã đổi** với
  nút **Vẫn đúng**; không tìm được thì gợi ý node tên gần giống để chọn lại. Liên kết cũ dùng tên đã lưu (`method: Class.method`).

### Code map: AI viết tên và tổng quan tính năng
- File **Xuất cho AI** có thêm khối `feature` (tên, tổng quan). AI viết nó sau cùng, tổng hợp từ các luồng; nhập vào
  là dùng ngay, hiện nhãn **AI viết** ở đầu trang tính năng. Trước đây trang hứa "để AI viết" nhưng phần nhập bỏ qua.
- Tổng quan bạn đã **Sửa** bị khoá: AI chỉ đọc, không viết đè.
- MCP: `codemap_get_item_doc` (đọc) và `codemap_propose_item_doc` (ghi, cần knowledge token).
- Bỏ vài chữ "đã duyệt" còn sót trong prompt MCP.

### Code map: bỏ phần dành cho nhiều người
Viewer Hub chạy trên máy cá nhân, không có ai khác để trả lời hay chốt, nên các phần sau được bỏ:
- **Câu hỏi**: mục "Câu hỏi AI chưa chắc" của tài liệu luồng, tab Câu hỏi ở trang Quy tắc, số câu hỏi trên cây và trang
  tính năng. File xuất cho AI không còn trường `questions`; chỗ AI chưa chắc ghi thành quy tắc `warn`.
- **Quyết định**: tab Quyết định (chốt / từ chối) ở trang Quy tắc. Trang **Quy tắc** giờ chỉ có quy tắc nghiệp vụ.
- **Ô "Tên của bạn"** trên thanh Code map. Nhãn **AI viết** / **Người viết** vẫn giữ.
- **Chia sẻ knowledge** (xuất / nhập `.codemap-knowledge.json`) ở trang KB.
- MCP: bỏ `codemap_propose_question`, `codemap_propose_decision`, `codemap_propose_answer`; `codemap_knowledge_gaps`
  không còn `kind=question`. Agent được dặn nói thẳng với người dùng chỗ chưa chắc hoặc tài liệu lệch code.
- Dữ liệu cũ (câu hỏi, quyết định đã lưu) vẫn nằm nguyên trong file knowledge, chỉ không hiện nữa.

### Code map: trang luồng gọn lại, ERD nằm trong sơ đồ
- Thanh trên sơ đồ chỉ còn một nút **Xem**: **Luồng chạy** · **Dữ liệu** · **Phụ thuộc**. Mức chi tiết và cách vẽ
  (Graph / Swimlane) là tuỳ chọn ở bên phải, chỉ hiện khi dùng được.
- **Dữ liệu** vẽ ERD các bảng luồng đọc / ghi ngay trong khung sơ đồ, mỗi bảng gắn nhãn C/R/U/D. Mục **Dữ liệu** của tài
  liệu chỉ còn danh sách bảng gọn; bấm một bảng để xem nó trong ERD. Bảng CRUD to trong tài liệu được bỏ.
- Mục lục tài liệu gọn: Tổng quan · Các bước · Dữ liệu · Ngoại lệ, có số bước / số bảng.
- Thanh trên cùng và khung chi tiết bảng / cột không còn nút ERD. ERD cả cơ sở dữ liệu là addon **ERD** (addon mặc định),
  mở từ menu hoặc nút **Mở trong ERD** của view Dữ liệu.
- Chữ dài không còn làm vỡ trang: tên file, đường dẫn, tên bảng không có khoảng trắng tự xuống dòng (tiêu đề, bước, quy
  tắc, bằng chứng, tổng quan). Thanh trên sơ đồ hẹp thì ẩn số node rồi chỉ còn icon, không bị cắt.

### Addon mặc định
- **Sơ đồ** 0.5.0: AI vẽ / sửa sơ đồ được lưu ngay thành bản mới gắn nhãn AI (không còn hàng chờ duyệt; Lịch sử khôi phục bản cũ).
- Thêm **ERD** 1.0.0.
- Bỏ **Box Workspace** (`box-workspace`) khỏi addon mặc định: bản cài mới không còn tự có. Máy đã cài vẫn giữ
  (gỡ trên trang Cài đặt nếu không dùng); vẫn cài tay được bằng cách upload zip.

### Addon Node dùng `node` của máy, không bật cửa sổ console
- Addon Node luôn chạy bằng `node` có sẵn trên máy (PATH). Gói addon kèm `app/node/node.exe` giờ bị từ chối lúc cài
  (máy dev luôn có Node; gói nhẹ hơn ~80 MB). Chưa có Node thì trang Cài đặt báo cần cài Node.js.
- Trên Windows, mọi tiến trình Hub chạy (addon, lệnh `init` / `status` của addon, `tasklist` cho trang Giám sát) không
  mở cửa sổ console. Daemon (MCP Bridge) không còn cửa sổ console thu nhỏ: output vào log của Hub, dừng / chạy lại trên
  trang của nó.

### GitHub Copilot trong Cài đặt, tự đồng bộ skills
- Khối **Dùng với GitHub Copilot** chuyển từ trang Hướng dẫn sang **Cài đặt**, giữ hai nút **Sao chép cấu hình MCP** và
  **Tải skills (.zip)**.
- Thêm danh sách **folder project** (tối đa 20): mỗi lần Viewer Hub khởi động và khi lưu danh sách, skills được ghi vào
  `.github/skills/` của từng folder (thêm, cập nhật, xoá skill không còn dùng). Chỉ đụng tới skill Viewer Hub tạo
  (`SKILL.md` có dòng `viewer-hub: tự sinh`); skill người dùng tự viết, kể cả trùng tên, giữ nguyên. Mỗi folder hiện
  kết quả lần đồng bộ gần nhất hoặc lỗi; có nút **Đồng bộ ngay**.
- API: `GET/PUT /api/settings/copilot`.

## [v0.3.2] - 2026-11-19

### 🤝 Dùng Viewer Hub với GitHub Copilot không cần MCP Bridge
- Trang **Hướng dẫn** có hai nút: **Sao chép cấu hình MCP** (khối `servers` cho `.vscode/mcp.json`, địa chỉ lấy theo cổng
  đang chạy) và **Tải skills (.zip)** (mỗi MCP một `SKILL.md`, giải nén vào `.github/skills/`). Skill chỉ giữ mô tả ngắn
  trong ngữ cảnh, phần tool lấy từ `### Tool cho AI` của `GUIDE.md` nên module / addon mới tự có skill.
- API: `GET /api/mcp/config` và `GET /api/mcp/skills.zip`.

## [v0.3.0] - 2026-11-18

### 🧱 Cấu trúc gói addon mới (đổi hợp đồng, `schemaVersion` 3)
- Gói addon giờ có **một cấu trúc cho mọi runtime**: gốc chỉ có `addon.json`, `GUIDE.md`, `signature.json` và các thư mục
  `ui/`, `app/`, `assets/`, `legal/`. Chương trình và mọi thứ nó cần (code Python + `lib/`, bundle Node, các DLL .NET,
  `node/node.exe`) nằm trong `app/`; `entry` là tên một file trong đó, Hub chạy với thư mục làm việc là `app/`. Hub từ chối
  gói có thứ khác ở gốc. Dữ liệu chỉ đọc đi kèm ở `assets/` (`addon.assets`, `VIEWER_HUB_ADDON_ASSETS`), giấy phép ở `legal/`.
- **Project nguồn** tách khỏi gói: `addon/` (addon.json, GUIDE.md), `src/`, `web/`, `test/`; `npm run build` lắp gói vào
  `build/<id>/`, không ghi vào nguồn; `dist/` giữ zip. SDK (`build.mjs`, mẫu `simple` / `daemon` / `external`, `AGENTS.md`,
  `README.md`) viết lại theo cấu trúc này. Zip tay cả thư mục project không còn cài được: dùng `npm run zip`.
- **Không đọc cấu trúc cũ** (`schemaVersion` 1 / 2). Addon mặc định được cài lại tự động khi mở Viewer Hub; addon cài tay
  phải build lại bằng SDK mới. `viewer-hub addon pack` giờ đóng một gói đã build (`build/<id>`), bỏ `--include`.
- Cả 6 addon mặc định đã chuyển sang cấu trúc mới (svn, diagram, api-specs, box-workspace, db-query, mcp-bridge) và ký lại.

### ⚙️ Cài đặt addon
- Kiểu cài đặt mới `records`: mỗi dòng nhiều ô (chọn, nhập, chỉ hiện ô theo giá trị ô khác, ô chiếm cả hàng). DB Query dùng nó
  để nhập kết nối Oracle theo từng ô (Service name / SID / TNS, host, port, giao thức, user, schema); dòng cũ vẫn chạy.
- Hộp **Cài đặt** của addon có thể là hướng dẫn từng bước (`setup`, `setupIntro`, `setupCheck` trong trang addon): trang đầu
  là form, lưu xong chạy kiểm tra, rồi qua các bước. MCP Bridge dùng nó để dẫn nối Copilot Studio qua Box.
- Sửa: bỏ viền xanh lệch khi mở Cài đặt cho một ô (con trỏ nhảy thẳng vào ô); tiêu đề bảng không còn bị ô chọn trong bảng vẽ đè.

### 🔌 MCP
- `GET /api/mcp?detail=1` trả cả mô tả và schema của từng tool (Hub hỏi `tools/list` của từng server).

### 🌉 MCP Bridge 0.4.13
- Chỉ còn Box + Copilot Studio (bỏ Agent Flow / Power Automate). Hướng dẫn cho agent điền sẵn thư mục Box và token; thêm
  bản **skill** (SKILL.md) cho agent đã có hướng dẫn riêng. Token xem và tạo lại ngay trên Hub.

## [v0.2.7] - 2026-11-18

### 🧩 DB Query chạy bằng .NET (1.0.0)
- **DB Query** (addon mặc định, premium) giờ dùng driver **.NET** (`Oracle.ManagedDataAccess.Core`) thay cho bản Node. Đăng nhập
  được cả tài khoản Oracle cũ (kiểu mật khẩu 10G) mà chế độ Thin của Node từ chối với lỗi `NJS-116` / `NJS-138`.
- **Giữ nguyên với người dùng cũ**: cùng id, cùng khoá premium (mã mở khoá đã cấp vẫn dùng được, không cần cấp lại), cùng ô
  cấu hình kết nối (kết nối đã lưu còn nguyên), cùng lệnh MCP `db`. Mật khẩu vẫn chỉ giữ trong bộ nhớ.
- **Cần .NET 8 trở lên** (lệnh `dotnet`) trên máy; chưa có thì trang addon báo "Cần .NET 8+" và addon không chạy.
- **Chỉ còn một tool `db_query`** (SELECT, tối đa 50 dòng). Các tool `db_tables`, `db_describe`, `db_connections` đã bỏ:
  muốn xem cấu trúc bảng, AI tự truy vấn `all_tables`, `all_tab_columns`, `all_constraints`…

---

## [v0.2.6] - 2026-11-18

### 🧩 Addon .NET
- **Addon chạy trên .NET** (`"runtime": "dotnet"`, `lifecycle: managed`): Hub chạy `dotnet <entry>.dll serve --port N` bằng .NET 8+
  có sẵn trên máy, cùng hợp đồng HTTP như addon Node (token, `/health`, `/mcp`, `/shutdown`, tự thoát khi Hub tắt). Máy
  chưa có .NET thì trang addon báo "Cần .NET 8+". Dùng khi cần thư viện chỉ có cho .NET, ví dụ driver Oracle hỗ trợ cả
  tài khoản kiểu mật khẩu cũ mà chế độ Thin của Node từ chối (`NJS-116`).
- **Quy tắc quét**: addon `dotnet` được kèm `.dll`, nhưng chỉ assembly .NET (kiểm CLR header); `.exe`, DLL native, `.so`,
  `.node` vẫn bị từ chối, và `.dll` trong addon Python / Node vẫn bị từ chối. Lúc cài, admin thấy ghi chú rằng Hub không
  đọc được code đã biên dịch. `npm run check` của SDK quét giống hệt. Hướng dẫn: `kit/AGENTS.md` §4.4.

### 🔌 API
- **`GET /api/mcp`**: danh sách mọi server MCP của Hub (module có sẵn và addon) cho công cụ bên ngoài: địa chỉ, scope, tên
  tool. Đọc từ khai báo nên không khởi động addon nào.

---

## [v0.2.5] - 2026-11-18

### 🐛 F-Search không còn treo khi tìm
- **Highlight nhanh hơn nhiều với tài liệu dài**: văn bản ASCII 5 MB 1,8 s → 0,01 s, có tiếng Việt 1,8 s → 0,12 s mỗi trường.
  Chỉ quét 1 triệu ký tự đầu của mỗi trường để tìm chỗ tô sáng.
- **Từ khoá khớp hơn 20.000 tài liệu** không tính độ liên quan (bm25) nữa mà xếp theo mới nhất, kèm thông báo: 2,7 s → 1,1 s.
- **Tìm quá 8 giây thì dừng** và báo cách thu hẹp, thay vì quay mãi.
- **Giao diện huỷ lần tìm cũ** khi bạn tìm lại hoặc đổi bộ lọc, nên các lần tìm chậm không dồn lên nhau.

---

## [v0.2.4] - 2026-11-18

### ⚡ Hiệu năng với dữ liệu lớn
- **F-Search** (đo trên 200.000 tài liệu): tìm kiếm 9,9 s → 0,5 s; gom nhóm 12 s → 1,5 s; "Xem thêm" trong nhóm 3,4 s → 0,6 s.
  Lọc, facet, sắp xếp và gom nhóm đọc qua index thay vì đọc cả tài liệu.
- **F-Search gom nhóm**: đếm đủ mọi kết quả (trước chỉ đếm trong 10.000 kết quả đầu); nhóm "(không có)" gồm cả giá trị rỗng
  và "Xem thêm" của nhóm này chạy đúng; "Xem thêm" giữ đúng thứ tự của trang kết quả.
- **Pack F-Search mới** có thêm index cho tên file, đường dẫn, tác giả: sắp xếp theo tên 4,6 s → 0,5 s, gom theo đường
  dẫn 3,9 s → 1,3 s. Pack đóng trước đây vẫn dùng được (hai thao tác này chậm như cũ tới khi đóng lại pack).
- **Code map**: cây menu bên trái chỉ vẽ phần đang thấy (46.000 mục: "Mở tất cả" 3,4 s → 0,04 s, chọn mục 0,55 s → 0,05 s).
  Bỏ hai API `business/tree/roots` và `tree/children` không dùng (bản 0.2.2 ghi "Lazy Loading" nhưng giao diện chưa từng gọi).

### 🧩 Addon
- **Lúc cài và `npm run check` từ chối trang addon vẽ lại phần đầu của Hub**: gọi `/api/addons/…`, tự đọc / ghi cấu hình qua
  `/settings` / `/config`, nút "Cài đặt" / "Nhật ký" / "Khởi động lại", banner tự làm về cấu hình. Cấu hình chỉ qua
  `settings` (+ `required`) và `useAddon().openSettings()`.
- **SDK** (`AGENTS.md`, mẫu): ghi quy tắc này ngay đầu file kèm ví dụ đúng / sai, để AI viết addon làm theo.

---

## [v0.2.3] - 2026-11-17

### ⚡ Tối ưu hoá Đóng gói & Hiệu năng Giải nén trên Windows
- **Loại bỏ hơn 13.600 file rác từ dependencies (`app/vendor`)**:
  - Dọn dẹp hơn 12.700 file icon SVG không sử dụng trong `mkdocs-material` (`.icons/fontawesome`, `.icons/octicons`, `.icons/simple` và các icon hiếm trong `.icons/material`).
  - Dọn dẹp hơn 950 file locale không sử dụng trong `babel/locale-data`.
  - Tổng số file trong bản phát hành Windows giảm từ **18.393 files xuống 4.707 files (giảm ~74.4%)**, dung lượng file zip giảm ~38.5% (từ 46.5 MB còn ~30 MB).
  - Tăng tốc độ giải nén trên Windows NTFS và giảm thiểu nghẽn I/O do Windows Defender quét real-time (từ 3–5 phút xuống chỉ còn vài giây).
- **Ký lại toàn bộ các Addon mặc định** bằng khóa tác giả (`api-specs`, `box-workspace`, `db-query`, `diagram`, `mcp-bridge`, `svn`).
- **Giao diện Docs**: Tối ưu kích thước compact cho `md-switch`, hoàn thiện các dialog xem chi tiết và upload nguồn markdown.

---

## [v0.2.2] - 2026-11-17

### 🧪 Tính năng mới nổi bật
- **MCP Interactive Tester / Playground** (`/monitor` tab *Thử nghiệm MCP*):
  - Môi trường thử nghiệm trực quan cho mọi server MCP (F-Search, CSV, Code Map, Monitor, SVN, Box...).
  - Tự động khám phá công cụ (`tools/list`), hiển thị annotations, schema và tự động tạo mẫu tham số thông minh (**Smart Arguments Generator**).
  - Chạy thử tool trực tiếp trên nền web (`tools/call`), đo đạc độ trễ (latency ms), trạng thái HTTP, kèm log chi tiết phản hồi JSON-RPC.
  - Hỗ trợ nạp tham số mẫu có sẵn và xoá trắng nhanh.
- **Addon Box Workspace (`box-workspace-0.1.0`)**:
  - Addon mặc định mới: xem tệp Copilot Studio từ thư mục đồng bộ Box Drive.
  - Xem trước Markdown, hiển thị cây thư mục phân cấp và mở tệp bằng ứng dụng mặc định hệ thống.
  - Công cụ MCP `box_list_files`, `box_read_file` cho AI Agent.
- **Thông báo quyền hạn Addon thân thiện**:
  - Bảng quyền hạn trực quan: *Chạy tiến trình / Gọi ứng dụng ngoài*, *Kết nối mạng*, *Xử lý Base64*, *Kênh IPC Socket*...
  - Chi tiết vị trí dòng code quét được được thu gọn cho Admin/Dev.

### 🎨 Cải tiến Giao diện & Trải nghiệm (UI/UX)
- **F-Search**:
  - Danh sách kết quả dạng thẻ bo góc Material 3, tăng khoảng cách dòng và thẻ snippet dễ đọc.
  - Đại tu màu highlight `<mark>`: chuyển sang màu hổ phách tương phản cao ở Dark Mode.
  - Biểu tượng spinner loading trên `SearchBar` và thanh tiến trình `vh-grid-loading-bar`.
  - Tự động cuộn mượt lên đầu trang khi lọc nâng cao, chuyển trang hoặc tìm kiếm mới.
- **Thanh điều hướng**:
  - Hỗ trợ cuộn độc lập cho menu bên trái khi danh sách dài.
  - Đưa mục **Giám sát** (`monitor`) xuống chân trang, phía trên *Hướng dẫn sử dụng*.
- **Favicon**: Bổ sung `favicon.svg` nhận diện thương hiệu Material 3.

### ⚡ Sửa lỗi & Tối ưu Hiệu năng
- **Upload File lớn & Lỗi 413**: Sửa `max_request_body_size = 10 GB` của Waitress (giá trị 0 trước đây gây lỗi 413); hỗ trợ import trực tiếp từ đường dẫn đĩa cho file `.sapack` lớn.
- **Code Map**: cây tính năng không tự mở các nhánh con khi cây lớn (hơn 50 mục).
- **Addon Bundler**: Sửa cấu hình Rollup/Vite trong SDK build xuất đúng `ui/ui.css` cho addon có stylesheet riêng.
- **Cập nhật Addons**: `mcp-bridge` 0.4.2 và `api-specs` 0.3.1.

---

## [v0.2.1] - 2026-11-16
- Minify addon Node bundles; db-query 0.4.1.

## [v0.2.0] - 2026-11-15
- Addons chia sẻ dữ liệu qua hợp đồng `exports` / `uses`.
