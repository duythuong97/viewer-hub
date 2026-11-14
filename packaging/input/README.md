# Thư mục `input/`: dữ liệu để đóng data pack (`.sapack`)

Data pack là một file `.sapack` chứa dữ liệu dự án (code map, tìm kiếm, CSV, tài liệu) để gửi cho mọi người.
Người nhận mở Viewer Hub → **Cài đặt → Import .sapack**. Dữ liệu trong pack là **chỉ đọc**, không trộn với dữ liệu
người dùng tự tải lên; import bản mới cùng `id` sẽ thay bản cũ.

## Cách đóng gói

```
just pack                 # input/ → dist/<id>-<version>.sapack
just pack-install         # như trên, rồi import luôn vào máy này để xem thử
```

Không có `just`: `viewer-hub.cmd pack --input input --out dist` (Windows) hoặc
`./viewer-hub.sh pack --input input --out dist` (macOS / Linux).

## Cấu trúc

Chỉ cần `pack.yaml` và **ít nhất một** phần dữ liệu; phần nào không có thì bỏ qua.

```
input/
  pack.yaml               id, title (bắt buộc), version (tuỳ chọn)
  codemap/                kết quả của công cụ code-map extract
    codemap.sqlite          bắt buộc nếu có thư mục này
    graph.sqlite, manifest.json, graph-index.json   (có thì đóng kèm)
  search.sqlite           chỉ mục F-Search
  csv/
    *.csv                 mỗi file một bảng (UTF-8, Shift_JIS / CP932… đều đọc được)
    config.json           (tuỳ chọn) tên, mô tả cho AI, cột hiện, bộ lọc
  docs/
    <tên site>/           mỗi thư mục con là một site tài liệu (tên thư mục = tên site)
      *.md, ảnh…
```

### `pack.yaml`

```yaml
id: core-system           # chữ thường, số, dấu -; giữ nguyên giữa các lần cập nhật
title: Core System        # tên hiện cho người dùng
version: 2026.11.14       # tuỳ chọn; bỏ trống thì lấy ngày giờ lúc đóng gói
```

### `codemap/`

Kết quả của **công cụ code-map extract** (không đi kèm Viewer Hub): chép nguyên thư mục output của nó vào đây. Chỉ
các file `codemap.sqlite`, `graph.sqlite`, `manifest.json`, `graph-index.json` được đóng vào pack; file khác (báo
cáo…) bị bỏ qua.

### `search.sqlite`

Chỉ mục cho F-Search, xuất từ Solr bằng:

```
viewer-hub.cmd export-solr http://<máy solr>:8983/solr/<core> --out input/search.sqlite
```

Cần máy truy cập được Solr; thường chỉ chạy trên máy của người chuẩn bị dữ liệu.

### `csv/`

Mỗi file `.csv` thành một bảng xem / lọc được trên trang CSV, và AI đọc được (MCP). Cột, kiểu, chỉ mục được tạo
sẵn lúc đóng gói nên máy người dùng mở ngay. Encoding tự nhận (UTF-8, có / không BOM, Shift_JIS / CP932…).

`config.json` (tuỳ chọn, cạnh các file CSV), mỗi mục là một bảng, key là tên hiện cho người dùng:

```json
{
  "Nhân viên": {
    "path": "nhan-vien.csv",
    "description": "Danh sách nhân viên: mã, tên, phòng ban, ngày vào công ty.",
    "columnDescriptions": {"ma_nv": "Mã nhân viên, khoá chính", "phong": "Mã phòng ban (bảng Phòng ban)"},
    "visibleCols": ["ma_nv", "ho_ten", "phong"],
    "filterCol": [{"phong": "IN"}],
    "mcp": true
  }
}
```

| Trường | Ý nghĩa |
|---|---|
| `path` | tên file CSV (bỏ trống: `<tên>.csv`) |
| `description` | mô tả bảng cho người và AI (nên có: thiếu thì lúc đóng gói sẽ nhắc) |
| `columnDescriptions` | mô tả từng cột theo tên cột |
| `visibleCols` | cột hiện mặc định |
| `filterCol` | cột có bộ lọc: `IN` (chọn nhiều giá trị) hoặc `==` |
| `mcp` | `false` để AI không đọc bảng này (mặc định: đọc được) |

### `docs/`

Mỗi thư mục con là một site tài liệu, tên thư mục là tên site. Bên trong là file Markdown (`.md`) và ảnh; thư mục
con được giữ nguyên. Site được build sẵn (mkdocs) lúc đóng gói.

## Kiểm tra trước khi gửi

1. `just pack-install`, mở Viewer Hub, xem từng trang (Code map, F-Search, CSV, Docs).
2. Hỏi AI một câu về dữ liệu (MCP) để chắc nó đọc được.
3. Gửi file trong `dist/`. Người nhận: **Cài đặt → Import .sapack**.
