"""Writing addons outside the Hub source (docs/addons.md §8.1): the SDK users download (viewer_hub/addons/kit,
sdk_kit.py), `viewer-hub addon pack`, zips made by hand, and the two templates working for real."""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from tests.test_core import _client_with
from viewer_hub.addons import install as installer
from viewer_hub.addons import sdk_kit
from viewer_hub.addons.manifest import AddonError, load
from viewer_hub.addons.pack import pack

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "viewer_hub" / "addons" / "kit"
TEMPLATES = KIT / "sdk" / "templates"


def _project(tmp_path: Path, template: str, ui: bool = True) -> Path:
    """A copy of a template as a user starts one, with its page "built" (a stand-in ui.js)."""
    folder = tmp_path / f"proj-{template}"
    shutil.copytree(TEMPLATES / template, folder)
    if ui:
        (folder / "ui").mkdir()
        (folder / "ui" / "ui.js").write_text('import React from "/static/dist/sdk/react.js";\nexport default () => null;\n')
    return folder


def test_sdk_download(paths):
    client = _client_with(paths)
    response = client.get("/api/addons/sdk")
    assert response.status_code == 200 and response.mimetype == "application/zip"
    assert sdk_kit.file_name() in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        names = set(archive.namelist())
        agents = archive.read(f"{sdk_kit.TOP}/AGENTS.md").decode()
        readme = archive.read(f"{sdk_kit.TOP}/README.md").decode()
        package = json.loads(archive.read(f"{sdk_kit.TOP}/package.json"))
    for name in ("AGENTS.md", "README.md", "package.json", ".gitignore", ".sdk/build.mjs", ".sdk/new.mjs",
                 ".sdk/python/viewer_hub/addons/sdk.py", ".sdk/python/viewer_hub/core/mcp.py", ".sdk/templates/simple/addon.json", ".sdk/templates/simple/main.py",
                 ".sdk/templates/simple/web/index.jsx", ".sdk/templates/daemon/addon.json", ".sdk/templates/daemon/main.mjs"):
        assert f"{sdk_kit.TOP}/{name}" in names, name
    assert "{{" not in agents + readme + json.dumps(package) and "npm run zip" in readme
    assert set(package["scripts"]) == {"new", "build", "watch", "check", "test", "zip", "exports"}
    # "sdk" is not an addon id the Hub would route
    assert "sdk" in client.application.extensions["hub"].addons.reserved


def test_agents_md_keeps_up_with_the_sdk():
    """Every export of @vh/ui and @vh/md is documented; the kit's page build matches the Hub's own."""
    agents = (KIT / "AGENTS.md").read_text(encoding="utf-8")
    ui = (ROOT / "web" / "src" / "sdk" / "ui.js").read_text(encoding="utf-8")
    md = (ROOT / "web" / "src" / "md" / "react.jsx").read_text(encoding="utf-8")
    exported = {n.strip() for group in re.findall(r"export \{([^}]*)\}", ui) for n in group.split(",")}
    exported |= set(re.findall(r"^export function (\w+)", md, re.M))
    for sdk_file in ("mermaid.js", "flow.js"):
        exported |= set(re.findall(r"^export function (\w+)", (ROOT / "web" / "src" / "sdk" / sdk_file).read_text(encoding="utf-8"), re.M))
    missing = sorted(name for name in exported if not re.search(rf"`{name}\b", agents))
    assert not missing, f"AGENTS.md: thiếu {missing}"
    sdk_map = lambda text: dict(re.findall(r"['\"]?([@\w/.-]+)['\"]?:\s*['\"]([\w-]+)['\"]", text.split("};")[0].split("SDK = {")[1]))
    build = (KIT / "sdk" / "build.mjs").read_text()
    # every "@vh/…" the SDK builder leaves to the Hub is a file the Hub builds (web/vite.config.js sdk/<name>)
    hub_sdk = set(re.findall(r"'sdk/([\w-]+)'", (ROOT / "web" / "vite.config.js").read_text()))
    assert set(sdk_map(build).values()) == hub_sdk
    # the SDK's zip leaves out exactly what an install skips
    js_list = lambda name: set(re.findall(r'"([^"]+)"', build.split(f"const {name} = [")[1].split("]")[0]))
    assert js_list("DEV_ROOT") == installer.DEV_ROOT and js_list("DEV_ANY") == installer.DEV_ANY


def test_templates_pack_and_install(paths, tmp_path):
    for template in ("simple", "daemon"):
        out = pack(_project(tmp_path, template), tmp_path / "dist", log=lambda _: None)
        result = installer.install_zip(paths, out)
        assert result.trust == "unsigned" and (result.addon.folder / "ui" / "ui.js").is_file()
        assert not (result.addon.folder / "web").exists()


def test_pack_refuses_an_unbuilt_page_and_a_bad_guide(tmp_path):
    with pytest.raises(AddonError, match="npm run build"):
        pack(_project(tmp_path, "simple", ui=False), tmp_path / "dist", log=lambda _: None)
    project = _project(tmp_path / "b", "simple")
    guide = project / "GUIDE.md"
    guide.write_text(guide.read_text(encoding="utf-8").replace("| `notes_read` |", "| notes_read |"), encoding="utf-8")
    with pytest.raises(AddonError, match="notes_read"):
        pack(project, tmp_path / "dist", log=lambda _: None)


def test_pack_merges_a_program_built_elsewhere(tmp_path):
    """A daemon in its own project: its release zip (Name-<version>/) is merged in, launchers left out."""
    project = _project(tmp_path, "daemon")
    (project / "main.mjs").unlink()
    program = tmp_path / "program.zip"
    with zipfile.ZipFile(program, "w") as archive:
        archive.writestr("MyDaemon-0.3.0/main.mjs", (TEMPLATES / "daemon" / "main.mjs").read_text())
        archive.writestr("MyDaemon-0.3.0/lib/util.mjs", "export const x = 1;\n")
        archive.writestr("MyDaemon-0.3.0/run.cmd", "@echo off\n")
    out = pack(project, tmp_path / "dist", [program], log=lambda _: None)
    assert out.name == "my-daemon-0.3.0.zip"
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
    assert {"my-daemon/main.mjs", "my-daemon/lib/util.mjs"} <= names
    assert "my-daemon/run.cmd" not in names


def test_a_zip_made_by_hand_installs(paths, tmp_path):
    """Explorer / Finder zip of the project folder, or of its contents: source folders and dotfiles are skipped."""
    project = _project(tmp_path, "simple")
    (project / "node_modules" / ".bin").mkdir(parents=True)
    (project / "node_modules" / ".bin" / "vite.cmd").write_text("@echo off")
    (project / ".DS_Store").write_bytes(b"x")
    for dev in ("src/main.mjs", "test/a.test.mjs", "AGENTS.md", "README.md", "package.json", ".sdk/build.mjs", "dist/old.zip"):
        (project / dev).parent.mkdir(parents=True, exist_ok=True)
        (project / dev).write_text("x")
    for top in ("my-folder/", ""):
        archive_path = tmp_path / f"hand{len(top)}.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for path in sorted(project.rglob("*")):
                if path.is_file():
                    archive.write(path, top + path.relative_to(project).as_posix())
                    if top:  # macOS Finder "Compress" adds a second top folder of metadata
                        archive.writestr(f"__MACOSX/{top}._" + path.relative_to(project).as_posix(), b"meta")
        result = installer.install_zip(paths, archive_path)
        installed = {p.relative_to(result.addon.folder).as_posix() for p in result.addon.folder.rglob("*") if p.is_file()}
        assert installed == {"addon.json", "GUIDE.md", "main.py", "ui/ui.js"}, installed
        assert load(result.addon.folder).id == "my-addon"


def test_cli_pack_and_sdk(paths, tmp_path, capsys):
    from viewer_hub.cli import main

    project = _project(tmp_path, "simple")
    assert main(["--data-dir", str(paths.home), "addon", "pack", str(project), "--out", str(tmp_path / "d")]) == 0
    assert (tmp_path / "d" / "my-addon-0.1.0.zip").is_file()
    assert main(["--data-dir", str(paths.home), "addon", "sdk", "--out", str(tmp_path / "s")]) == 0
    assert (tmp_path / "s" / sdk_kit.file_name()).is_file()
    shutil.rmtree(project / "ui")
    assert main(["--data-dir", str(paths.home), "addon", "pack", str(project)]) == 1
    assert "npm run build" in capsys.readouterr().err


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_daemon_template_runs(paths, tmp_path):
    """The daemon template honours the contract: init / start / status, health, its API, EVENTS, shutdown."""
    from viewer_hub.addons.registry import Registry

    installer.install_zip(paths, pack(_project(tmp_path, "daemon"), tmp_path / "dist", log=lambda _: None))
    registry = Registry(paths)
    runner = registry.runner(registry.get("my-daemon"))
    try:
        ok, message = runner.start({"name": "Thử", "interval": "1"})
        assert ok, message + "\n" + "\n".join(runner.log_tail())
        assert runner.status()["running"] is True
        status, state = runner.request("GET", "/api/state")
        assert status == 200 and state["name"] == "Thử" and state["interval"] == 1
        events = runner.events()
        assert next(events)["event"] == "keepalive"
        assert next(events)["event"] == "tick"
        assert runner.request("GET", "/api/nope")[0] == 404
        # its output reaches the Hub's log (runner.tee), whole, through the API too
        import time
        for _ in range(20):
            if "Thử: đang chạy" in runner.log_text():
                break
            time.sleep(0.2)
        assert "Thử: đang chạy" in runner.log_text()
        client = _client_with(paths)
        assert "Thử: đang chạy" in client.get("/api/addons/my-daemon/log").get_json()["text"]
        assert client.get("/api/addons/my-daemon/status").get_json()["running"] is True
        # init gets a setting only when it changed since the last start: what the user changed elsewhere stays
        assert runner.setting_args({"name": "Thử"}, "init") == []
        assert runner.setting_args({"name": "Khác"}, "init") == ["--name", "Khác"]
        assert runner.setting_args({"interval": "1"}, "start") == ["--interval", "1"]
        # a Hub opened later (no runner for it yet) still stops it before removing the addon
        later = Registry(paths)
        later.refresh()
        assert later.forget("my-daemon")[0] is True
        assert not runner.running()
    finally:
        ok, message = runner.stop()
    assert ok, message
    assert runner.status()["running"] is False


def test_log_rotates(tmp_path):
    from viewer_hub.addons.runner import rotate, tee

    log = tmp_path / "addon-x.log"
    log.write_bytes(b"x" * 100)
    rotate(log, limit=50)
    assert not log.exists() and (tmp_path / "addon-x.1.log").read_bytes() == b"x" * 100
    assert tee(str(log), [sys.executable, "-c", "print('xin chào'); print('hai')"]) == 0
    assert log.read_text(encoding="utf-8").splitlines() == ["xin chào", "hai"]


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_sdk_new_check_zip_install(paths, tmp_path):
    """The SDK as a user gets it: unzip, `npm run new`, `npm run check` / `zip` (no page here: no vite needed), and
    the zip installs with only the addon's own files."""
    import subprocess

    with zipfile.ZipFile(io.BytesIO(sdk_kit.build())) as archive:
        archive.extractall(tmp_path)
    folder = tmp_path / sdk_kit.TOP
    run = lambda *args: subprocess.run(["node", *args], cwd=folder, capture_output=True, text=True, timeout=60)
    assert run(".sdk/build.mjs", "check").returncode == 1  # no addon yet
    made = run(".sdk/new.mjs", "daemon", "my-sync")
    assert made.returncode == 0, made.stderr
    assert run(".sdk/new.mjs", "simple", "other").returncode == 1  # one addon per folder
    assert json.loads((folder / "package.json").read_text())["name"] == "my-sync"
    data = json.loads((folder / "addon.json").read_text())
    assert data["id"] == "my-sync" and data["entry"] == "main.mjs"
    shutil.rmtree(folder / "web")
    data.pop("ui")
    (folder / "addon.json").write_text(json.dumps(data))
    zipped = run(".sdk/build.mjs", "zip")
    assert zipped.returncode == 0, zipped.stderr + zipped.stdout
    out = folder / "dist" / f"my-sync-{data['version']}.zip"
    with zipfile.ZipFile(out) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"my-sync/addon.json", "my-sync/GUIDE.md", "my-sync/main.mjs"}
    assert installer.install_zip(paths, out).addon.id == "my-sync"
    with zipfile.ZipFile(out) as archive:
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())  # a valid DOS date


# One line each: what core/scan.py refuses (or notes) and so must `npm run check` (kit/sdk/build.mjs scan()).
SCAN_SAMPLES = [
    ("lib/a.py", "subprocess.run(x, shell=True)"), ("lib/a.py", "os.system('x')"), ("lib/a.py", "eval(text)"),
    ("lib/a.py", "run('powershell -c x')"), ("lib/a.py", "import winreg"), ("lib/a.py", "pickle.loads(b)"),
    ("lib/a.py", "yaml.load(text)"), ("lib/a.py", "import urllib.request"), ("lib/a.py", "import subprocess"),
    ("lib/a.py", "socket.socket()"), ("lib/a.py", "base64.b64decode(x)"),
    ("ui/ui.js", 'import("https://cdn.example.com/x.js")'), ("ui/ui.js", "new Function('x')"),
    ("ui/ui.js", "el.innerHTML = x"), ("ui/ui.css", "@import url(https://fonts.googleapis.com/x);"),
    ("main.mjs", "spawn('x', { shell: true })"), ("main.mjs", "import 'node:child_process'"),
    ("lib/tool.exe", "MZ"), ("lib/CON.py", "x = 1"), ("lib/a?.py", "x = 1"),
    ("lib/a.py", "eval(text)  # noqa: security"),
]


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_sdk_check_scans_like_the_hub(tmp_path):
    """`npm run check` refuses and notes exactly what an install would, sample by sample."""
    import subprocess

    from viewer_hub.core.scan import scan_addon

    build = (KIT / "sdk" / "build.mjs").as_uri()
    script = (f"import {{ scan }} from {json.dumps(build)};\n"
              "const r = scan(process.argv[1]); console.log(JSON.stringify([r.errors.length > 0, r.notes.length > 0]));")
    for rel, line in SCAN_SAMPLES:
        folder = tmp_path / f"s{SCAN_SAMPLES.index((rel, line))}"
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if "?" in rel and sys.platform == "win32":
            continue
        target.write_text(line + "\n", encoding="utf-8")
        errors, notes = scan_addon(folder)
        if rel.startswith("lib/CON") or "?" in rel:  # names: install.py refuses them before scanning
            errors = ["name"]
        js = subprocess.run(["node", "--input-type=module", "-e", script, str(folder)], capture_output=True, text=True,
                            timeout=30)
        assert js.returncode == 0, js.stderr
        assert json.loads(js.stdout) == [bool(errors), bool(notes)], (rel, line, errors, notes)


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_sdk_runs_the_template_tests_without_a_hub(tmp_path):
    """`npm test` in a fresh simple addon: its unittest imports the real Python SDK shipped in .sdk/python."""
    import subprocess

    with zipfile.ZipFile(io.BytesIO(sdk_kit.build())) as archive:
        archive.extractall(tmp_path)
    folder = tmp_path / sdk_kit.TOP
    run = lambda *args: subprocess.run(["node", *args], cwd=folder, capture_output=True, text=True, timeout=60,
                                       env={**__import__("os").environ, "VIEWER_HUB_PYTHON": sys.executable})
    assert run(".sdk/new.mjs", "simple", "my-notes").returncode == 0
    tested = run(".sdk/build.mjs", "test")
    assert tested.returncode == 0 and "OK" in tested.stderr, tested.stdout + tested.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_sdk_runs_node_tests(tmp_path):
    """`npm test` of a Node addon: node --test on the test files (Node 22 does not take a directory)."""
    import subprocess

    with zipfile.ZipFile(io.BytesIO(sdk_kit.build())) as archive:
        archive.extractall(tmp_path)
    folder = tmp_path / sdk_kit.TOP
    assert subprocess.run(["node", ".sdk/new.mjs", "daemon", "my-sync"], cwd=folder, capture_output=True).returncode == 0
    (folder / "test").mkdir()
    (folder / "test" / "a.test.mjs").write_text('import { test } from "node:test";\ntest("ok", () => {});\n')
    tested = subprocess.run(["node", ".sdk/build.mjs", "test"], cwd=folder, capture_output=True, text=True, timeout=60)
    assert tested.returncode == 0 and "# pass 1" in tested.stdout, tested.stdout + tested.stderr
