"""Static checks for the rules in docs/GUIDELINE.md §5 (run before every commit and in CI).

    just security        (python packaging/check_security.py)

The rules live in viewer_hub/core/scan.py, shared with the install-time scan of addons; addon projects in addons/
are checked the way an install checks them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "viewer_hub"
sys.path.insert(0, str(ROOT))

from viewer_hub.core.scan import EXECUTABLE, PY_RULES, WEB_RULES, line_of, scan_addon  # noqa: E402

SKIP = {"core/scan.py"}  # holds the patterns themselves


def main() -> int:
    problems = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel in SKIP:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, message, allowed in PY_RULES:
            if rel in allowed:
                continue
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                line = line_of(text, match.start())
                if "noqa: security" in text.splitlines()[line - 1]:
                    continue
                problems.append(f"viewer_hub/{rel}:{line}: {message}")
    web_files = [*APP.rglob("*.html"), *(ROOT / "web" / "src").rglob("*.js*")]
    for path in web_files:
        text = path.read_text(encoding="utf-8")
        for pattern, message in WEB_RULES:
            for match in re.finditer(pattern, text):
                problems.append(f"{path.relative_to(ROOT)}:{line_of(text, match.start())}: {message}")
    for path in APP.rglob("*"):
        if path.suffix in EXECUTABLE:
            problems.append(f"{path.relative_to(ROOT)}: file thực thi trong mã nguồn")
    for addon in sorted(p.parent for p in (ROOT / "tests" / "fixtures").glob("*/addon.json")):
        errors, _notes = scan_addon(addon)
        problems += [f"{addon.relative_to(ROOT)}/{error}" for error in errors]
    for problem in problems:
        print(problem)
    print(f"{len(problems)} vấn đề" if problems else "OK: không có vi phạm GUIDELINE §5")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
