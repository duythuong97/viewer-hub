## Cài đặt

- **Thư mục dữ liệu**: nơi lưu mọi thứ của bạn (CSV, Docs, ghi chú), tách khỏi chương trình nên **cập nhật phiên bản mới không mất dữ liệu**.
- **Data pack**: các gói dữ liệu đang có. Khi admin gửi file `.sapack` mới, bấm **Import .sapack** để nạp.
  - Gói mới **không ghi đè** CSV, Docs hay ghi chú của bạn; bản cũ vẫn được giữ.
  - Gói **cũ hơn** bản đang dùng được nạp nhưng không tự bật.
  - Muốn quay lại bản trước: bấm **Dùng bản này** ở bản đó.
- **Sao lưu**: ứng dụng tự sao lưu trước mỗi lần nâng cấp dữ liệu (giữ 5 bản). Bấm **Sao lưu ngay** khi muốn.


## Gặp sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Nhấp đúp mà không thấy gì | Xem cửa sổ console có báo lỗi không; mở lại. |
| Trang không mở được | Xem địa chỉ in trong cửa sổ console (cổng có thể khác 8700). |
| Banner đỏ "chỉ đọc" | Dữ liệu của bạn vẫn an toàn (đã sao lưu). Liên hệ admin. |
| Code map / F-Search trống, cũ, thiếu hệ thống | Liên hệ admin để nhận data pack mới. |
| Mất danh sách CSV/Docs sau sự cố | Liên hệ admin (có cách dựng lại từ dữ liệu trên máy). |

Khi báo lỗi, gửi kèm file log: `%LOCALAPPDATA%\ViewerHub\logs\viewer-hub.log` (log không chứa nội dung tài liệu).
