## F-Search

Tìm trong toàn bộ tài liệu, code và ảnh scan đã được đưa vào.

1. Bấm **F-Search**, gõ từ khoá, Enter.
2. Cách gõ:
   | Bạn gõ | Nghĩa |
   |---|---|
   | `đăng nhập` hoặc `dang nhap` | tìm được cả khi không gõ dấu |
   | `auth` | cả các từ bắt đầu bằng `auth` (authentication, author…); không có thì tìm cả chuỗi nằm giữa từ |
   | `"đăng nhập hệ thống"` | đúng cụm từ này |
   | `token -refresh` | có `token`, không có `refresh` |
   | `ログイン` | tiếng Nhật (từ 3 ký tự trở lên cho kết quả tốt nhất) |
3. Cạnh ô tìm: **Repository**, **Loại file**, **Sắp xếp** (đổi là tìm lại ngay). Nút **Nâng cao**: ngôn ngữ, khoảng ngày; **nhóm** kết quả theo file/repository; **OR** (có từ bất kỳ) hay **AND** (có đủ các từ); **cụm từ chính xác**; **từng từ chính xác** (không tìm theo đầu từ); **khoảng cách từ** (các từ đứng gần nhau trong N từ).
4. Mỗi kết quả: tên, đường dẫn, đoạn trích có **từ khoá được tô màu**, nhãn OCR nếu đến từ ảnh scan. Nút:
   - [icon:content_copy] **Sao chép đường dẫn** file;
   - [icon:open_in_new] **Mở trong repository** (nếu có link);
   - [icon:folder_open] **Mở thư mục chứa file**: chỉ hiện khi bạn khai báo *Thư mục file gốc* trong **Nâng cao** (thư mục trên máy bạn có bản copy các file).

### Tool cho AI
| Tool | AI dùng để |
|---|---|
| `search_documents` | Tìm tài liệu / code / chữ OCR; mỗi kết quả một dòng thông tin + một đoạn trích ngắn. Lọc theo repository, loại file, ngôn ngữ, ngày |
| `read_document` | Đọc một tài liệu theo id: chỉ các đoạn quanh từ khoá (gọn nhất), hoặc từng phần của toàn văn |
