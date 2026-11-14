"""A daemon addon's admin channel: a Windows named pipe or a Unix socket of the same OS user, never a TCP port.

Only programs of the same user reach it, so every call runs as the owner. The addon names the channel in its
``status --json`` reply (``adminChannel``); see runner.py.

Protocol (my-bridge src/api/admin-channel.ts): one JSON line per request, one JSON line back ({"status", "body"});
{"method": "EVENTS"} streams one JSON line per event until closed.
"""
from __future__ import annotations

import json
import socket
import sys
from contextlib import contextmanager
from typing import Any, Iterator

TIMEOUT = 30.0
MAX_REPLY = 16 * 1024 * 1024


class Unavailable(Exception):
    """The daemon is not running (or not reachable on this channel)."""


class _Pipe:
    """A Windows named pipe opened as a file: write a line, read until EOF or a newline."""

    def __init__(self, where: str) -> None:
        try:
            self._file = open(where, "r+b", buffering=0)  # noqa: SIM115  (closed in close())
        except OSError as exc:
            raise Unavailable(str(exc)) from exc

    def send(self, data: bytes) -> None:
        self._file.write(data)

    def recv(self, size: int) -> bytes:
        try:
            return self._file.read(size) or b""
        except OSError:
            return b""

    def close(self) -> None:
        self._file.close()


class _Socket:
    def __init__(self, where: str, timeout: float | None) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        try:
            self._sock.connect(where)
        except OSError as exc:
            self._sock.close()
            raise Unavailable(str(exc)) from exc

    def send(self, data: bytes) -> None:
        self._sock.sendall(data)

    def recv(self, size: int) -> bytes:
        return self._sock.recv(size)

    def close(self) -> None:
        self._sock.close()


@contextmanager
def _connect(where: str, timeout: float | None) -> Iterator[Any]:
    if not where:
        raise Unavailable("no admin channel")
    conn = _Pipe(where) if sys.platform == "win32" else _Socket(where, timeout)
    try:
        yield conn
    finally:
        conn.close()


def request(where: str, method: str, path: str, *, query: dict | None = None, body: Any = None) -> tuple[int, Any]:
    """One API call (path /api/...) as the owner; returns (status, body)."""
    payload = {"method": method.upper(), "path": path, "query": query or {}}
    if body is not None:
        payload["body"] = body
    with _connect(where, TIMEOUT) as conn:
        conn.send(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        chunks, size = [], 0
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_REPLY:
                raise Unavailable("reply too large")
    text = b"".join(chunks).decode("utf-8").strip()
    if not text:
        raise Unavailable("empty reply")
    reply = json.loads(text)
    return int(reply.get("status", 500)), reply.get("body")


def events(where: str) -> Iterator[dict]:
    """The daemon's live events ({"event", "data"}) until it stops; raises Unavailable if it is not running."""
    with _connect(where, None) as conn:
        conn.send(b'{"method":"EVENTS"}\n')
        buffer = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line.strip():
                    yield json.loads(line)
