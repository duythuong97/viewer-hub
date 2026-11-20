## Code map

Code map là "bản đồ" của hệ thống: các **màn hình**, **API**, **code**, **procedure**, **bảng**, **batch/job** và cách chúng nối với nhau. Dùng khi cần trả lời: *màn hình này lấy dữ liệu ở đâu?*, *sửa bảng này thì ảnh hưởng tới đâu?*, *job này ghi vào bảng nào?*

### Tìm và xem
- **Cây chức năng** (bên trái): hệ thống → nhóm → màn hình/API/job. Bấm để mở.
- **Ô tìm kiếm**: tên màn hình, API (`GET /api/orders`), tên bảng, procedure, hoặc thuật ngữ nghiệp vụ tiếng Việt / Nhật / Anh.
- Mục nào có **tên logic** (ví dụ 注文 / Order) thì hiện kèm tên kỹ thuật.

### Trang luồng
Đi theo một màn hình, API hoặc job tới dữ liệu cuối cùng.
- Bên trái là tài liệu, bên phải là sơ đồ; chọn **Luồng chạy**, **Dữ liệu** (ERD) hay **Phụ thuộc** ở thanh trên sơ đồ (mục *Ba cách xem một luồng* bên dưới).
- **Cách vẽ** **Graph**: sơ đồ các bước. **Swimlane**: cùng các bước nhưng chia làn theo hệ thống.
- Bấm một ô để xem **chi tiết** bên phải: nó là gì, gọi tới đâu, **bằng chứng** (file và dòng code). Nút **Xem file nguồn** chỉ có khi dữ liệu kèm source.
- Màu đường nối cho biết kiểu quan hệ: gọi, đọc bảng, ghi bảng…

### Thêm liên kết còn thiếu
Có lời gọi mà code map không thấy (gọi qua tên động, job chạy theo cấu hình…): bấm một ô trên graph → **Thêm liên kết** → chọn chiều, loại cạnh (gọi, đọc/ghi bảng…), tìm node ở đầu kia và ghi lý do. Liên kết hiện bằng **nét đứt** với chữ "tay"; luồng, file xuất cho AI và AI agent (MCP: trace, impact) đều đi qua nó. Xoá trong thẻ của ô đó.

Sau khi extract lại, liên kết **tự gắn lại** vào node mới nếu code chỉ dời file / dời dòng / đổi project: liên kết nhớ **địa chỉ** của node (`hệ thống › loại › tên đầy đủ`, vd `order-api › method › Shop.Data.OrderRepository.Save`). Liên kết được gắn lại hiện [icon:sync_problem] **Code đã đổi, đã gắn lại theo tên** kèm tên cũ; bấm **Vẫn đúng** nếu không sai. Node không tìm lại được thì hiện [icon:link_off] **Node … không còn trong graph** kèm các node tên gần giống: bấm một node để gắn lại, hoặc **Xoá**.

### Viết tài liệu bằng AI
Ở trang tính năng hoặc trang luồng: **Xuất cho AI** → đưa file cho AI (không cần viết thêm câu lệnh) → **Nhập kết quả AI**. File có sẵn **thứ tự gọi** của từng luồng nên AI tự chia luồng thành các bước nghiệp vụ; luồng có bước bạn đã sửa thì giữ nguyên cách chia, và AI không viết đè phần bạn đã sửa. Không có bước duyệt: nội dung nhập vào **được dùng ngay**, ghi rõ **AI viết** hay **Người viết**. Liên kết còn thiếu AI tìm được cũng được thêm ngay (nét đứt, chữ "AI thêm"); thấy sai thì **Xoá**.

Cùng file đó AI viết luôn **tên nghiệp vụ và tổng quan của tính năng** (tính năng để làm gì, ai dùng, các luồng chính, bảng chính, không làm gì), sau khi viết xong các luồng. Tổng quan hiện ở đầu trang tính năng với nhãn **AI viết**; bấm **Sửa** để viết lại, từ đó AI không đổi nó nữa.

Khi code đổi sau lần bạn sửa một phần, phần đó hiện **Code đã đổi**: đọc lại code rồi **Sửa**, hoặc bấm **Vẫn đúng** nếu nội dung vẫn đúng.

### Trang Kiến thức (KB)
Trạng thái dữ liệu (lấy từ code lúc nào, commit nào), **ghi chú**, **quy tắc nghiệp vụ**, số quy tắc có code đã đổi. Quy tắc lưu là dùng ngay; quy tắc mà code đã đổi từ lúc viết hiện **Code đã đổi · cần xem lại** ở trang **Quy tắc** (bấm **Vẫn đúng** hoặc **Sửa**). Ghi chú bạn thêm được lưu trên máy bạn và **không mất khi admin gửi data pack mới**.

### Ba cách xem một luồng
Mở một luồng: bên trái là **tài liệu** của luồng (mục lục:
Tổng quan · Các bước · Dữ liệu · Ngoại lệ), bên phải là **sơ đồ**. Thanh trên sơ đồ có một nút chọn **Xem**:

1. **Luồng chạy**: các bước chạy theo thứ tự. **Mức chi tiết** (Hệ thống / Ứng dụng / Kỹ thuật) và **Cách vẽ**
   (Graph / Swimlane) nằm ở bên phải thanh.
2. **Dữ liệu**: ERD của các bảng luồng đọc / ghi, nối bằng **khoá ngoại**. Mỗi bảng có nhãn `C` tạo, `R` đọc, `U` sửa,
   `D` xoá (tô màu khi luồng ghi). [icon:key] = khoá chính, [icon:link] = khoá ngoại; bảng con bên trái, bảng được tham
   chiếu bên phải; đầu "chân chim" = phía *nhiều*. **Tên hiển thị** (日本語 / English / Kỹ thuật) nằm bên phải thanh, như các tuỳ chọn của Luồng chạy.
3. **Phụ thuộc**: mọi node luồng gọi tới, kể cả phần đã ẩn ở Luồng chạy.

Mục **Dữ liệu** trong tài liệu liệt kê các bảng luồng chạm tới (bảng được ghi đứng trước, [icon:back_hand] = có liên kết
tay). Bấm một bảng: sơ đồ chuyển sang **Dữ liệu** và đưa bảng đó vào giữa. Dòng *"N bảng khác có khoá ngoại tới các bảng
này"* ở chân sơ đồ là các bảng ngoài luồng nối tới. Tối đa 40 bảng mỗi luồng.

Tất cả lấy từ cạnh đọc / ghi trong code, không cần AI. Thêm hay xoá liên kết tay ở thẻ node thì danh sách và ERD cập nhật
theo. Thấy *"Chưa có dữ liệu khoá ngoại"*: dữ liệu hiện tại chưa có thông tin khoá ngoại, **liên hệ admin**.

**ERD của cả cơ sở dữ liệu** (chọn bảng bất kỳ, cả schema, xuất Mermaid / DBML) là addon **ERD**. Code map chỉ có ERD trong view **Dữ liệu** của luồng đang mở; khi addon đã được cài, nút [icon:schema] **Mở trong ERD** ở đó mở các bảng này (và bảng nối tới) trong addon. Chưa có addon thì cài ở **Cài đặt → Addon** (liên hệ admin để lấy file).

### Tool cho AI
| Tool | AI dùng để |
|---|---|
| `codemap_search` | Tìm màn hình, API, method, procedure, bảng, job, thuật ngữ nghiệp vụ liên quan tới một câu hỏi (Việt / Nhật / Anh / tên kỹ thuật), kèm vị trí `file:dòng` và tài liệu nghiệp vụ (ghi rõ người hay AI viết) |
| `codemap_trace_flow` | Đi theo một màn hình, thao tác, API hoặc job qua mọi hệ thống tới bảng nó đọc / ghi, kèm tài liệu luồng |
| `codemap_impact` | Phân tích ảnh hưởng khi sửa một bảng, API, procedure, method, job (hoặc danh sách file): ai gọi, màn hình / job nào, ai đọc / ghi, gom theo hệ thống, nêu rõ chỗ chưa chắc |
| `codemap_erd` | (Sắp bỏ: dùng `erd_diagram` của addon ERD) Sơ đồ quan hệ bảng theo khoá ngoại: cột, kiểu, khoá, tên logic, `ON DELETE`; xuất Mermaid / DBML |
| `codemap_file_context` | Một file nguồn (hoặc một đoạn dòng) khai báo gì, chạm tới bảng / API nào, job nào chạy nó |
| `codemap_current_behavior` | Hệ thống đang làm gì cho một chủ đề nghiệp vụ: sự thật từ code + quy tắc, tài liệu luồng (dùng trước khi viết / soát requirement) |
| `codemap_check_terms` | Soát một đoạn requirement: thuật ngữ nghiệp vụ, tên kỹ thuật không có trong hệ thống, từ ngữ mơ hồ |
| `codemap_get_flow_doc` | Lấy khung tài liệu của một luồng (các bước theo hệ thống, node của từng bước, chữ đã có, phần người đã sửa thì khoá) để viết tài liệu luồng |
| `codemap_get_item_doc` | Lấy tên, tổng quan hiện có của một tính năng (khoá nếu bạn đã viết) và tóm tắt các luồng của nó, để viết tổng quan tính năng |
| `codemap_status` | Dữ liệu được lấy lúc nào, từ commit nào; chất lượng dữ liệu |
| `codemap_knowledge_gaps` | Danh sách việc còn thiếu để AI đọc tài liệu viết tiếp: luồng chưa có tài liệu hoặc phần đã viết nhưng code đã đổi, lời gọi / đọc / ghi mà code map không lần ra (kèm node có thể là đích) |
| `codemap_resolve` | Đổi tên trong tài liệu (màn hình, API, bảng, job, tên tiếng Nhật / Anh / Việt) ra đúng node: một node, nhiều ứng viên, hoặc không có |

Liên kết bạn thêm tay (ở trên) được tính trong `codemap_trace_flow` và `codemap_impact`.

Khi AI được cấp **knowledge token**, nó còn có các tool ghi: tài liệu luồng, **tên và tổng quan tính năng**, quy tắc, **liên kết** giữa hai node và **ghi chú** trên node. AI làm việc từ tài liệu nghiệp vụ (spec, 画面設計書, DB設計書) phải ghi **trích dẫn**: tên tài liệu, mục, có thể kèm link và một câu trích. Những gì AI ghi được dùng ngay và hiện kèm nhãn **AI viết** cùng trích dẫn; bạn sửa hoặc xoá được như mục mình viết. AI không bao giờ sửa phần bạn đã viết: liên kết bạn thêm, ghi chú của bạn giữ nguyên.
