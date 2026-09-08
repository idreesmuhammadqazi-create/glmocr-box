"""Storage client tests (no network — session is mocked)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ocrqp.storage import StorageClient, _content_type, load_visitor_token


def test_content_type():
    assert _content_type(Path("a.json")) == "application/json"
    assert _content_type(Path("a.md")) == "text/markdown"
    assert _content_type(Path("a.bin")) == "application/octet-stream"


def test_visitor_token_persisted(tmp_path):
    t1 = load_visitor_token(tmp_path)
    t2 = load_visitor_token(tmp_path)
    assert t1 == t2 and t1.startswith("ocrqp-")


def test_upload_single_flow(tmp_path):
    f = tmp_path / "x.json"
    f.write_text('{"a":1}')

    client = StorageClient("https://storage.to/api", "vt-123", None)
    client.session = MagicMock()

    init_resp = MagicMock()
    init_resp.json.return_value = {
        "success": True, "type": "single",
        "upload_url": "https://r2.example/put", "headers": {}, "r2_key": "rk-1",
    }
    init_resp.status_code = 200
    confirm_resp = MagicMock()
    confirm_resp.json.return_value = {
        "success": True, "file": {"id": "abc", "url": "https://storage.to/abc"},
    }
    confirm_resp.status_code = 200
    put_resp = MagicMock()
    put_resp.status_code = 200
    put_resp.raise_for_status = lambda: None

    client.session.post.side_effect = [init_resp, confirm_resp]
    client.session.put.return_value = put_resp

    out = client.upload_file(f)
    assert out["file"]["url"] == "https://storage.to/abc"
    # visitor token header was sent on init
    _, kwargs = client.session.post.call_args_list[0]
    assert kwargs["headers"]["X-Visitor-Token"] == "vt-123"
