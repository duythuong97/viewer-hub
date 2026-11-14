"""The server keeps its port across restarts (cli._free_port)."""
from __future__ import annotations

import os
import socket

import pytest

from viewer_hub.cli import _free_port


def test_skips_a_port_someone_listens_on():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert _free_port("127.0.0.1", port) != port


@pytest.mark.skipif(os.name == "nt", reason="TIME_WAIT does not block a bind on Windows")
def test_reuses_a_port_left_in_time_wait():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    accepted, _ = server.accept()
    accepted.close()  # the server side closes first: its end stays in TIME_WAIT, as after stopping with a browser open
    server.close()
    client.recv(1)
    client.close()
    assert _free_port("127.0.0.1", port) == port
