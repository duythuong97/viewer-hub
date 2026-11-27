## Addon

Addon là tính năng thêm do admin gửi cho bạn dưới dạng file `.zip`. Cài xong, addon hiện thành một mục mới trên
menu và có phần hướng dẫn riêng ở trang này.

- **Cài**: **Cài đặt → Addon → Cài addon (.zip)**, chọn file admin gửi. Cài bản mới hơn sẽ thay bản cũ, dữ liệu của addon được giữ.
- **Bật / tắt**: công tắc cạnh addon trong **Cài đặt → Addon**. Addon tắt không còn trên menu, trang hướng dẫn và
  MCP cho AI, tiến trình của nó dừng; addon vẫn cài, cài đặt và dữ liệu giữ nguyên. Bật lại là dùng tiếp ngay. Addon
  khác dùng dữ liệu của addon đang tắt sẽ báo **Thiếu phụ thuộc** cho tới khi bật lại.
- **Gỡ**: bấm [icon:delete] cạnh addon trong **Cài đặt → Addon**. Dữ liệu của addon vẫn giữ lại, cài lại là dùng tiếp.
- **Nhãn tin cậy**: **Đã ký** [icon:verified] là addon chính thức; **chưa ký** là addon admin tự đóng gói; **File đã bị
  sửa** [icon:warning] nghĩa là addon bị thay đổi sau khi cài, hãy liên hệ admin. Chỉ cài addon do admin gửi.

### Ba loại addon

| Loại | Cách chạy | Bạn làm gì |
|---|---|---|
| **Chạy khi cần** | Viewer Hub tự chạy khi bạn mở mục đó hoặc khi AI dùng tới, tự dừng khi đóng Viewer Hub | Không cần làm gì |
| **Dịch vụ** | Chạy nền, **vẫn chạy khi đóng Viewer Hub** | Bấm trạng thái ở đầu trang: **Chạy**, **Dừng**, **Khởi động lại**, **Tự chạy khi mở Viewer Hub** |
| **Chương trình ngoài** | Một chương trình bạn tự cài và tự mở như công cụ .NET của công ty; Viewer Hub chỉ kết nối tới nó | Mở chương trình đó trước. Đầu trang cho biết **Đã kết nối** hay chưa; chương trình dùng cổng khác thì bấm **Đổi cổng** |

### Trang của một addon

- Hàng đầu trang luôn do Viewer Hub vẽ: mô tả bên trái; bên phải là trạng thái (**Đang chạy** / **Đã dừng**, bấm
  vào để chạy, dừng, khởi động lại; hoặc **Đã kết nối** với chương trình ngoài), [icon:receipt_long] **Nhật ký** và
  [icon:settings] **Cài đặt** của addon. Khi cần bạn làm gì (chạy dịch vụ, mở chương trình, điền cài đặt), một dòng
  thông báo hiện ngay dưới kèm nút để làm luôn.
- Trang của addon bị lỗi: phần đầu trang vẫn dùng được để xem **Nhật ký** hay dừng dịch vụ.
- Addon có kết nối cho AI: địa chỉ MCP nằm ở mục **Dùng với AI qua MCP** cuối trang này, các tool ở phần **Tool cho AI** của addon.

### Khi addon gặp sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| "chưa chạy" / "Không khởi động được" | Bấm **Nhật ký**, xem dòng cuối. Dịch vụ: bấm **Chạy** ở dòng thông báo. |
| "Cần Node.js" | Addon cần Node.js trên máy: liên hệ admin để cài. |
| Chương trình ngoài **Chưa kết nối** | Mở chương trình đó rồi bấm **Kiểm tra lại**; sai cổng thì bấm **Đổi cổng**. |
| Không cài được addon | Đọc thông báo lỗi khi cài rồi gửi cho admin. |

Muốn tự viết addon: **Cài đặt → Addon → Tải SDK**, mở thư mục SDK bằng công cụ AI và làm theo `README.md`.
