from __future__ import annotations

import json
from pathlib import Path

import pytest

from viewer_hub.core.migrate import open_hub
from viewer_hub.core.paths import HubPaths
from viewer_hub.app.factory import create_wsgi

SAMPLE_DOCS = [
    {"id": "a", "title": "authentication.py", "content": ["import jwt; def generate_token(user): pass"],
     "source_code_content": "def generate_token(user_id): return jwt.encode()", "language": "en", "file_type": "py",
     "file_path": "src/auth/authentication.py", "repository": "backend", "author": "An",
     "last_modified": "2026-01-02T00:00:00Z", "_version_": 1},
    {"id": "b", "title": "Hướng dẫn sử dụng", "content": "Tài liệu tiếng Việt về đăng nhập hệ thống", "language": "vi",
     "file_type": "md", "file_path": "docs/huong-dan.md", "repository": "docs", "last_modified": "2026-03-01T00:00:00Z"},
    {"id": "c", "title": "仕様書", "content": "ログイン画面の仕様について説明します", "language": "ja", "file_type": "pdf",
     "file_path": "spec/login.pdf", "repository": "docs", "image_ocr_text": "スキャンされたログイン仕様",
     "last_modified": "2025-12-01T00:00:00Z", "custom_s": "x"},
]


@pytest.fixture()
def paths(tmp_path: Path) -> HubPaths:
    return HubPaths(tmp_path / "data").ensure()


@pytest.fixture()
def search_db(paths: HubPaths) -> Path:
    from viewer_hub.fsearch.export_solr import write

    target = paths.home / "search" / "search.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    write(target, ((len(SAMPLE_DOCS), d) for d in SAMPLE_DOCS), "test")
    return target


@pytest.fixture()
def app(paths: HubPaths):
    state = open_hub(paths)
    application = create_wsgi(paths, state)
    application.config["TESTING"] = True
    yield application
    state.db.close()


@pytest.fixture()
def client(app):
    client = app.test_client()
    open_ = client.open

    def open_on_app_origin(*args, **kwargs):
        # Requests go to the app origin (app/origins.py) unless a test sets another Host.
        host = (kwargs.get("headers") or {}).get("Host", "127.0.0.1")
        kwargs.setdefault("base_url", f"http://{host}/")
        return open_(*args, **kwargs)

    client.open = open_on_app_origin
    return client


def write_json(path: Path, value) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path
