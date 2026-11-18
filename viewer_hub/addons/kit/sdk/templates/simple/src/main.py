"""Template addon "my-addon" (managed, Python): an API for its page and two read-only MCP tools.

Viewer Hub starts it on first use with its own Python and relays /x/my-addon/api/* and /x/my-addon/mcp here.
Standard library only (+ pure-Python packages copied into lib/). It writes only under addon.data.
"""
import json
import time

from viewer_hub.addons.sdk import Addon, ApiError, ToolError

addon = Addon("notes", title="Ghi chú nhanh", instructions="Read the notes the user saved in Viewer Hub.")
STORE = addon.data / "notes.json"


def _load() -> list[dict]:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(notes: list[dict]) -> None:
    addon.data.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE)


@addon.get("/notes")
def list_notes(_request):
    return {"title": addon.settings().get("title") or "Ghi chú", "notes": _load()}


@addon.post("/notes")
def add_note(request):
    text = str((request.body or {}).get("text") or "").strip()
    if not text or len(text) > 2000:
        raise ApiError("bad_text", "Ghi chú phải có nội dung (tối đa 2000 ký tự)")
    notes = _load()
    note = {"id": int(time.time() * 1000), "text": text, "at": time.strftime("%Y-%m-%d %H:%M")}
    _save([note, *notes])
    return {"note": note}


@addon.delete("/notes/<note_id>")
def delete_note(request):
    notes = _load()
    kept = [n for n in notes if str(n["id"]) != request.params["note_id"]]
    if len(kept) == len(notes):
        raise ApiError("not_found", "Không có ghi chú này", 404)
    _save(kept)
    return {}


@addon.tool("notes_list", "List the saved notes (id, date, first line).")
def notes_list(_arguments):
    notes = _load()
    if not notes:
        return "No notes."
    return "\n".join(f"{n['id']}  {n['at']}  {n['text'].splitlines()[0][:80]}" for n in notes)


@addon.tool("notes_read", "Full text of one note by id (from notes_list).",
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})
def notes_read(arguments):
    for note in _load():
        if str(note["id"]) == str(arguments.get("id")):
            return note["text"]
    raise ToolError(f"no note with id {arguments.get('id')}")


if __name__ == "__main__":
    addon.run()
