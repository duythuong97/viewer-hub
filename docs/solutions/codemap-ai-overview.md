# Code map: AI viết cả phần tổng quan, không chỉ tài liệu luồng

Ngày: 2026-11-20 · Trạng thái: bước 1 đã làm (tên + tổng quan tính năng, file và MCP); bước 2–4 là đề xuất

## 1. Hiện trạng (điều tra từ code)

AI hiện chỉ viết được **tài liệu luồng** và **liên kết còn thiếu**:

| Đường vào | AI viết gì | Ở đâu |
|---|---|---|
| Xuất / nhập file (trang tính năng) | Mỗi luồng: tên, tóm tắt, bước (node, text, rule), ngoại lệ; `links` | `business/ai_exchange.py` (`export_pack`, `apply_import`, `_merge_flow`) |
| MCP | `codemap_propose_flow_doc`, `propose_rule`, `propose_link`, `propose_note` | `mcp/write_tools.py`, `mcp/doc_tools.py` |

Những chỗ còn trống:

1. **Tên và mô tả tính năng.** `export_pack` gửi `feature.description` cho AI làm *ngữ cảnh*, nhưng `apply_import` không
   bao giờ ghi lại vào `kn.biz_items`. Trang tính năng lại đang hứa *"Chưa có mô tả… hoặc để AI viết khi xuất tính
   năng"* (`FeaturePage.jsx`): lời hứa này hiện chưa đúng.
2. **Tổng quan menu / nhóm / hệ thống.** `update_item` cho người sửa `name`, `description` của menu, nhưng không có
   đường nào cho AI. Trang đầu Code map và trang menu chỉ có danh sách con.
3. **Ghi chú nghiệp vụ trên node** (`kn.graph_knowledge`): AI ghi được qua `codemap_propose_note`, nhưng **giao diện
   không hiện ở đâu cả** (trang node, thẻ node trong luồng). Bảng, màn hình, API, job vì vậy không có câu "cái này là
   gì cho nghiệp vụ".
4. Cột `kn.biz_items.status` **đã có giá trị `ai`** (`business/common.py`) và `<Status>` đã vẽ nhãn **AI viết** /
   **Người viết** kèm cờ **Code đã đổi** (`common.jsx`), nhưng chưa có gì ghi `status='ai'` vào `biz_items`.

## 2. Hướng giải quyết

Một nguyên tắc: **viết từ dưới lên, mỗi tầng tóm tắt tầng dưới.** Luồng → tính năng → menu → hệ thống. Tầng dưới đọc
code (đắt, đã có); tầng trên chỉ đọc *tóm tắt đã viết* của con (rẻ, vừa một file dù menu có 50 tính năng). Như vậy
mô tả các tầng khớp nhau và người sửa ở tầng dưới thì tầng trên viết lại theo.

Mọi thứ AI viết dùng chung luật đang có: **dùng ngay**, nhãn **AI viết**, phần người đã sửa (`edited`) bị khoá và AI
không viết đè, cờ **Code đã đổi** khi node bên dưới đổi hành vi.

### 2.1. Nội dung AI viết được, theo thứ tự giá trị

| # | Nội dung | Lưu ở | AI đọc gì để viết | Hiện ở |
|---|---|---|---|---|
| A | **Tên + tổng quan tính năng**: làm gì, ai dùng, kết quả, màn hình / API / bảng chính, không bao gồm gì | `biz_items` (`status='ai'`) | Như file luồng hiện tại + tóm tắt các luồng vừa viết | Đầu trang tính năng |
| B | **Tổng quan menu / nhóm / hệ thống** | `biz_items` | Tên + tổng quan các tính năng con, bảng ghi / đọc gom lại, API ra ngoài | Trang menu, trang đầu Code map |
| C | **Ghi chú nghiệp vụ trên node** chính (bảng, màn hình, API, job): ý nghĩa, vòng đời, ai ghi / đọc | `graph_knowledge` (đã có) | Node, CRUD theo luồng, cột, tên ja / en, comment code | Trang node, thẻ node trong luồng, khung chi tiết bảng |
| D | Tên nghiệp vụ cho menu tự sinh từ graph (vd `PKG_ORDER` → "Xử lý đơn hàng") | `biz_items.name` | Như B | Cây bên trái |

### 2.2. Cách AI nhận việc

**File (Xuất cho AI / Nhập kết quả AI), mở rộng chứ không làm đường mới:**

- *Tính năng* (A + C): file hiện có thêm hai khối AI điền:
  ```yaml
  feature:            # mới: tên + tổng quan tính năng
    name: ""
    description: ""   # locked: true nếu người đã sửa
  flows: [...]        # như cũ
  notes:              # mới: ghi chú cho node chính chưa có ghi chú của người
    - node: "table: ORDER_HEADER"
      text: ""
  links: []
  ```
  Hướng dẫn trong `business/common.py` thêm bước cuối: *viết `feature.description` sau khi xong các luồng*.
- *Menu / hệ thống* (B + D): nút **Xuất cho AI** trên trang menu và trang đầu. File chỉ chứa cây con với tên, tổng
  quan đã có (luồng, tính năng), số liệu CRUD gom lại; AI điền `items: [{id, name, description}]`. Không kèm code, nên
  file nhỏ. Tính năng chưa có tổng quan thì file ghi rõ để AI không bịa (và gợi ý xuất tính năng đó trước).

**MCP (agent đọc tài liệu nghiệp vụ hoặc Copilot trong repo):**

| Tool | Loại | Việc |
|---|---|---|
| `codemap_get_item_doc` | đọc | Khung của một tính năng / menu / hệ thống: tổng quan hiện có (khoá hay không), tóm tắt con |
| `codemap_propose_item_doc` | ghi | Ghi `name` / `description` cho một mục; mục người đã sửa không đổi; kèm `citations` |
| `codemap_knowledge_gaps` | đọc (sửa) | Thêm `kind=item_doc` (tính năng / menu chưa có tổng quan, theo thứ tự dưới lên) và `kind=note` (bảng / màn hình / API chính chưa có ghi chú) |

`propose_note` giữ nguyên.

### 2.3. Phát hiện cũ (Code đã đổi)

- Ghi chú node: lưu fingerprint của node như quy tắc (`knowledge.fingerprint_of`).
- Tổng quan tính năng / menu: lưu một **dấu của các con** (hash tên + tóm tắt luồng / tính năng con lúc viết). Con đổi
  (người sửa, AI viết lại, luồng mới) thì tổng quan hiện **Code đã đổi** với nút **Vẫn đúng** / **Sửa**, và lọt vào
  `knowledge_gaps kind=item_doc`. Không đi thẳng vào fingerprint code: tổng quan mô tả các luồng, không mô tả code.

### 2.4. Giao diện

- Trang tính năng / menu: nhãn **AI viết** / **Người viết** cạnh tổng quan (đã có `<Status>`), cờ **Code đã đổi**,
  nút **Xuất cho AI** cho cả menu và trang đầu.
- Trang node và thẻ node trong luồng: khối **Ghi chú nghiệp vụ** (đọc / sửa / xoá, nhãn AI viết, trích dẫn).
- Bảng trong view **Dữ liệu** của luồng: di chuột vào bảng hiện câu đầu của ghi chú.

### 2.5. Dữ liệu

Không cần bảng mới. `biz_items` thêm hai cột qua `storage.ADDED_COLUMNS` (giữ mọi dòng cũ): `children_sig TEXT`,
`citations_json TEXT`. `graph_knowledge` đã có `citations_json`, `created_by`; thêm `fingerprint`.

## 3. Lộ trình

| Bước | Nội dung | Kích thước |
|---|---|---|
| 1 | **A**: file tính năng có khối `feature`, import ghi `biz_items` (`status='ai'`, không đè `edited`); MCP `get_item_doc` / `propose_item_doc` cho tính năng. Sửa luôn lời hứa trên trang tính năng | Nhỏ |
| 2 | **C**: hiện ghi chú node trên trang node / thẻ node (đang ẩn); khối `notes` trong file tính năng; `knowledge_gaps kind=note` | Vừa |
| 3 | **B + D**: xuất / nhập cho menu và trang đầu (dưới lên, chỉ tóm tắt); MCP cho menu / hệ thống | Vừa |
| 4 | Dấu của con + cờ **Code đã đổi** cho tổng quan; fingerprint cho ghi chú | Nhỏ |

Bước 1 dùng lại gần hết cơ chế khoá / nhãn đang có, nên làm trước; bước 2 mở khoá dữ liệu AI đã ghi qua MCP mà người
dùng chưa thấy.

## 4. Không làm

- Không cho AI đổi cấu trúc cây (chuyển tính năng sang menu khác, gộp menu): sai thì khó thấy, sửa tay nhanh hơn.
- Không viết tổng quan tầng trên từ code trực tiếp (bỏ qua tầng dưới): file quá lớn và mô tả các tầng lệch nhau.
- Không có hàng chờ duyệt hay câu hỏi cho người (quyết định 2026-11-20, `codemap-redesign-solution.md` §3.3).
