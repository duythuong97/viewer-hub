# Changelog

Mọi thay đổi quan trọng của Viewer Hub được ghi nhận tại đây.

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
- **Code Map**: Lazy Loading cây thư mục (`business_tree_roots` & `children`), giải quyết đơ giao diện ở đồ thị lớn.
- **Addon Bundler**: Sửa cấu hình Rollup/Vite trong SDK build xuất đúng `ui/ui.css` cho addon có stylesheet riêng.
- **Cập nhật Addons**: `mcp-bridge` 0.4.2 và `api-specs` 0.3.1.

---

## [v0.2.1] - 2026-11-16
- Minify addon Node bundles; db-query 0.4.1.

## [v0.2.0] - 2026-11-15
- Addons chia sẻ dữ liệu qua hợp đồng `exports` / `uses`.
