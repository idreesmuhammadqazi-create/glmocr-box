"""storage.to upload client (REST API, presigned R2 uploads).

Flow (https://storage.to/docs/api):
  1. POST /upload/init    {filename, content_type, size} -> presigned URL(s)
  2. PUT  <upload_url>    raw bytes straight to R2
  3. POST /upload/confirm {filename, size, content_type, r2_key, ...} -> file

Anonymous uploads work with just an X-Visitor-Token header (files expire in
3 days). Set STORAGE_TO_TOKEN for an authenticated bearer token.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import requests

from .config import Config

DEFAULT_BASE = "https://storage.to/api"

CONTENT_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
    ".html": "text/html",
}


def _content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def load_visitor_token(cache_dir: str | Path) -> str:
    """Load or create a persistent anonymous visitor token."""
    p = Path(cache_dir) / ".visitor_token"
    if p.exists():
        tok = p.read_text().strip()
        if tok:
            return tok
    p.parent.mkdir(parents=True, exist_ok=True)
    tok = "ocrqp-" + secrets.token_hex(16)
    p.write_text(tok)
    return tok


class StorageClient:
    def __init__(self, base_url: str, visitor_token: str | None,
                 ca_bundle: str | None, timeout_s: int = 60,
                 bearer_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.visitor_token = visitor_token
        self.bearer_token = bearer_token
        self.timeout_s = timeout_s
        self.session = requests.Session()
        if ca_bundle:
            self.session.verify = ca_bundle

    @classmethod
    def from_config(cls, config: Config) -> "StorageClient":
        return cls(
            base_url=os.getenv("STORAGE_TO_BASE_URL", DEFAULT_BASE),
            visitor_token=load_visitor_token(config.cache_dir),
            ca_bundle=config.ca_bundle,
            timeout_s=config.timeout_s,
            bearer_token=os.getenv("STORAGE_TO_TOKEN"),
        )

    # -- low-level ------------------------------------------------------- #
    def _headers(self, extra: dict | None = None) -> dict:
        h: dict[str, str] = {}
        if self.bearer_token:
            h["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.visitor_token:
            h["X-Visitor-Token"] = self.visitor_token
        if extra:
            h.update(extra)
        return h

    def _post(self, path: str, body: dict | None = None) -> dict:
        resp = self.session.post(
            f"{self.base_url}{path}", json=body or {},
            headers=self._headers({"Content-Type": "application/json"}),
            timeout=self.timeout_s, verify=self.session.verify or True,
        )
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            raise
        if resp.status_code >= 400 or data.get("success") is False:
            raise RuntimeError(f"{path} failed [{resp.status_code}]: {data}")
        return data

    def _get(self, path: str) -> dict:
        resp = self.session.get(
            f"{self.base_url}{path}", headers=self._headers(),
            timeout=self.timeout_s, verify=self.session.verify or True,
        )
        resp.raise_for_status()
        return resp.json()

    # -- public API ------------------------------------------------------ #
    def health(self) -> bool:
        try:
            return self._get("/health").get("status") == "ok"
        except Exception:
            return False

    def create_collection(self, expected_file_count: int | None = None) -> dict:
        body = {}
        if expected_file_count is not None:
            body["expected_file_count"] = expected_file_count
        return self._post("/collection", body)

    def upload_file(self, path: str | Path, collection_id: str | None = None) -> dict:
        """Upload a file; small files use a single presigned PUT."""
        path = Path(path)
        size = path.stat().st_size
        ctype = _content_type(path)

        init = self._post("/upload/init", {
            "filename": path.name, "content_type": ctype, "size": size,
        })
        if init.get("type") == "multipart":
            return self._upload_multipart(path, init, collection_id)

        headers = {k: v[0] for k, v in init.get("headers", {}).items()}
        headers.setdefault("Content-Type", ctype)
        put = self.session.put(
            init["upload_url"], data=path.read_bytes(), headers=headers,
            timeout=self.timeout_s, verify=self.session.verify or True,
        )
        put.raise_for_status()

        body = {"filename": path.name, "size": size,
                "content_type": ctype, "r2_key": init["r2_key"]}
        if collection_id:
            body["collection_id"] = collection_id
        return self._post("/upload/confirm", body)

    def _upload_multipart(self, path: Path, init: dict, collection_id: str | None) -> dict:
        """Multipart upload for large files (>50MB)."""
        path = Path(path)
        upload_id = init["upload_id"]
        r2_key = init["r2_key"]
        total_parts = init["total_parts"]
        urls = {int(k): v for k, v in init.get("initial_urls", {}).items()}

        parts = []
        with open(path, "rb") as fh:
            for pn in range(1, total_parts + 1):
                if pn not in urls:  # fetch more part URLs if needed
                    more = self._post("/upload/parts", {
                        "upload_id": upload_id, "part_numbers": [pn]})
                    for pu in more.get("part_urls", []):
                        urls[int(pu["partNumber"])] = pu["url"]
                chunk = fh.read(init["part_size"])
                r = self.session.put(urls[pn], data=chunk,
                                     timeout=self.timeout_s,
                                     verify=self.session.verify or True)
                r.raise_for_status()
                parts.append({"partNumber": pn, "etag": r.headers.get("ETag", "")})

        self._post("/upload/complete-multipart", {"upload_id": upload_id, "parts": parts})
        body = {"filename": path.name, "size": path.stat().st_size,
                "content_type": _content_type(path), "r2_key": r2_key}
        if collection_id:
            body["collection_id"] = collection_id
        return self._post("/upload/confirm", body)
