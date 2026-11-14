from __future__ import annotations

import sqlite3

import pytest

from viewer_hub.core import backup, migrate
from viewer_hub.core.lock import AlreadyRunning, InstanceLock
from viewer_hub.core.migrate import Migration, open_hub
from viewer_hub.core.paths import HubPaths


def test_data_dir_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("VIEWER_HUB_HOME", str(tmp_path / "env"))
    assert HubPaths.resolve().home == (tmp_path / "env").resolve()
    assert HubPaths.resolve(tmp_path / "arg").home == (tmp_path / "arg").resolve()


def test_fresh_open_creates_schema(paths):
    state = open_hub(paths)
    assert not state.readonly
    assert state.db.schema_version == migrate.hub_schema()
    assert state.backup_path is None  # nothing to back up on first run
    state.db.close()


def test_newer_data_opens_readonly(paths):
    state = open_hub(paths)
    state.db.raw().execute("PRAGMA user_version = 999")
    state.db.close()
    again = open_hub(paths)
    assert again.readonly and "mới hơn" in again.reason
    with pytest.raises(Exception):
        with again.db.write() as db:
            db.execute("INSERT INTO settings VALUES ('a', 'b')")
    again.db.close()


def test_failed_migration_restores_backup(paths, monkeypatch):
    state = open_hub(paths)
    with state.db.write() as db:
        db.execute("INSERT INTO settings VALUES ('keep', 'me')")
    state.db.close()

    real = migrate.available()
    broken = Migration(real[-1].number + 1, "9999_broken.sql", "sql")
    monkeypatch.setattr(migrate, "available", lambda: [*real, broken])

    def explode(db, migration, paths_):
        if migration is broken:
            raise RuntimeError("boom")
        return original(db, migration, paths_)

    original = migrate._run
    monkeypatch.setattr(migrate, "_run", explode)
    result = open_hub(paths)
    assert result.readonly and "boom" in result.reason
    assert result.backup_path and result.backup_path.is_dir()
    assert result.db.one("SELECT value FROM settings WHERE key='keep'")["value"] == "me"
    assert result.db.schema_version == real[-1].number
    result.db.close()


def test_backup_and_restore_roundtrip(paths):
    state = open_hub(paths)
    with state.db.write() as db:
        db.execute("INSERT INTO settings VALUES ('v', '1')")
    saved = backup.create(paths, "test", "0")
    with state.db.write() as db:
        db.execute("UPDATE settings SET value='2' WHERE key='v'")
    state.db.close()
    backup.restore(paths, saved, "0")
    db = sqlite3.connect(paths.db)
    assert db.execute("SELECT value FROM settings WHERE key='v'").fetchone()[0] == "1"
    db.close()


def test_backups_are_pruned(paths):
    open_hub(paths).db.close()
    for _ in range(backup.KEEP + 2):
        backup.create(paths, "n", "0")
    assert len(backup.list_backups(paths)) == backup.KEEP


def test_single_instance(paths):
    first = InstanceLock(paths.lock)
    first.acquire({"version": "1", "url": "http://127.0.0.1:1/"})
    second = InstanceLock(paths.lock)
    with pytest.raises(AlreadyRunning) as info:
        second.acquire({"version": "2"})
    assert info.value.info["url"] == "http://127.0.0.1:1/"
    first.release()
    second.acquire({"version": "2"})
    second.release()


def test_repair_rebuilds_registry(paths, client):
    from viewer_hub.core.repair import repair
    import io

    assert client.post("/csv/api/datasets", data={"file": (io.BytesIO("a,b\n1,2\n".encode()), "x.csv")}).status_code == 200
    client.application.extensions["hub"].db.close()
    paths.db.unlink()
    message = repair(paths)
    assert "'datasets': 1" in message


def test_unreleased_features_are_not_named_in_the_ui(client):
    from pathlib import Path

    for url in ("/", "/premium", "/csv/?manage=1", "/ocr-search/", "/docs/", "/settings"):
        assert '<div id="app">' in client.get(url).data.decode(), url
    for url in ("/api/app", "/api/home", "/api/help"):
        text = client.get(url).data.decode().lower()
        assert "bridge" not in text and "box-mcp" not in text, url
    # The Hub's own bundles never name a premium feature: those are addons, with their own page file.
    dist = Path(__file__).resolve().parents[1] / "viewer_hub" / "static" / "dist"
    for bundle in dist.rglob("*.js"):
        assert "bridge" not in bundle.read_text(encoding="utf-8").lower(), bundle
    premium = (Path(__file__).resolve().parents[1] / "web" / "src" / "app" / "pages" / "Premium.jsx").read_text(encoding="utf-8")
    assert "Donate to unlock" in premium and "volunteer_activism" in premium


def test_help_page(client):
    guide = client.get("/api/help").get_json()
    assert "Hướng dẫn sử dụng Viewer Hub" in guide["title"] and '<md-icon class="md-help__icon"' in guide["html"]
    assert "[icon:" not in guide["html"] and guide["toc"]


def test_config_files_never_unlock_premium(paths, tmp_path):
    from viewer_hub.core.config import load, premium_enabled

    assert premium_enabled(load(paths, tmp_path), "bridge") is False
    paths.config.write_text("premium:\n  bridge: true\n", encoding="utf-8")
    (tmp_path / "viewer-hub.yaml").write_text("premium:\n  bridge: true\n", encoding="utf-8")
    assert premium_enabled(load(paths, tmp_path), "bridge") is False  # only an unlock code opens it


def _client_with(paths, premium: bool | set = False):
    """A test client; ``premium`` opens premium features the way a saved unlock code does (core/unlock.py): True =
    every one the installed modules and addons declare, or a set of names."""
    from viewer_hub.app.factory import create_wsgi
    from viewer_hub.core import config
    from viewer_hub.core.migrate import open_hub

    app = create_wsgi(paths, open_hub(paths))
    hub = app.extensions["hub"]
    if premium:
        names = premium if isinstance(premium, set) else {m.premium for m in hub.every_module if m.premium}
        config.unlock(hub.config, names)
    client = app.test_client()
    open_ = client.open
    client.open = lambda *a, **k: open_(*a, **{"base_url": "http://127.0.0.1/", **k})
    return client


def test_premium_locked_shows_only_donate(paths):
    from tests.addon_kit import install

    assert "Premium" not in [i["label"] for i in _client_with(paths).get("/api/app").get_json()["nav"]]  # none locked
    install(paths, "secret-tool", label="Công cụ bí mật", premium="secret")
    client = _client_with(paths, premium=False)
    app = client.get("/api/app").get_json()
    labels = [item["label"] for item in app["nav"]]
    assert "Premium" in labels and "Công cụ bí mật" not in labels and "CSV" in labels and app["locked"] is True
    assert app["scripts"] == {} and "secret" not in str(app)
    assert client.get("/premium").status_code == 200
    locked = client.get("/x/secret-tool")  # the real page does not exist while locked
    assert locked.status_code == 302 and locked.headers["Location"].rstrip("/").endswith("/premium")
    assert client.get("/x/secret-tool/api/greetings").status_code == 404
    assert client.get("/api/addons/secret-tool").status_code == 404
    listed = client.get("/api/addons").get_json()
    assert listed["locked"] == 1 and "secret" not in str(listed["addons"])
    assert "Công cụ bí mật" not in client.get("/api/help").get_json()["html"]


def test_premium_enabled_shows_real_name(paths):
    from tests.addon_kit import install

    install(paths, "secret-tool", label="Công cụ bí mật", premium="secret")
    client = _client_with(paths, premium=True)
    app = client.get("/api/app").get_json()
    paths_ = {item["label"]: item["path"] for item in app["nav"]}
    assert paths_.get("Công cụ bí mật") == "/x/secret-tool" and "CSV" in paths_
    assert "Premium" not in paths_ and app["locked"] is False  # nothing left locked: no anonymous Premium entry
    assert '<div id="app">' in client.get("/x/secret-tool").data.decode()
    assert client.get("/premium").headers["Location"].rstrip("/").endswith("/x/secret-tool")  # old bookmark


def test_cli_prints_vietnamese_on_a_cp1252_pipe():
    """Windows: a piped stdout is cp1252 / cp932 (just, redirects, CI) and -I ignores PYTHONUTF8."""
    import io

    from viewer_hub.core.text import utf8_output

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    utf8_output(stream)
    print("Dữ liệu 日本語", file=stream)
    stream.flush()
    assert raw.getvalue().decode("utf-8") == "Dữ liệu 日本語\n"
