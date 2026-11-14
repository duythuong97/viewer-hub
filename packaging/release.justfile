# Viewer Hub (bản phát hành): mọi lệnh cho máy đã giải nén zip, không cần source.
#
#   just              liệt kê lệnh
#   just pick         chọn lệnh bằng fzf (nếu có fzf)
#   just pack         đóng data pack từ thư mục input/ cạnh file này (cách chuẩn bị: input/README.md)
#
# Cần just (Windows: winget install Casey.Just; macOS: brew install just). Dữ liệu ở thư mục mặc định
# (%LOCALAPPDATA%\ViewerHub), hoặc thêm `--data-dir` qua biến VIEWER_HUB_HOME.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

vh := if os_family() == "windows" { "& .\\viewer-hub.cmd" } else { "./viewer-hub.sh" }

[private]
default:
    @just --list

# Chọn lệnh bằng fzf
[private]
pick:
    @just --choose

# Chạy Viewer Hub và mở trình duyệt
[group('chạy')]
serve port="8700":
    {{ vh }} serve --port {{ port }}

# Đóng data pack (.sapack) từ input/ (pack.yaml, codemap/, search.sqlite, csv/, docs/) vào dist/
[group('dữ liệu')]
pack input="input" out="dist":
    {{ vh }} pack --input {{ input }} --out {{ out }}

# Đóng data pack từ input/ rồi import luôn vào máy này
[group('dữ liệu')]
pack-install input="input" out="dist":
    {{ vh }} pack --input {{ input }} --out {{ out }} --install

# Import một data pack (.sapack)
[group('dữ liệu')]
import file:
    {{ vh }} import {{ file }}

# Xuất Solr ra input/search.sqlite cho F-Search (máy có Solr; vd. `just export-solr http://localhost:8983/solr/documents`)
[group('dữ liệu')]
export-solr url out="input/search.sqlite":
    {{ vh }} export-solr {{ url }} --out {{ out }}

# Cài một addon (.zip); tắt Viewer Hub trước nếu đang cập nhật một addon đang chạy
[group('addon')]
addon-install zip:
    {{ vh }} addon install {{ zip }}

# Addon đã cài
[group('addon')]
addons:
    {{ vh }} addon list

# Gỡ một addon (dữ liệu của nó vẫn giữ)
[group('addon')]
addon-remove id:
    {{ vh }} addon remove {{ id }}

# Đóng gói một addon tự viết thành zip (kiểm tra như lúc cài); daemon ở project khác: include=<zip / thư mục dist>
[group('addon')]
addon-pack dir include="":
    {{ vh }} addon pack {{ dir }} {{ if include == "" { "" } else { "--include " + include } }}

# Ghi bộ viết addon (AGENTS.md cho AI, mẫu, công cụ build trang) ra thư mục hiện tại
[group('addon')]
addon-sdk:
    {{ vh }} addon sdk

# Sao lưu dữ liệu người dùng
[group('dữ liệu')]
backup:
    {{ vh }} backup
