# Viewer Hub: every command of this repo in one place.
#
#   just              pick a command with fzf (Enter runs it; the preview shows what it does)
#   just --list       every command, by group
#   just <command>    run one directly, e.g. `just serve 8700`, `just unlock bridge`, `just addon-default <zip>`
#
# Needs uv, just, fzf (for the picker) and Node.js 22+:
#   macOS:   brew install uv just fzf node
#   Windows: winget install astral-sh.uv Casey.Just junegunn.fzf OpenJS.NodeJS.LTS

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Pick a command with fzf
[private]
default:
    @just --choose

# ── Cài đặt ──────────────────────────────────────────────────────────────

# Cài / cập nhật môi trường: Python (uv sync → .venv) và thư viện web (npm ci). Chạy lần đầu và sau mỗi lần pull.
[group('cài đặt')]
setup:
    uv sync
    npm ci --prefix web

# ── Chạy ─────────────────────────────────────────────────────────────────

# Chạy Viewer Hub từ source (dữ liệu dev ở var/dev, cổng 8765; vd. `just serve 8700`). Cần `just web` trước nếu chưa build giao diện.
[group('chạy')]
serve port="8765" data="var/dev":
    uv run viewer-hub --data-dir {{ data }} serve --port {{ port }}

# Build lại giao diện mỗi khi sửa file trong web/ (để chạy song song với `just serve`)
[group('chạy')]
web-watch:
    npm run dev --prefix web

# ── Kiểm tra ─────────────────────────────────────────────────────────────

# Kiểm tra đầy đủ trước khi commit: build giao diện, pytest, quy tắc bảo mật, test code map (JS)
[group('kiểm tra')]
check: web test security test-web

# Chạy pytest (thêm tham số: `just test -k unlock`)
[group('kiểm tra')]
test *args:
    uv run pytest -q {{ args }}

# Quét quy tắc bảo mật (GUIDELINE §5)
[group('kiểm tra')]
security:
    uv run python packaging/check_security.py

# Test JS của code map
[group('kiểm tra')]
test-web:
    npm run test:codemap --prefix web

# Soát giao diện: mở mọi trang (dữ liệu demo có chữ rất dài) ở 1600 / 1200 / 760px bằng Chrome / Edge, báo chỗ tràn khung, ảnh ở var/ui-check (vd. `just ui-check --only codemap`)
[group('kiểm tra')]
ui-check *args: web
    uv run python packaging/ui_check.py {{ args }}

# Build giao diện React (web/ → viewer_hub/static/dist)
[group('kiểm tra')]
web:
    npm run build --prefix web

# ── Build / phát hành ────────────────────────────────────────────────────

# Build bản phát hành đầy đủ (zip gửi mọi người: app + data pack từ input/ + addon mặc định trong addons/), build lại giao diện
[group('build')]
build:
    uv run python packaging/build.py

# Như build nhưng dùng lại giao diện đã build (nhanh hơn; chỉ khi không sửa web/ từ lần build trước)
[group('build')]
build-fast:
    uv run python packaging/build.py --skip-web

# Đóng data pack (.sapack) từ input/ vào dist/: cập nhật dữ liệu cho người đã cài (Cài đặt → Import .sapack)
[group('build')]
pack input="input" out="dist":
    uv run viewer-hub pack --input {{ input }} --out {{ out }}

# Cập nhật phiên bản thư viện: uv.lock (máy dev) và packaging/requirements.lock (đóng vào bản Windows)
[group('build')]
lock:
    uv lock --upgrade
    uv pip compile pyproject.toml --python-platform x86_64-pc-windows-msvc --python-version 3.12 --upgrade -o packaging/requirements.lock

# ── Addon ────────────────────────────────────────────────────────────────

# Đóng một project addon (thư mục SDK) thành dist/addons/<id>-<version>.zip, đã ký: đồng bộ SDK, build bằng .sdk/build.mjs, kiểm tra
[group('addon')]
addon dir:
    uv run python packaging/addon.py build {{ dir }}

# Thêm / cập nhật một addon mặc định (đi kèm mọi bản build, tự cài khi mở): kiểm tra zip rồi chép vào addons/, bỏ bản cũ
[group('addon')]
addon-default zip:
    uv run python packaging/addon.py default {{ zip }}

# Cài một addon zip vào dữ liệu dev (var/dev); trên web: Cài đặt → Addon
[group('addon')]
addon-install zip data="var/dev":
    uv run viewer-hub --data-dir {{ data }} addon install {{ zip }}

# Addon đã cài trong dữ liệu dev
[group('addon')]
addons data="var/dev":
    uv run viewer-hub --data-dir {{ data }} addon list

# Sửa giao diện addon: build lại vào bản đã cài trong var/dev mỗi lần lưu file (F5 để xem; cài addon một lần trước)
[group('addon')]
addon-watch dir data="var/dev":
    cd {{ dir }} && node .sdk/build.mjs watch --out {{ justfile_directory() / data / "addons" / file_name(dir) / "ui" }}

# Đưa file SDK (.sdk/, AGENTS.md, package.json) của các project addon lên bản SDK của Hub này (`just addon` cũng tự làm)
[group('addon')]
addon-sdk-sync +dirs:
    uv run python packaging/addon.py sync {{ dirs }}

# Bộ viết addon cho người dùng (giống nút Tải SDK ở Cài đặt → Addon): AGENTS.md, mẫu, công cụ build trang
[group('addon')]
addon-sdk out="dist":
    uv run viewer-hub addon sdk --out {{ out }}

# ── Mở khoá premium ──────────────────────────────────────────────────────

# Tạo một mã mở khoá premium mới, ngẫu nhiên (không tham số: hỏi tính năng; vd. `just unlock bridge`)
[group('premium')]
unlock *features:
    uv run python packaging/unlock.py issue {{ features }}

# Xem một mã mở khoá mở tính năng gì (không tham số: hỏi mã)
[group('premium')]
unlock-check code="":
    uv run python packaging/unlock.py check {{ code }}

# Đặt mật khẩu admin: trong bản phát hành, `just unlock` hỏi mật khẩu này để tạo mã (chỉ khoá công khai vào code)
[group('premium')]
unlock-passphrase:
    uv run python packaging/unlock.py passphrase

# Tạo khoá ký MỚI: mọi mã đã phát mất hiệu lực. Chỉ dùng khi mất khoá ~/.viewer-hub/unlock-signing.key
[confirm('Tạo khoá ký mới làm MỌI mã đã phát mất hiệu lực. Tiếp tục? (y/N)')]
[group('premium')]
unlock-keygen:
    uv run python packaging/unlock.py keygen --force

# ── Dữ liệu ──────────────────────────────────────────────────────────────

# Xuất Solr ra input/search.sqlite cho F-Search (vd. `just export-solr http://localhost:8983/solr/documents`)
[group('dữ liệu')]
export-solr url out="input/search.sqlite":
    uv run viewer-hub export-solr {{ url }} --out {{ out }}
