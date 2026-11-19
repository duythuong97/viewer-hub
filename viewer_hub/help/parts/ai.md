## Dùng với AI qua MCP

Các mục dưới đây có sẵn kết nối cho AI agent (MCP), ví dụ Copilot, Claude. AI chỉ **đọc**; mọi thứ chạy trên máy bạn. Khi ứng dụng đang chạy:

{{mcp}}

`<cổng>` là cổng trên thanh địa chỉ trình duyệt (thường là 8700). Cách thêm vào Copilot/Claude: liên hệ admin.
Các tool AI dùng được ghi ở phần **Tool cho AI** trong mục của từng phần.

### Dùng với GitHub Copilot

Ở đầu trang này có hai nút:

- **Sao chép cấu hình MCP**: dán vào `.vscode/mcp.json` của folder (hoặc file `mcp.json` của VS Code để dùng cho mọi folder). Địa chỉ lấy theo cổng đang chạy; Viewer Hub đổi cổng thì sao chép lại.
- **Tải skills (.zip)**: giải nén vào `.github/skills/` của folder. Mỗi mục là một skill nhỏ; Copilot chỉ nạp phần chi tiết khi việc đang làm cần đến, nên không làm đầy ngữ cảnh.

Viewer Hub phải đang mở thì AI mới đọc được dữ liệu.
