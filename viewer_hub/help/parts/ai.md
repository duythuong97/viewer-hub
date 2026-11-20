## Dùng với AI qua MCP

Các mục dưới đây có sẵn kết nối cho AI agent (MCP), ví dụ Copilot, Claude. AI chỉ **đọc**; mọi thứ chạy trên máy bạn. Khi ứng dụng đang chạy:

{{mcp}}

`<cổng>` là cổng trên thanh địa chỉ trình duyệt (thường là 8700). Cách thêm vào Copilot/Claude: liên hệ admin.
Các tool AI dùng được ghi ở phần **Tool cho AI** trong mục của từng phần.

### Dùng với GitHub Copilot

Vào **Cài đặt** → **Dùng với GitHub Copilot**:

- **Sao chép cấu hình MCP**: dán vào `.vscode/mcp.json` của folder (hoặc file `mcp.json` của VS Code để dùng cho mọi folder). Địa chỉ lấy theo cổng đang chạy; Viewer Hub đổi cổng thì sao chép lại.
- **Tải skills (.zip)**: giải nén vào `.github/skills/` của folder. Mỗi mục là một skill nhỏ; Copilot chỉ nạp phần chi tiết khi việc đang làm cần đến, nên không làm đầy ngữ cảnh.
- **Tự đồng bộ skills vào folder**: nhập đường dẫn các folder project (repo) bạn mở bằng VS Code → **Thêm**. Mỗi lần Viewer Hub khởi động, skills được ghi vào `.github/skills/` của từng folder: thêm skill mới (addon mới cài, tính năng premium vừa mở), cập nhật skill đã đổi, xoá skill không còn dùng. Viewer Hub chỉ đụng tới skill nó tạo (có dòng `viewer-hub: tự sinh` trong `SKILL.md`); skill bạn tự viết giữ nguyên. Bấm **Đồng bộ ngay** để không phải chờ lần khởi động sau; dòng dưới mỗi folder cho biết lần đồng bộ gần nhất hoặc lỗi.

Viewer Hub phải đang mở thì AI mới đọc được dữ liệu.
