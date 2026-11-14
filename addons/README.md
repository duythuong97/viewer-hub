# Addon mặc định

Mọi file `*.zip` addon đặt ở đây được `just build` đóng kèm vào bản phát hành (`<release>/addons/`) và **tự cài khi
Viewer Hub mở** (bản mới hơn thay bản cũ). Người dùng không phải tự upload.

- Lấy zip từ project của addon, vd. MCP Bridge: `cd ../viewer-hub-addons/my-bridge && npm run release` → `dist/mcp-bridge-<ver>.zip`,
  chép vào đây (xoá bản cũ). Hoặc `just addon-default ../viewer-hub-addons/my-bridge/dist/mcp-bridge-0.4.1.zip` (kiểm tra rồi chép).
- Zip được kiểm như lúc cài (addon.json, chữ ký, quy tắc bảo mật); zip hỏng làm build dừng.
- Zip **được commit**: đã ký trên máy tác giả (khoá ký không bao giờ rời máy đó), nên GitHub Actions build bản phát
  hành mà không cần khoá. Cập nhật một addon = `just addon-default <zip mới>` rồi commit (bản cũ bị xoá).
