"""Managed addons that run on .NET (addon.json "runtime": "dotnet"): the Hub starts `dotnet <entry>.dll serve --port N`
and allows managed assemblies (.dll) in the zip, never an .exe or a native library (core/scan.py)."""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from tests.test_addon_sdk import KIT
from viewer_hub.addons import runner
from viewer_hub.addons.manifest import AddonError, parse
from viewer_hub.core.scan import is_managed_assembly, scan_addon

MANIFEST = {"schema": "viewer-hub/addon", "schemaVersion": 3, "sdk": "1", "id": "dbq", "name": "DB Query", "version": "0.1.0",
            "runtime": "dotnet", "entry": "DbQuery.dll", "lifecycle": "managed",
            "menu": {"label": "DB", "icon": "database", "summary": "x"}}


def _pe(managed: bool, *, pe32: bool = False) -> bytes:
    """The smallest PE file the check reads: DOS header → "PE\\0\\0" → COFF → optional header with 16 data directories,
    the CLR one (index 14) set only for a .NET assembly."""
    dos = bytearray(64)
    dos[:2] = b"MZ"
    dos[0x3C:0x40] = struct.pack("<I", 64)
    optional_size = 224 if pe32 else 240
    coff = struct.pack("<HHIIIHH", 0x14C if pe32 else 0x8664, 1, 0, 0, 0, optional_size, 0x2022)
    optional = bytearray(optional_size)
    optional[:2] = struct.pack("<H", 0x10B if pe32 else 0x20B)
    directories = 96 if pe32 else 112
    optional[directories - 4:directories] = struct.pack("<I", 16)
    if managed:
        optional[directories + 14 * 8:directories + 14 * 8 + 8] = struct.pack("<II", 0x2008, 0x48)
    return bytes(dos) + b"PE\0\0" + coff + bytes(optional)


def _addon(tmp_path: Path, files: dict[str, bytes], runtime: str = "dotnet") -> Path:
    folder = tmp_path / "dbq"
    folder.mkdir()
    (folder / "addon.json").write_text(json.dumps({**MANIFEST, "runtime": runtime,
                                                   **({"entry": "main.mjs"} if runtime == "node" else {})}), encoding="utf-8")
    for rel, data in files.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return folder


def test_manifest_accepts_a_dll_entry_only():
    addon = parse(MANIFEST)
    assert (addon.runtime, addon.entry, addon.lifecycle) == ("dotnet", "DbQuery.dll", "managed")
    for bad in ("main.py", "DbQuery.exe", "sub/DbQuery.dll", "../x.dll"):
        with pytest.raises(AddonError, match="entry"):
            parse({**MANIFEST, "entry": bad})
    with pytest.raises(AddonError, match="dotnet"):
        parse({**MANIFEST, "runtime": "java"})


def test_pe_check_tells_assemblies_from_native_libraries(tmp_path):
    for name, data, expected in (("net.dll", _pe(True), True), ("net32.dll", _pe(True, pe32=True), True),
                                 ("native.dll", _pe(False), False), ("native32.dll", _pe(False, pe32=True), False),
                                 ("text.dll", b"hello", False), ("mz.dll", b"MZ", False), ("empty.dll", b"", False)):
        path = tmp_path / name
        path.write_bytes(data)
        assert is_managed_assembly(path) is expected, name


def test_scan_allows_managed_assemblies_for_dotnet_addons_with_a_note(tmp_path):
    folder = _addon(tmp_path, {"app/DbQuery.dll": _pe(True), "app/Oracle.ManagedDataAccess.dll": _pe(True),
                               "app/DbQuery.runtimeconfig.json": b"{}", "ui/ui.js": b"export default () => null;\n"})
    errors, notes = scan_addon(folder)
    assert errors == []
    assert any("2 assembly" in n and ".NET" in n for n in notes)


def test_scan_still_refuses_everything_else_native(tmp_path):
    folder = _addon(tmp_path, {"app/DbQuery.dll": _pe(True), "app/native.dll": _pe(False), "app/DbQuery.exe": _pe(True),
                               "app/lib/x.so": b"\x7fELF", "app/lib/y.node": b"x"})
    errors, _notes = scan_addon(folder)
    assert sorted(e.split(":")[0] for e in errors) == ["app/DbQuery.exe", "app/lib/x.so", "app/lib/y.node", "app/native.dll"]
    assert any("chỉ được kèm assembly .NET" in e for e in errors if e.startswith("app/native.dll"))


def test_a_dll_is_still_refused_when_the_addon_is_not_dotnet(tmp_path):
    for runtime in ("node", "python"):
        folder = _addon(tmp_path / runtime if (tmp_path / runtime).exists() else tmp_path, {"app/Lib.dll": _pe(True)}, runtime)
        errors, _ = scan_addon(folder)
        assert errors == ["app/Lib.dll: file thực thi / native"], runtime
        shutil.rmtree(folder)


def test_runner_starts_dotnet_with_the_machines_runtime(tmp_path, monkeypatch):
    folder = _addon(tmp_path, {"app/DbQuery.dll": _pe(True)})
    managed = runner.Managed(parse(MANIFEST, folder), tmp_path / "data", tmp_path / "logs")
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/dotnet" if name == "dotnet" else None)
    assert managed.problem() == ""
    assert managed.program() == ["/usr/bin/dotnet", str(folder / "app" / "DbQuery.dll")]
    assert managed.env()["DOTNET_CLI_TELEMETRY_OPTOUT"] == "1"
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    assert ".NET 8+" in managed.problem()   # the page shows this instead of starting anything


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_sdk_check_matches_the_hub_for_dotnet_addons(tmp_path):
    folder = _addon(tmp_path, {"app/DbQuery.dll": _pe(True), "app/native.dll": _pe(False)})
    build = (KIT / "sdk" / "build.mjs").as_uri()
    script = (f"import {{ scan }} from {json.dumps(build)};\n"
              "const r = scan(process.argv[1]); console.log(JSON.stringify([r.errors, r.notes]));")
    out = subprocess.run(["node", "--input-type=module", "-e", script, str(folder)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    js_errors, js_notes = json.loads(out.stdout)
    errors, notes = scan_addon(folder)
    assert js_errors == errors and len(js_notes) == len(notes) == 1


RECORDS = {"key": "connections", "label": "Kết nối", "type": "records", "fields": [
    {"key": "name", "label": "Tên", "required": True},
    {"key": "mode", "label": "Kiểu", "type": "select", "options": ["Service name", "SID", "TNS"]},
    {"key": "host", "label": "Host", "showWhen": {"mode": ["Service name", "SID"]}},
    {"key": "tns", "label": "Chuỗi TNS", "showWhen": {"mode": ["TNS"]}}]}


def test_records_setting_is_declared_with_fields():
    addon = parse({**MANIFEST, "settings": [RECORDS]})
    setting = addon.settings[0]
    assert setting.type == "records" and [f["key"] for f in setting.fields] == ["name", "mode", "host", "tns"]
    assert setting.public()["fields"][2]["showWhen"] == {"mode": ["Service name", "SID"]}
    bad = [{**RECORDS, "fields": []}, {k: v for k, v in RECORDS.items() if k != "fields"},
           {**RECORDS, "fields": [{"key": "a", "label": "A", "type": "number"}]},
           {**RECORDS, "fields": [{"key": "a", "label": "A", "type": "select"}]},
           {**RECORDS, "fields": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]},
           {**RECORDS, "fields": [{"key": "a", "label": "A", "showWhen": {"zzz": ["x"]}}]}]
    for setting in bad:
        with pytest.raises(AddonError):
            parse({**MANIFEST, "settings": [setting]})


def test_records_setting_is_cleaned_on_save(paths):
    from viewer_hub.addons.registry import Registry
    registry = Registry(paths)
    addon = parse({**MANIFEST, "settings": [RECORDS]})
    saved = registry.save_settings(addon, {"connections": [
        {"name": " DEV ", "mode": "SID", "host": "10.0.0.5", "tns": "", "extra": "dropped"},
        {"name": "", "mode": "", "host": "", "tns": ""},  # empty row: dropped
        "DEV | old line"]})  # a line from before the fields: kept
    assert saved["connections"] == [{"name": "DEV", "mode": "SID", "host": "10.0.0.5", "tns": ""}, "DEV | old line"]
    with pytest.raises(AddonError, match="chọn một trong"):
        registry.save_settings(addon, {"connections": [{"name": "x", "mode": "Telnet"}]})
    with pytest.raises(AddonError):
        registry.save_settings(addon, {"connections": "not a list"})
