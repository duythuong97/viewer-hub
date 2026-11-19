from __future__ import annotations

import io
import zipfile


def test_config_uses_request_address(client):
    config = client.get("/api/mcp/config").get_json()
    assert config["servers"], "builtin MCP servers are listed"
    for name, server in config["servers"].items():
        assert name.startswith("viewer-") and server["type"] == "http"
        assert server["url"].startswith("http://") and server["url"].endswith("/mcp")


def test_skills_zip_has_one_skill_per_server(client):
    servers = client.get("/api/mcp/config").get_json()["servers"]
    reply = client.get("/api/mcp/skills.zip")
    assert reply.mimetype == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(reply.data))
    assert sorted(archive.namelist()) == sorted(f"{name}/SKILL.md" for name in servers)
    text = archive.read("viewer-csv/SKILL.md").decode("utf-8")
    assert text.startswith("---\nname: viewer-csv\ndescription: ")
    assert "`csv_search`" in text  # tool table comes from GUIDE.md
