"""Copilot skills synced into the project folders listed in Settings (app/copilot_sync.py)."""
from __future__ import annotations

from viewer_hub.app import copilot_sync, mcp_export


def test_settings_save_syncs_and_keeps_the_users_own_skills(client, tmp_path):
    repo = tmp_path / "repo"
    skills = repo / ".github" / "skills"
    (skills / "my-own").mkdir(parents=True)
    (skills / "my-own" / "SKILL.md").write_text("---\nname: my-own\n---\nmine\n", encoding="utf-8")
    (skills / "viewer-csv").mkdir()
    (skills / "viewer-csv" / "SKILL.md").write_text("hand-written csv skill", encoding="utf-8")  # same name, no marker
    (skills / "viewer-gone").mkdir()
    (skills / "viewer-gone" / "SKILL.md").write_text(f"---\n---\n{mcp_export.MARKER}\nold\n", encoding="utf-8")

    assert client.put("/api/settings/copilot", json={"folders": ["relative/path"]}).status_code == 400
    assert client.put("/api/settings/copilot", json={"folders": [str(tmp_path / "missing")]}).status_code == 400

    reply = client.put("/api/settings/copilot", json={"folders": [str(repo), f" {repo} "]})
    assert reply.status_code == 200, reply.get_data(as_text=True)
    folders = reply.get_json()["folders"]
    assert [folder["path"] for folder in folders] == [str(repo.resolve())]
    last = folders[0]["last"]
    assert "viewer-gone" in last["removed"] and not (skills / "viewer-gone").exists()
    assert (skills / "my-own" / "SKILL.md").read_text(encoding="utf-8").endswith("mine\n")
    assert (skills / "viewer-csv" / "SKILL.md").read_text(encoding="utf-8") == "hand-written csv skill"
    written = {path.parent.name for path in skills.glob("*/SKILL.md") if mcp_export.MARKER in path.read_text(encoding="utf-8")}
    assert written and written == set(last["written"])

    # Nothing changed: a second sync writes nothing; the page shows the last result.
    again = client.put("/api/settings/copilot", json={"folders": [str(repo)]}).get_json()["folders"][0]["last"]
    assert again["written"] == [] and again["removed"] == []
    assert client.get("/api/settings/copilot").get_json()["folders"][0]["last"]["at"] == again["at"]


def test_start_sync_reports_a_missing_folder(app, tmp_path):
    hub = app.extensions["hub"]
    gone = tmp_path / "unplugged"
    results = copilot_sync.sync(hub.db, hub.modules, [str(gone)])
    assert "Không tìm thấy folder" in results[str(gone)]["error"]


def test_skills_zip_carries_the_marker(client):
    import io
    import zipfile

    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/mcp/skills.zip").data))
    assert all(mcp_export.MARKER in archive.read(name).decode("utf-8") for name in archive.namelist())
