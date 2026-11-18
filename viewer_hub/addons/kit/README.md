# Viewer Hub: bộ viết addon (SDK {{sdk}})

Viết tính năng thêm cho Viewer Hub, đóng thành zip, cài ở **Cài đặt → Addon**. Không cần mã nguồn Viewer Hub.

**Thư mục này là project của một addon.** Mỗi addon một thư mục: giải nén SDK một lần cho mỗi addon (tên thư mục tuỳ
ý, nên đặt theo id, vd. `jira-reader`). Loại nào (managed, daemon, external) cũng cùng một cấu trúc:
`addon/` (khai báo + hướng dẫn), `src/` (chương trình), `web/` (trang), `test/`. `npm run build` lắp gói thật vào
`build/<id>/` (gốc chỉ có `addon.json`, `GUIDE.md`, `signature.json`, `ui/`, `app/`, `assets/`, `legal/`).

**Dùng AI để viết:** mở thư mục này bằng công cụ AI (Claude Code, Copilot, Cursor...) và nói việc bạn muốn, vd.
"Viết addon đọc ticket Jira theo AGENTS.md". AI đọc `AGENTS.md` (đầy đủ quy tắc).

## Các bước

1. Cài Node.js 22+, chạy `npm install` một lần.
2. Tạo addon từ mẫu, ngay trong thư mục này:
   - `npm run new -- simple jira-reader`: hàm + trang + tool MCP cho AI (Python). Hầu hết addon dùng mẫu này.
   - `npm run new -- daemon my-sync`: chương trình chạy nền mà Viewer Hub bật / tắt (Node.js).
   - `npm run new -- external my-tool`: nối tới chương trình có sẵn viết bằng ngôn ngữ khác (.NET, Java…) mà người
     dùng tự cài và tự chạy; addon chỉ có trang và khai báo cổng.
3. Sửa `addon/addon.json` (`name`, `menu`), code (`src/main.py` / `src/main.mjs`), `addon/GUIDE.md`, trang `web/index.jsx`.
4. `npm test` (test trong `test/`), `npm run check` (kiểm tra như lúc cài), rồi `npm run zip` → `dist/<id>-<version>.zip`.
5. Viewer Hub → **Cài đặt → Addon → Cài addon (.zip)**. Mục mới hiện trên menu.

Hub chỉ cài zip đúng cấu trúc gói (§2 của `AGENTS.md`): đừng nén tay thư mục project, hãy dùng `npm run zip`.
