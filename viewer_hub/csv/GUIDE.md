## CSV

Tra cứu file CSV bằng bộ lọc theo cột. File bạn tải lên chỉ nằm trên máy bạn.

Bộ dữ liệu có nhãn [icon:inventory_2] **Data pack** do admin cung cấp: xem, tìm, lọc, xuất được nhưng **chỉ đọc** (không sửa cột, không xoá). Admin gửi bản mới thì nó tự cập nhật; không ảnh hưởng file của bạn.

### Thêm file
- Kéo thả file `.csv` vào ô lớn, hoặc nút [icon:upload_file] **Tải CSV lên** ở góc phải đầu trang. Chọn được nhiều file một lúc. Tiêu đề cột, bảng mã (UTF-8, Shift_JIS…) và dấu phân cách (`,` `;` tab `|`) tự nhận.
- Tải xong, hộp thoại **Mô tả file vừa tải** mở ra cho từng file:
  - **Tên**: tên hiện trong app.
  - **Mô tả**: file là gì, mỗi dòng là gì (ví dụ "Từ điển cột của DB đơn hàng — mỗi dòng là một cột của một bảng"). Người xem thấy trên trang CSV; AI đọc để chọn đúng file.
  - **Cho AI đọc**: mặc định tắt. Chỉ bật cho file không có dữ liệu nhạy cảm. File có nhãn [icon:smart_toy] **AI** là AI agent đọc được.
  - Bấm **Để sau** nếu chưa muốn điền.
- Sửa lại bất cứ lúc nào: danh sách CSV ([icon:folder_managed]) → nút **Sửa** trên thẻ của file. File trong data pack do admin mô tả nên chỉ có nút **Mở**.

### Tra cứu
- **Nguồn dữ liệu**: chọn file cần tra. Lần sau mở CSV sẽ vào thẳng file xem gần nhất.
- Mỗi dòng **bộ lọc**: *Cột* · *Toán tử* (`IN` = chứa, `==` = bằng đúng; không phân biệt hoa thường) · *Giá trị*. Nút [icon:close] xoá dòng lọc.
- **Thêm bộ lọc** để lọc theo nhiều cột; dòng kết quả phải thoả **tất cả** bộ lọc.
- Bấm **Tìm kiếm** (hoặc Enter trong ô giá trị). Hiện tối đa 500 dòng; cần hết thì dùng [icon:download] **Xuất CSV**.

### Nút ở góc phải đầu trang
| Nút | Làm gì |
|---|---|
| [icon:upload_file] | Tải thêm file CSV |
| [icon:folder_managed] | Danh sách các bộ dữ liệu |
| [icon:download] | Xuất kết quả đang lọc ra file CSV |
| [icon:view_column] | Cấu hình cột: mô tả file, Cho AI đọc, tên hiển thị và mô tả từng cột, ẩn/hiện, cột có sẵn dòng lọc khi mở trang, toán tử mặc định |
| [icon:delete] | Xoá bộ dữ liệu (không hoàn tác được) |

### Tool cho AI
| Tool | AI dùng để |
|---|---|
| `csv_list` | Xem các file được phép đọc: tên, **mô tả**, số dòng, từng cột (kiểu, mô tả, vài giá trị mẫu). Không trả dữ liệu dòng |
| `csv_search` | Lấy dòng của một file: bộ lọc theo cột (`IN` = chứa, `==` = bằng; tất cả phải khớp), chuỗi tìm chung, chỉ các cột cần, tối đa 500 dòng |

AI chọn file CSV dựa vào **mô tả** bạn ghi lúc tải lên, nên mô tả càng rõ (file là gì, mỗi dòng là gì) AI càng chọn đúng.
