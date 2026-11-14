from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from viewer_hub.core.migrate import open_hub
from viewer_hub.docs.store import SiteStore, safe_relative
from viewer_hub.packs.builder import build as build_pack
from viewer_hub.packs.importer import PackError, import_pack


def test_safe_relative():
    assert safe_relative("a/b.md").as_posix() == "a/b.md"
    for bad in ("../x.md", "/etc/x", "a/../../x", "C:/x.md", ".git/config", "a\\..\\b"):
        assert safe_relative(bad) is None


def _post_site(client, files, title="Spec"):
    data = {"title": title, "file": [(io.BytesIO(body), name) for name, body in files]}
    return client.post("/docs/api/sites", data=data, content_type="multipart/form-data")


def test_site_from_folder_builds_material_site(client, paths):
    files = [("spec/index.md", b"# Trang chu\n\nXin chao"), ("spec/guide/setup.md", b"# Cai dat\n"),
             ("spec/evil.exe", b"MZ"), ("spec/.hidden.md", b"#x")]
    response = _post_site(client, files)
    assert response.status_code == 200 and response.get_json()["ok"] and response.get_json()["site"]["viewUrl"]
    site = SiteStore(paths.sites, paths.tmp).list()[0]
    assert site.built and site.meta["pages"] >= 2
    assert not list(site.src.rglob("*.exe")) and not (site.src / ".hidden.md").exists()
    # User content lives on the content origin only.
    redirect = client.get(f"/docs/{site.id}/view/")
    assert redirect.status_code == 302 and redirect.headers["Location"].startswith("http://localhost/")
    page = client.get(f"/docs/{site.id}/view/", headers={"Host": "localhost"})
    assert page.status_code == 200 and b"md-header" in page.data  # mkdocs-material markup
    assert "default-src 'self'" in page.headers["Content-Security-Policy"]
    assert b"fonts.googleapis.com" not in page.data
    assert b"md-nav--integrated" in page.data and b"md-tabs" not in page.data  # one menu: headings inside the left nav
    assert client.get(f"/docs/{site.id}/view/../../site.json", headers={"Host": "localhost"}).status_code == 404
    # App pages are never served on the content origin; unknown hosts are refused.
    assert client.get("/csv/", headers={"Host": "localhost"}).status_code == 302
    assert client.post("/csv/api/datasets", headers={"Host": "localhost"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_mkdocs_hooks_and_plugins_are_dropped(client, paths):
    cfg = b"site_name: Mine\nhooks: [evil.py]\nplugins: [search, macros]\nmarkdown_extensions: [admonition, evil.ext]\n"
    _post_site(client, [("mkdocs.yml", cfg), ("docs/index.md", b"# Hi"), ("evil.py", b"print(1)")])
    site = SiteStore(paths.sites, paths.tmp).list()[0]
    assert site.built and site.meta["buildError"] is None
    assert not (site.src / "evil.py").exists()  # .py is not an allowed file type


def test_site_from_zip(client, paths):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("index.md", "# Zip\n")
        z.writestr("../escape.md", "# no\n")
    _post_site(client, [("site.zip", buffer.getvalue())], title="Zip")
    site = SiteStore(paths.sites, paths.tmp).list()[0]
    assert site.built and not (paths.sites / "escape.md").exists()


def _make_pack(tmp_path, search_db, **extra):
    out = tmp_path / "p.sapack"
    build_pack(out, "core", "Core", "1.0", search=search_db)
    if extra:
        with zipfile.ZipFile(out, "a") as z:
            for name, body in extra.items():
                z.writestr(name, body)
    return out


def test_pack_roundtrip_and_search(tmp_path, paths, search_db):
    pack = _make_pack(tmp_path, search_db)
    search_db.unlink()  # only the pack provides search now
    state = open_hub(paths)
    manifest = import_pack(paths, state.db, pack)
    assert manifest["components"]["search"]["docCount"] == 3
    assert (paths.packs / "core" / "1.0" / "search" / "search.sqlite").is_file()
    with pytest.raises(PackError):
        import_pack(paths, state.db, pack)  # same version twice
    state.db.close()


@pytest.mark.parametrize("name", ["../x.json", "tools/run.exe", "a/b.ps1"])
def test_pack_rejects_unsafe_members(tmp_path, paths, search_db, name):
    pack = _make_pack(tmp_path, search_db, **{name: "x"})
    state = open_hub(paths)
    with pytest.raises(PackError):
        import_pack(paths, state.db, pack)
    assert not (paths.packs / "core").exists()
    state.db.close()


def test_pack_checksum_mismatch(tmp_path, paths, search_db):
    out = tmp_path / "bad.sapack"
    manifest = {"format": 1, "id": "bad", "version": "1", "title": "B", "components": {"search": {}},
                "sha256": {"search/search.sqlite": "0" * 64}}
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("pack.json", json.dumps(manifest))
        z.write(search_db, "search/search.sqlite")
    state = open_hub(paths)
    with pytest.raises(PackError, match="checksum"):
        import_pack(paths, state.db, out)
    state.db.close()


def test_old_builds_are_rebuilt_on_view(client, paths):
    _post_site(client, [("index.md", b"# A\n\n## B\n")])
    site = SiteStore(paths.sites, paths.tmp).list()[0]
    site.meta["buildProfile"] = 1
    site.save()
    client.get(f"/docs/{site.id}/view/", headers={"Host": "localhost"})
    assert SiteStore(paths.sites, paths.tmp).get(site.id).meta["buildProfile"] >= 2


def test_bundled_packs_are_imported_once(tmp_path, paths, search_db):
    from viewer_hub.packs.bundled import import_bundled

    folder = tmp_path / "bundled"
    folder.mkdir()
    _make_pack(tmp_path, search_db).rename(folder / "core.sapack")
    state = open_hub(paths)
    assert import_bundled(paths, state.db, folder) == ["core 1.0"]
    assert import_bundled(paths, state.db, folder) == []  # already there: nothing to do
    assert state.db.one("SELECT active FROM packs WHERE id='core'")["active"] == 1
    state.db.close()


def test_import_pack_from_settings(client, tmp_path, search_db):
    pack = _make_pack(tmp_path, search_db)
    with open(pack, "rb") as handle:
        response = client.post("/api/settings/import", data={"file": (handle, "core.sapack")})
    assert response.status_code == 200 and "Core" in response.get_json()["message"]
    packs = client.get("/api/settings").get_json()["packs"]
    assert [(p["id"], p["active"]) for p in packs] == [("core", True)]


# ── Review: importing a pack never overwrites user data or newer pack data ───────────

def _pack_version(tmp_path, search_db, version):
    out = tmp_path / f"core-{version}.sapack"
    build_pack(out, "core", "Core", version, search=search_db)
    return out


def test_import_keeps_user_data_and_old_versions(client, paths, tmp_path, search_db):
    import io as _io

    client.post("/csv/api/datasets", data={"file": (_io.BytesIO(b"a,b\n1,2\n"), "mine.csv")})
    knowledge = paths.user / "codemap" / "core" / "knowledge.sqlite"
    knowledge.parent.mkdir(parents=True)
    knowledge.write_bytes(b"user notes")
    before = {p: p.read_bytes() for p in [*paths.workspace.rglob("*"), knowledge] if p.is_file()}
    db = client.application.extensions["hub"].db
    for version in ("1.0", "1.1"):
        import_pack(paths, db, _pack_version(tmp_path, search_db, version))
    after = {p: p.read_bytes() for p in before}
    assert after == before  # CSV, its index and the user's knowledge are byte-identical
    assert (paths.packs / "core" / "1.0").is_dir() and (paths.packs / "core" / "1.1").is_dir()
    assert db.one("SELECT version FROM packs WHERE id='core' AND active=1")["version"] == "1.1"


def test_older_pack_is_imported_but_not_activated(paths, tmp_path, search_db):
    from viewer_hub.packs.importer import version_key

    state = open_hub(paths)
    import_pack(paths, state.db, _pack_version(tmp_path, search_db, "2026.12.1"))
    older = import_pack(paths, state.db, _pack_version(tmp_path, search_db, "2026.11.30"))
    assert older["activated"] is False and "cũ hơn" in older["reason"]
    assert state.db.one("SELECT version FROM packs WHERE id='core' AND active=1")["version"] == "2026.12.1"
    assert version_key("1.10") > version_key("1.9") and version_key("2026.11.13-fk") > version_key("2026.11.13")
    state.db.close()


def test_bundled_older_pack_does_not_replace_newer(paths, tmp_path, search_db):
    from viewer_hub.packs.bundled import import_bundled

    state = open_hub(paths)
    import_pack(paths, state.db, _pack_version(tmp_path, search_db, "2.0"))
    folder = tmp_path / "bundled"
    folder.mkdir()
    _pack_version(tmp_path, search_db, "1.0").rename(folder / "core.sapack")
    assert import_bundled(paths, state.db, folder) == ["core 1.0 (cũ hơn bản đang dùng, chưa bật)"]
    assert state.db.one("SELECT version FROM packs WHERE id='core' AND active=1")["version"] == "2.0"
    state.db.close()


def test_switch_back_to_previous_version(client, paths, tmp_path, search_db):
    db = client.application.extensions["hub"].db
    for version in ("1.0", "1.1"):
        import_pack(paths, db, _pack_version(tmp_path, search_db, version))
    reply = client.post("/api/settings/packs/activate", json={"id": "core", "version": "1.0"})
    assert "Đang dùng core 1.0" in reply.get_json()["message"]
    assert db.one("SELECT version FROM packs WHERE id='core' AND active=1")["version"] == "1.0"
    packs = {p["version"]: p["active"] for p in client.get("/api/settings").get_json()["packs"]}
    assert packs == {"1.0": True, "1.1": False}  # the other version stays, for "Dùng bản này"


def test_readonly_and_reserved_and_leftovers(paths, tmp_path, search_db):
    from viewer_hub.core.db import HubDB

    state = open_hub(paths)
    out = tmp_path / "local.sapack"
    build_pack(out, "local", "Local", "1", search=search_db)
    with pytest.raises(PackError, match="dành riêng"):
        import_pack(paths, state.db, out)
    # A folder left by an import that never registered is replaced, not a dead end.
    stale = paths.packs / "core" / "1.0"
    stale.mkdir(parents=True)
    (stale / "junk.txt").write_text("x")
    import_pack(paths, state.db, _pack_version(tmp_path, search_db, "1.0"))
    assert not (stale / "junk.txt").exists() and (stale / "pack.json").is_file()
    state.db.close()
    readonly = HubDB(paths.db, readonly=True)
    with pytest.raises(PackError, match="chỉ đọc"):
        import_pack(paths, readonly, _pack_version(tmp_path, search_db, "9.9"))
    assert not (paths.packs / "core" / "9.9").exists()
    readonly.close()


def test_repair_activates_newest_version(paths, tmp_path, search_db):
    from viewer_hub.core.repair import repair

    state = open_hub(paths)
    for version in ("1.9", "1.10"):
        import_pack(paths, state.db, _pack_version(tmp_path, search_db, version))
    state.db.close()
    repair(paths)
    state = open_hub(paths)
    assert state.db.one("SELECT version FROM packs WHERE id='core' AND active=1")["version"] == "1.10"
    state.db.close()


# ── CSV and docs inside a data pack ─────────────────────────────────────────────────

def _content_pack(tmp_path, search_db, version="1.0"):
    csv = tmp_path / "nhan-vien.csv"
    csv.write_text("Mã,Tên,Phòng\nNV1,An,Kế toán\nNV2,Bình,Kỹ thuật\n", encoding="utf-8")
    docs = tmp_path / "so-tay"
    (docs / "guide").mkdir(parents=True, exist_ok=True)
    (docs / "index.md").write_text("# Sổ tay\n\n## Mục\n", encoding="utf-8")
    (docs / "guide" / "a.md").write_text("# A\n", encoding="utf-8")
    out = tmp_path / f"content-{version}.sapack"
    manifest = build_pack(out, "core", "Core", version, csv=[csv], docs=[docs])
    assert manifest["components"]["csv"][0]["rows"] == 2 and manifest["components"]["docs"][0]["pages"] >= 2
    return out


def test_pack_csv_is_listed_read_only_next_to_user_csv(client, paths, tmp_path, search_db):
    import io as _io

    # The user already has a dataset with the same name: the pack must not replace it.
    client.post("/csv/api/datasets", data={"file": (_io.BytesIO("x\n1\n".encode()), "nhan-vien.csv")})
    import_pack(paths, client.application.extensions["hub"].db, _content_pack(tmp_path, search_db))
    from viewer_hub.csv.store import CsvStore
    from viewer_hub.packs.content import pack_dirs

    datasets = CsvStore(paths.csv, paths.tmp, packs=pack_dirs(client.application.extensions["hub"], "csv")).list()
    ids = {d.id: d for d in datasets}
    assert "nhan-vien" in ids and not ids["nhan-vien"].readonly  # user's own, untouched
    assert ids["nhan-vien"].meta["rows"] == 1
    assert "core--nhan-vien" in ids and ids["core--nhan-vien"].readonly
    rows = client.get("/csv/api/datasets/core--nhan-vien/rows", query_string={"q": "Bình"}).json
    assert rows["total"] == 1
    info = client.get("/csv/api/datasets/core--nhan-vien").get_json()
    assert info["pack"] == "Core" and info["readonly"] is True  # the page hides edit and delete
    assert client.patch("/csv/api/datasets/core--nhan-vien", json={"title": "x"}).status_code == 403
    assert client.put("/csv/api/datasets/core--nhan-vien/columns", json={"columns": []}).status_code == 403
    assert client.delete("/csv/api/datasets/core--nhan-vien").status_code == 403
    assert (paths.packs / "core" / "1.0" / "csv" / "nhan-vien" / "data.sqlite").is_file()


def test_pack_docs_site_is_prebuilt_and_read_only(client, paths, tmp_path, search_db):
    import_pack(paths, client.application.extensions["hub"].db, _content_pack(tmp_path, search_db))
    listing = {s["id"]: s for s in client.get("/docs/api/sites").get_json()["sites"]}
    assert listing["core--so-tay"]["pack"] == "Core" and listing["core--so-tay"]["readonly"]
    page = client.get("/docs/core--so-tay/view/", headers={"Host": "localhost"})
    assert page.status_code == 200 and b"md-header" in page.data
    assert client.post("/docs/api/sites/core--so-tay/rebuild").status_code == 403
    assert client.delete("/docs/api/sites/core--so-tay").status_code == 403
    detail = client.get("/docs/api/sites/core--so-tay").get_json()["site"]
    assert detail["readonly"] and detail["built"]  # the page shows "chỉ đọc", no "Build lại"
    assert not list((paths.packs / "core" / "1.0" / "docs").rglob("*.gz"))


def test_new_pack_version_switches_pack_csv_and_keeps_old(client, paths, tmp_path, search_db):
    db = client.application.extensions["hub"].db
    import_pack(paths, db, _content_pack(tmp_path, search_db, "1.0"))
    import_pack(paths, db, _content_pack(tmp_path, search_db, "1.1"))
    from viewer_hub.csv.store import CsvStore
    from viewer_hub.packs.content import pack_dirs

    datasets = [d for d in CsvStore(paths.csv, paths.tmp, packs=pack_dirs(client.application.extensions["hub"], "csv")).list() if d.readonly]
    assert len(datasets) == 1 and "/1.1/" in datasets[0].folder.as_posix()
    assert (paths.packs / "core" / "1.0" / "csv").is_dir()  # old version kept for "Dùng bản này"


def test_pack_id_with_double_dash_is_rejected(tmp_path, paths, search_db):
    out = tmp_path / "bad.sapack"
    build_pack(out, "a--b", "x", "1", search=search_db)
    state = open_hub(paths)
    with pytest.raises(PackError, match="--"):
        import_pack(paths, state.db, out)
    state.db.close()


def test_images_in_markdown_are_served(client, paths):
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
           b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'
    files = [("spec/index.md", b"# A\n\n![so do](img/flow.png)\n\n![icon](img/logo.svg)\n"),
             ("spec/img/flow.png", png), ("spec/img/logo.svg", svg)]
    assert _post_site(client, files).status_code == 200
    site = SiteStore(paths.sites, paths.tmp).list()[0]
    page = client.get(f"/docs/{site.id}/view/", headers={"Host": "localhost"})
    assert b'src="img/flow.png"' in page.data
    image = client.get(f"/docs/{site.id}/view/img/flow.png", headers={"Host": "localhost"})
    assert image.status_code == 200 and image.mimetype == "image/png"
    assert client.get(f"/docs/{site.id}/view/img/logo.svg", headers={"Host": "localhost"}).status_code == 200


def test_release_input_folder_makes_a_pack(tmp_path):
    """packaging/input (shipped in every release as input/): its pack.yaml and the config.json shown in its
    README.md work as written."""
    import json
    import re
    import shutil
    import zipfile

    from viewer_hub.packs.builder import InputError, build_from_input

    source = Path(__file__).resolve().parents[1] / "packaging" / "input"
    folder = tmp_path / "input"
    shutil.copytree(source, folder)
    with pytest.raises(InputError, match="chưa có dữ liệu"):  # only the README and pack.yaml: says what is missing
        build_from_input(folder, tmp_path / "dist")
    readme = (source / "README.md").read_text(encoding="utf-8")
    config = json.loads(re.search(r"```json\n(.*?)```", readme, re.S).group(1))
    (folder / "csv").mkdir()
    (folder / "csv" / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    (folder / "csv" / "nhan-vien.csv").write_bytes("ma_nv,ho_ten,phong\n1,山田太郎,A\n".encode("cp932"))
    (folder / "docs" / "Hướng dẫn").mkdir(parents=True)
    (folder / "docs" / "Hướng dẫn" / "index.md").write_text("# Xin chào\n", encoding="utf-8")
    out = build_from_input(folder, tmp_path / "dist")
    assert out.name.startswith("my-project-")
    with zipfile.ZipFile(out) as archive:
        manifest = json.loads(archive.read("pack.json"))
        meta = json.loads(next(archive.read(n) for n in archive.namelist() if n.startswith("csv/") and n.endswith("dataset.json")))
    assert manifest["components"]["csv"][0]["title"] == "Nhân viên"
    assert manifest["components"]["docs"][0]["title"] == "Hướng dẫn"
    assert meta["description"].startswith("Danh sách nhân viên")
