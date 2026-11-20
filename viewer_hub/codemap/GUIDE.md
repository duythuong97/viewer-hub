## Code map

Code map là "bản đồ" của hệ thống: các **màn hình**, **API**, **code**, **procedure**, **bảng**, **batch/job** và cách chúng nối với nhau. Dùng khi cần trả lời: *màn hình này lấy dữ liệu ở đâu?*, *sửa bảng này thì ảnh hưởng tới đâu?*, *job này ghi vào bảng nào?*

### Tìm và xem
- **Cây chức năng** (bên trái): hệ thống → nhóm → màn hình/API/job. Bấm để mở.
- **Ô tìm kiếm**: tên màn hình, API (`GET /api/orders`), tên bảng, procedure, hoặc thuật ngữ nghiệp vụ tiếng Việt / Nhật / Anh.
- Mục nào có **tên logic** (ví dụ 注文 / Order) thì hiện kèm tên kỹ thuật.

### Trang luồng
Đi theo một màn hình, API hoặc job tới dữ liệu cuối cùng.
- **Graph**: sơ đồ các bước. **Swimlane**: cùng các bước nhưng chia làn theo hệ thống.
- Bấm một ô để xem **chi tiết** bên phải: nó là gì, gọi tới đâu, **bằng chứng** (file và dòng code). Nút **Xem file nguồn** chỉ có khi dữ liệu kèm source.
- Màu đường nối cho biết kiểu quan hệ: gọi, đọc bảng, ghi bảng…

### Thêm liên kết còn thiếu
Có lời gọi mà code map không thấy (gọi qua tên động, job chạy theo cấu hình…): bấm một ô trên graph → **Thêm liên kết** → chọn chiều, loại cạnh (gọi, đọc/ghi bảng…), tìm node ở đầu kia và ghi lý do. Liên kết hiện bằng **nét đứt** với chữ "tay"; luồng, file xuất cho AI và AI agent (MCP: trace, impact) đều đi qua nó. Xoá trong thẻ của ô đó.

Sau khi extract lại, liên kết **tự gắn lại** vào node mới nếu code chỉ dời file / dời dòng / đổi project: liên kết nhớ **địa chỉ** của node (`hệ thống › loại › tên đầy đủ`, vd `order-api › method › Shop.Data.OrderRepository.Save`). Liên kết được gắn lại hiện [icon:sync_problem] **Code đã đổi, đã gắn lại theo tên** kèm tên cũ; bấm **Vẫn đúng** nếu không sai. Node không tìm lại được thì hiện [icon:link_off] **Node … không còn trong graph** kèm các node tên gần giống: bấm một node để gắn lại, hoặc **Xoá**.

### Viết tài liệu luồng bằng AI
Ở trang tính năng hoặc trang luồng: **Xuất cho AI** → đưa file cho AI (không cần viết thêm câu lệnh) → **Nhập kết quả AI**. File có sẵn **thứ tự gọi** của từng luồng nên AI tự chia luồng thành các bước nghiệp vụ; luồng có bước bạn đã sửa thì giữ nguyên cách chia, và AI không viết đè phần bạn đã sửa. Không có bước duyệt: nội dung nhập vào **được dùng ngay**, ghi rõ **AI viết** hay **Người viết**. Liên kết còn thiếu AI tìm được cũng được thêm ngay (nét đứt, chữ "AI thêm"); thấy sai thì **Xoá**.

Khi code đổi sau lần bạn sửa một phần, phần đó hiện **Code đã đổi**: đọc lại code rồi **Sửa**, hoặc bấm **Vẫn đúng** nếu nội dung vẫn đúng.

### Trang Kiến thức (KB)
Trạng thái dữ liệu (lấy từ code lúc nào, commit nào), **ghi chú**, **quy tắc nghiệp vụ**, số câu hỏi chờ trả lời. Quy tắc lưu là dùng ngay; quy tắc mà code đã đổi từ lúc viết hiện **Code đã đổi · cần xem lại** ở trang **Quy tắc** (bấm **Vẫn đúng** hoặc **Sửa**). Ghi chú bạn thêm được lưu trên máy bạn và **không mất khi admin gửi data pack mới**.

**Chia sẻ knowledge cho người khác**: trang KB → **Xuất file knowledge** (file `.codemap-knowledge.json` gồm tài liệu luồng, quy tắc, quyết định, câu hỏi, ghi chú, liên kết tay). Người nhận mở Code map của cùng pack → **Chọn file để nhập** → xem trước mục mới / khác nhau → **Nhập**. Không gì bị xoá; chỗ hai bên khác nhau thì chọn *Lấy bản sửa sau cùng*, *Giữ của tôi* hoặc *Lấy theo file*. Trước khi nhập, knowledge hiện tại được sao lưu tự động.

### ERD: sơ đồ quan hệ bảng
Xem các bảng nối với nhau qua **khoá ngoại**: bảng nào trỏ tới bảng nào, bằng cột nào.

1. Mở: nút **ERD** trên thanh của Code map, hoặc mở một bảng/cột rồi bấm **Xem ERD** trong khung chi tiết.
2. Gõ tên bảng vào ô **Chọn bảng** (tên kỹ thuật như `ORDER_LINE`, hoặc tên logic như 注文明細 / Order Line).
3. Đọc sơ đồ:
   - Mỗi hộp là một bảng: tên, tên logic, danh sách cột với kiểu dữ liệu. [icon:key] = khoá chính, [icon:link] = khoá ngoại.
   - **Bảng con** (có khoá ngoại) bên trái, **bảng được tham chiếu** bên phải. Đường nối đi đúng từ cột này tới cột kia, nhãn `cột → cột` (khoá nhiều cột: `(a, b) → (c, d)`).
   - Đầu "chân chim" = phía *nhiều*, hai gạch = phía *một*. Ghi chú **xoá dây chuyền** = xoá dòng cha sẽ xoá luôn dòng con (`ON DELETE CASCADE`).
4. Bấm vào một bảng để lấy nó làm tâm. **Vừa khung** đưa cả sơ đồ vào màn hình.
5. **Bộ lọc**: xem cả một schema; độ sâu **1 bước** (chỉ bảng nối trực tiếp) hay **2 bước**; tên hiển thị 日本語 / English / tên kỹ thuật; **Chỉ cột khoá** cho sơ đồ gọn. Mỗi sơ đồ tối đa 80 bảng.
6. **Xuất Mermaid** / **Xuất DBML**: xem trước, **Sao chép** hoặc **Tải file**. Mermaid dán được vào tài liệu Markdown (GitLab, GitHub, Confluence…); DBML dán vào dbdiagram.io.

Thấy thông báo *"Chưa có dữ liệu khoá ngoại"*: dữ liệu hiện tại chưa có thông tin khoá ngoại, **liên hệ admin**.

### Tool cho AI
| Tool | AI dùng để |
|---|---|
| `codemap_search` | Tìm màn hình, API, method, procedure, bảng, job, thuật ngữ nghiệp vụ liên quan tới một câu hỏi (Việt / Nhật / Anh / tên kỹ thuật), kèm vị trí `file:dòng` và tài liệu nghiệp vụ (ghi rõ người hay AI viết) |
| `codemap_trace_flow` | Đi theo một màn hình, thao tác, API hoặc job qua mọi hệ thống tới bảng nó đọc / ghi, kèm tài liệu luồng |
| `codemap_impact` | Phân tích ảnh hưởng khi sửa một bảng, API, procedure, method, job (hoặc danh sách file): ai gọi, màn hình / job nào, ai đọc / ghi, gom theo hệ thống, nêu rõ chỗ chưa chắc |
| `codemap_erd` | Sơ đồ quan hệ bảng theo khoá ngoại: cột, kiểu, khoá, tên logic, `ON DELETE`; xuất Mermaid / DBML |
| `codemap_file_context` | Một file nguồn (hoặc một đoạn dòng) khai báo gì, chạm tới bảng / API nào, job nào chạy nó |
| `codemap_current_behavior` | Hệ thống đang làm gì cho một chủ đề nghiệp vụ: sự thật từ code + quy tắc, tài liệu luồng, câu trả lời của người (dùng trước khi viết / soát requirement) |
| `codemap_check_terms` | Soát một đoạn requirement: thuật ngữ nghiệp vụ, tên kỹ thuật không có trong hệ thống, từ ngữ mơ hồ |
| `codemap_get_flow_doc` | Lấy khung tài liệu của một luồng (các bước theo hệ thống, node của từng bước, chữ đã có, phần người đã sửa thì khoá) để viết tài liệu luồng |
| `codemap_status` | Dữ liệu được lấy lúc nào, từ commit nào; chất lượng dữ liệu |
| `codemap_knowledge_gaps` | Danh sách việc còn thiếu để AI đọc tài liệu viết tiếp: luồng chưa có tài liệu hoặc phần đã viết nhưng code đã đổi, lời gọi / đọc / ghi mà code map không lần ra (kèm node có thể là đích), câu hỏi đang mở |
| `codemap_resolve` | Đổi tên trong tài liệu (màn hình, API, bảng, job, tên tiếng Nhật / Anh / Việt) ra đúng node: một node, nhiều ứng viên, hoặc không có |

Liên kết bạn thêm tay (ở trên) được tính trong `codemap_trace_flow` và `codemap_impact`.

Khi AI được cấp **knowledge token**, nó còn có các tool ghi: tài liệu luồng, quy tắc, câu hỏi, quyết định, **liên kết** giữa hai node, **ghi chú** trên node và **câu trả lời** cho câu hỏi đang mở. AI làm việc từ tài liệu nghiệp vụ (spec, 画面設計書, DB設計書) phải ghi **trích dẫn**: tên tài liệu, mục, có thể kèm link và một câu trích. Những gì AI ghi được dùng ngay và hiện kèm nhãn **AI viết** cùng trích dẫn; bạn sửa hoặc xoá được như mục mình viết. AI không bao giờ sửa phần bạn đã viết: liên kết bạn thêm, ghi chú, câu trả lời của bạn giữ nguyên.
