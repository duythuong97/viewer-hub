"""An addon never takes the Hub down: what an upload is refused for, and what a slow, hung, crashing or log-flooding
addon may hold of the Hub (addons/install.py, addons/limits.py, addons/runner.py)."""
from __future__ import annotations

import json
import threading
import time
import zipfile
from pathlib import Path

import pytest

from tests.addon_kit import EXAMPLE, install
from tests.test_core import _client_with
from viewer_hub.addons import install as installer
from viewer_hub.addons.manifest import AddonError


@pytest.fixture()
def stop_addons():
    from viewer_hub.addons import runner

    yield
    runner._stop_all()


def _zip(tmp_path: Path, extra: dict[str, str] | None = None, manifest: dict | None = None, name="addon.zip") -> Path:
    files = {f"example/{p.relative_to(EXAMPLE).as_posix()}": p.read_bytes() for p in EXAMPLE.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts}
    if manifest:
        data = json.loads(files["example/addon.json"])
        data.update(manifest)
        files["example/addon.json"] = json.dumps(data).encode()
    files.update({f"example/{k}": v.encode() for k, v in (extra or {}).items()})
    out = tmp_path / name
    with zipfile.ZipFile(out, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return out


# ── upload checks ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["lib/CON.py", "lib/nul.txt", "lib/a?.py", "lib/end.", "lib/end "])
def test_names_windows_cannot_hold_are_refused(paths, tmp_path, bad):
    with pytest.raises(AddonError, match="Windows"):
        installer.install_zip(paths, _zip(tmp_path, {bad: "x"}))


def test_names_differing_only_by_case_are_refused(paths, tmp_path):
    with pytest.raises(AddonError, match="hoa / thường"):
        installer.install_zip(paths, _zip(tmp_path, {"lib/Util.py": "a", "lib/util.py": "b"}))


def test_taken_id_or_mcp_command_is_refused(paths, tmp_path):
    with pytest.raises(AddonError, match="trùng một mục có sẵn"):
        installer.install_zip(paths, _zip(tmp_path, manifest={"id": "csv"}).rename(tmp_path / "csv.zip"))
    with pytest.raises(AddonError, match="mcp.command"):
        manifest = json.loads((EXAMPLE / "addon.json").read_text())
        installer.install_zip(paths, _zip(tmp_path, manifest={"mcp": {**manifest["mcp"], "command": "search"}}))
    install(paths, "other-tool", command="greet")
    manifest = json.loads((EXAMPLE / "addon.json").read_text())
    with pytest.raises(AddonError, match="addon khác"):
        installer.install_zip(paths, _zip(tmp_path, manifest={"mcp": {**manifest["mcp"], "command": "greet"}}))


def test_signed_addon_is_not_replaced_by_an_unsigned_zip(paths, tmp_path):
    installer.install_zip(paths, _zip(tmp_path))
    (paths.addons / "example" / "signature.json").write_text("{}", encoding="utf-8")  # as if the installed one was signed
    with pytest.raises(AddonError, match="chưa ký"):
        installer.install_zip(paths, _zip(tmp_path, manifest={"version": "9.9.9"}))
    assert json.loads((paths.addons / "example" / "addon.json").read_text())["version"] != "9.9.9"


def test_guide_gaps_are_shown_not_refused(paths, tmp_path):
    result = installer.install_zip(paths, _zip(tmp_path, {"GUIDE.md": "## Ví dụ addon\n\nNo tool table."}))
    assert any("example_greet" in note for note in result.notes)


def test_a_bad_upload_never_stops_the_running_addon(paths, tmp_path, stop_addons):
    client = _client_with(paths)
    install(paths, "example")
    client.application.extensions["hub"].addons.refresh(force=True)
    assert client.get("/x/example/api/greetings").status_code == 200  # running now
    hub = client.application.extensions["hub"]
    runner = hub.addons.runner(hub.addons.get("example"))
    pid = runner.pid
    bad = _zip(tmp_path, {"lib/evil.py": "import os\nos.system('x')\n"}, manifest={"version": "0.9.0"})
    with bad.open("rb") as upload:
        reply = client.post("/api/addons", data={"file": (upload, "example.zip")},
                            headers={"X-Viewer-Hub": "1"}, content_type="multipart/form-data")
    assert reply.status_code == 400 and "bảo mật" in reply.get_json()["error"]["message"]
    assert runner.running() and runner.pid == pid  # still the same process


# ── a misbehaving addon ────────────────────────────────────────────────────────────────────────────────────────

SLOW = '''
import time
from viewer_hub.addons.sdk import Addon
addon = Addon("example", title="Slow")

@addon.get("/slow")
def slow(_request):
    time.sleep(8)
    return {"ok": True}

@addon.get("/greetings")
def fast(_request):
    return {"greetings": []}

if __name__ == "__main__":
    addon.run()
'''


def test_a_hung_addon_holds_a_few_threads_not_the_hub(paths, stop_addons, monkeypatch):
    from viewer_hub.addons import limits

    monkeypatch.setattr(limits, "WAIT", 0.5)
    install(paths, "example", files={"main.py": SLOW})
    client = _client_with(paths)
    assert client.get("/x/example/api/greetings").status_code == 200  # started
    replies = []
    workers = [threading.Thread(target=lambda: replies.append(client.get("/x/example/api/slow").status_code))
               for _ in range(limits.CALLS)]
    for worker in workers:
        worker.start()
    time.sleep(1)
    started = time.monotonic()
    busy = client.get("/x/example/api/greetings")  # every slot of this addon is taken
    assert busy.status_code == 503 and "bận" in busy.get_json()["error"]["message"]
    assert client.get("/api/app").status_code == 200  # the Hub itself answers at once
    assert time.monotonic() - started < 3
    for worker in workers:
        worker.join()
    assert replies == [200] * limits.CALLS
    assert client.get("/x/example/api/greetings").status_code == 200  # slots are given back


CRASH = '''
import sys
print("broken addon", flush=True)
sys.exit(3)
'''


def test_a_crashing_addon_is_not_restarted_on_every_request(paths, stop_addons):
    install(paths, "example", files={"main.py": CRASH})
    client = _client_with(paths)
    for _ in range(3):
        failed = client.get("/x/example/api/greetings")
        assert failed.status_code == 503 and "dừng ngay" in failed.get_json()["error"]["message"]
    started = time.monotonic()
    paused = client.get("/x/example/api/greetings")
    assert paused.status_code == 503 and "chờ" in paused.get_json()["error"]["message"]
    assert time.monotonic() - started < 1  # answered without starting it again
    assert client.get("/api/app").status_code == 200


def test_an_addon_flooding_its_log_is_stopped(paths, stop_addons, monkeypatch):
    from viewer_hub.addons import runner as runner_module

    install(paths, "example")
    client = _client_with(paths)
    assert client.get("/x/example/api/greetings").status_code == 200
    hub = client.application.extensions["hub"]
    runner = hub.addons.runner(hub.addons.get("example"))
    monkeypatch.setattr(runner_module, "LOG_FLOOD", 10)
    with runner.log_file.open("ab") as log:
        log.write(b"x" * 100)
    assert runner.check_log() and not runner.running()
    assert client.get("/x/example/api/greetings").status_code == 200  # the next use starts it with a fresh log


def test_stream_slots_are_given_back():
    from viewer_hub.addons import limits

    held = [limits.take("s-test", "stream") for _ in range(limits.STREAMS)]
    with pytest.raises(limits.Busy):
        limits.take("s-test", "stream")
    for slot in held:
        slot.release()
    limits.take("s-test", "stream").release()


def test_addon_process_gets_the_hub_import_path_absolute(monkeypatch, tmp_path):
    """The macOS/Linux release puts ``app`` (relative) on sys.path; an addon runs in its own folder, so the path it gets
    must not depend on the working directory (else: No module named 'viewer_hub')."""
    import sys

    from viewer_hub.addons import runner

    (tmp_path / "app").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", ["app", *sys.path])
    paths = runner._hub_paths()
    assert paths[0] == str((tmp_path / "app").resolve())
    assert all(Path(p).is_absolute() for p in paths)


def test_parent_watch_lets_the_addon_exit_cleanly_and_still_sees_the_hub_go():
    """The parent-watch thread blocked on stdin must not abort Python at exit (SIGABRT, a macOS crash report on every
    normal stop), and closing the Hub's pipe still ends the addon."""
    import os
    import subprocess
    import sys

    root = str(Path(__file__).resolve().parents[1])
    env = {**os.environ, "VIEWER_HUB_PARENT_PIPE": "1", "PYTHONPATH": root}
    start = "import time; from viewer_hub.addons.host import watch_parent; watch_parent(); "
    normal = subprocess.Popen([sys.executable, "-c", start + "time.sleep(0.3); raise SystemExit(0)"],
                              stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    err = normal.stderr.read()
    assert normal.wait(timeout=10) == 0, err.decode(errors="replace")
    normal.stdin.close()
    orphan = subprocess.Popen([sys.executable, "-c", start + "time.sleep(30)"], stdin=subprocess.PIPE, env=env)
    time.sleep(0.5)
    orphan.stdin.close()  # the Hub is gone
    assert orphan.wait(timeout=10) == 0
