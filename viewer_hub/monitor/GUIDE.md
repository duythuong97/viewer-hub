## Giám sát

Xem **AI đang dùng các MCP của Viewer Hub thế nào**: tool nào được gọi, bởi AI nào, mất bao lâu, có lỗi không, trả về
bao nhiêu chữ (≈ token AI phải đọc). Gồm cả MCP của module có sẵn (Code map, F-Search, CSV) lẫn **addon** (SVN, Sơ đồ…), dù AI
nối qua địa chỉ HTTP, qua lệnh `viewer-hub mcp …` hay qua addon gom MCP. Mọi số liệu nằm trên máy này.

- **Tổng quan**: số lời gọi, tỉ lệ lỗi, thời gian trả lời (p50 / p95: một nửa / 95% lời gọi nhanh hơn mức này), token
  ước tính; biểu đồ theo giờ; từng MCP; các AI đã kết nối và lần gọi cuối; sự kiện của addon. Chọn khung thời gian
  ở góc trên (1 giờ → 14 ngày).
- **Lời gọi**: danh sách cập nhật liên tục (vài giây một lần). Lọc theo MCP, AI, hoặc chỉ xem lỗi; bấm một dòng để
  xem chi tiết (tham số, lỗi). [icon:pause] tạm dừng cập nhật để đọc.
- **Theo tool**: mỗi tool một dòng: số lần gọi, lỗi, p50 / p95 / lâu nhất, cỡ kết quả trung bình. Tool chậm hoặc trả
  quá dài là chỗ nên xem lại (AI tốn context).
- **Addon**: trạng thái, RAM / CPU (6 giờ qua), số lần dừng bất thường, sự kiện chạy / dừng; addon gom MCP thì có thêm số
  lời gọi nó nhận (cả các MCP không thuộc Viewer Hub). [icon:description] mở nhật ký của addon.
- **Cảnh báo**: khi một MCP lỗi nhiều (≥ 20% trong 15 phút), tool chậm (p95 > 10 giây), addon dừng bất thường liên tục
  hoặc dùng quá 1,5 GB RAM: hiện ở đầu trang Giám sát, trên **Trang chủ** và chấm đỏ trên menu.

**Riêng tư**: mặc định chỉ lưu **tên** và độ dài tham số (vd. `path: text(32)`), không lưu nội dung AI gửi hay kết quả
trả về. Mục **Cài đặt** của trang: bật / tắt giám sát, chọn lưu đầy đủ tham số (để gỡ lỗi, tối đa 2000 ký tự), số ngày
giữ chi tiết (mặc định 14; số liệu theo giờ giữ 90 ngày), [icon:delete_sweep] xoá toàn bộ.

### Tool cho AI
| Tool | AI dùng để |
|---|---|
| `monitor_errors` | Xem các lời gọi tool bị lỗi gần đây (thời gian, tool, lỗi) khi một tool không chạy như mong đợi |
| `monitor_tools` | Xem tool nào chậm, lỗi nhiều hoặc trả kết quả quá dài |
| `monitor_status` | Xem có gì cần chú ý: MCP đang lỗi, addon dừng bất thường, tổng lời gọi 24 giờ |
