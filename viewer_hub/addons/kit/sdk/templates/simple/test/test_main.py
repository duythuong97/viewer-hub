"""Tests of the template addon without a Hub: npm test (the Hub's real SDK from .sdk/python, data in a temp folder)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

DATA = tempfile.mkdtemp()
os.environ["VIEWER_HUB_ADDON_DATA"] = DATA  # before importing main: Addon() reads it

import main  # noqa: E402

addon = main.addon


def call_tool(name, arguments=None):
    reply = addon.handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": arguments or {}}})
    result = reply["result"]
    return result.get("isError", False), result["content"][0]["text"]


class NotesTest(unittest.TestCase):
    def test_add_list_read_delete(self):
        status, body = addon.handle_api("POST", "/notes", {}, {"text": "Họp lúc 3 giờ"}, {})
        self.assertEqual(status, 200)
        note_id = str(body["note"]["id"])
        status, body = addon.handle_api("GET", "/notes", {}, None, {})
        self.assertEqual([n["text"] for n in body["notes"]], ["Họp lúc 3 giờ"])
        self.assertEqual(call_tool("notes_read", {"id": note_id}), (False, "Họp lúc 3 giờ"))
        self.assertEqual(addon.handle_api("DELETE", f"/notes/{note_id}", {}, None, {})[0], 200)
        self.assertEqual(call_tool("notes_list"), (False, "No notes."))

    def test_errors(self):
        status, body = addon.handle_api("POST", "/notes", {}, {"text": ""}, {})
        self.assertEqual((status, body["error"]["code"]), (400, "bad_text"))
        self.assertTrue(call_tool("notes_read", {"id": "nope"})[0])
        names = [t["name"] for t in addon.handle_mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
        self.assertEqual(names, json.loads(Path("addon/addon.json").read_text(encoding="utf-8"))["mcp"]["tools"])


if __name__ == "__main__":
    unittest.main()
