#!/bin/sh
# Viewer Hub on macOS/Linux: runs the app in this folder with the system python3 (3.12 or newer).
# The bundled python\ folder is for Windows only; app/ and app/vendor/ are pure Python and run anywhere.
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3.13 || command -v python3.12 || command -v python3)"
if [ -z "$PY" ]; then
  echo "Cần Python 3.12+ (python3). macOS: cài từ python.org hoặc 'brew install python'." >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Cần Python 3.12+; đang có: $("$PY" --version 2>&1)" >&2
  exit 1
fi
# Absolute paths (not "app"): the Hub hands its import path to addon processes, which run in their own folders.
exec "$PY" -I -c 'import sys; here = sys.argv.pop(1); sys.path[:0] = [here + "/app", here + "/app/vendor"]; from viewer_hub.cli import main; sys.exit(main(sys.argv[1:]))' "$HERE" "$@"
