import base64
import io
import os
import re
import time
import uuid

import httpx
import fitz
from PIL import Image
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:5002/glmocr/parse")
API_KEY = os.environ.get("OCR_API_KEY", "")
EMBED_IMAGES = os.environ.get("EMBED_IMAGES", "true").lower() in ("1", "true", "yes")
PDF_DPI = int(os.environ.get("PDF_DPI", "200"))
PAGE_LIMIT = int(os.environ.get("PAGE_LIMIT", "100"))
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "80"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "900"))

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

app = FastAPI(docs_url=None, redoc_url=None)


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"code": status, "message": message}, status_code=status)


def _decode_data_uri(ref: str) -> tuple[bytes, str]:
    header, _, b64 = ref.partition(",")
    if not ref.startswith("data:") or not b64:
        raise ValueError("malformed data URI")
    mime = header[5:].split(";")[0].strip() or "application/octet-stream"
    return base64.b64decode(b64), mime


def _detect_mime(data: bytes) -> str:
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _slice_pdf(pdf: bytes, start: int, end: int) -> bytes:
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        n = doc.page_count
        s = max(1, start or 1)
        e = min(n, end or n)
        if s > e:
            raise ValueError(f"invalid page range {s}-{e} for {n} pages")
        out = fitz.open()
        out.insert_pdf(doc, from_page=s - 1, to_page=e - 1)
        return out.tobytes()
    finally:
        doc.close()


async def _fetch_input(file_ref: str) -> tuple[bytes, str]:
    if file_ref.startswith("data:"):
        raw, mime = _decode_data_uri(file_ref)
        return raw, mime
    if file_ref.startswith("file://"):
        with open(file_ref[7:], "rb") as f:
            raw = f.read()
        return raw, _detect_mime(raw)
    if file_ref.startswith(("http://", "https://")):
        async with httpx.AsyncClient(
            timeout=120, follow_redirects=True, headers={"User-Agent": _UA},
        ) as c:
            r = await c.get(file_ref)
            r.raise_for_status()
            raw = r.content
        return raw, _detect_mime(raw)
    try:
        raw = base64.b64decode(file_ref, validate=True)
    except Exception:
        raise ValueError("file must be a URL, data URI, or base64 string")
    if len(raw) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"file exceeds {MAX_FILE_MB}MB limit")
    return raw, _detect_mime(raw)


def _render_page_images(pdf: bytes, dpi: int, limit: int) -> list:
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pages = []
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pages.append((pix.width, pix.height, pix.tobytes("png")))
            if len(pages) >= limit:
                break
        return pages
    finally:
        doc.close()


def _render_single_image(data: bytes) -> list:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return [(img.width, img.height, buf.getvalue())]


def _norm_bbox(bbox, pw: int, ph: int):
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except Exception:
        return None
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1000.0:
        return (
            int(x1 / 1000.0 * pw),
            int(y1 / 1000.0 * ph),
            int(x2 / 1000.0 * pw),
            int(y2 / 1000.0 * ph),
        )
    return int(x1), int(y1), int(x2), int(y2)


def _crop_png(page_img, rect) -> bytes:
    pw, ph, png = page_img
    x1, y1, x2, y2 = rect
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(pw, x2), min(ph, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return b""
    img = Image.open(io.BytesIO(png))
    buf = io.BytesIO()
    img.crop((x1, y1, x2, y2)).save(buf, format="PNG")
    return buf.getvalue()


def _iter_blocks(details):
    if not isinstance(details, list):
        return
    for entry in details:
        if isinstance(entry, list):
            yield from (b for b in entry if isinstance(b, dict))
        elif isinstance(entry, dict):
            yield entry


def embed_images(md: str, details, page_imgs):
    crops: list[str] = []
    data_uris: list[str] = []

    per_page = isinstance(details, list) and details and isinstance(details[0], list)
    if per_page:
        for pi, page in enumerate(details):
            if pi >= len(page_imgs):
                break
            for b in page:
                if not isinstance(b, dict) or b.get("label") != "image" or not b.get("bbox_2d"):
                    continue
                rect = _norm_bbox(b["bbox_2d"], page_imgs[pi][0], page_imgs[pi][1])
                if not rect:
                    continue
                png = _crop_png(page_imgs[pi], rect)
                if png:
                    data_uris.append(_to_data_uri(png, "image/png"))
    else:
        for b in _iter_blocks(details):
            if b.get("label") != "image" or not b.get("bbox_2d"):
                continue
            rect = _norm_bbox(b["bbox_2d"], page_imgs[0][0], page_imgs[0][1])
            if not rect:
                continue
            png = _crop_png(page_imgs[0], rect)
            if png:
                data_uris.append(_to_data_uri(png, "image/png"))

    if not data_uris:
        return md, crops

    it = iter(data_uris)

    def _sub(m):
        url = m.group(1)
        if url.startswith(("http://", "https://", "data:")):
            return m.group(0)
        try:
            uri = next(it)
        except StopIteration:
            return m.group(0)
        crops.append(uri)
        return f"![image]({uri})"

    new_md = _MD_IMG_RE.sub(_sub, md)
    if not crops and new_md == md:
        new_md = md + "\n\n" + "\n\n".join(f"![image]({u})" for u in data_uris)
        crops = list(data_uris)
    return new_md, crops


def _to_data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


@app.get("/health")
async def health():
    upstream_ok = False
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://127.0.0.1:5002/health")
            upstream_ok = r.status_code == 200
    except Exception:
        pass
    return {"status": "ok", "upstream": "ok" if upstream_ok else "starting"}


@app.post("/paas/v4/layout_parsing")
async def layout_parsing(request: Request):
    if API_KEY:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_KEY}":
            return _err(401, "Invalid API key")
    try:
        body = await request.json()
    except Exception:
        return _err(400, "Invalid JSON payload")

    file_ref = body.get("file")
    if not file_ref or not isinstance(file_ref, str):
        return _err(400, "Field 'file' is required (URL, data URI, or base64)")

    try:
        raw, mime = await _fetch_input(file_ref)
    except ValueError as e:
        return _err(400, str(e))
    except httpx.HTTPStatusError as e:
        return _err(400, f"Could not fetch file: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(400, f"Could not fetch file: {e}")

    if len(raw) > MAX_FILE_MB * 1024 * 1024:
        return _err(400, f"file exceeds {MAX_FILE_MB}MB limit")

    truncated = False
    if mime == "application/pdf":
        if body.get("start_page_id") or body.get("end_page_id"):
            try:
                raw = _slice_pdf(raw, int(body.get("start_page_id") or 1), int(body.get("end_page_id") or 10**9))
            except ValueError as e:
                return _err(400, str(e))
            except Exception:
                return _err(400, "Could not slice PDF pages")
        try:
            page_imgs = _render_page_images(raw, PDF_DPI, PAGE_LIMIT)
        except Exception:
            return _err(400, "Could not render PDF pages")
        if not page_imgs:
            return _err(400, "PDF contains no readable pages")
        truncated = len(page_imgs) >= PAGE_LIMIT
    else:
        try:
            page_imgs = _render_single_image(raw)
        except Exception:
            return _err(400, "File is not a readable PDF or image")

    payload = {
        "images": [_to_data_uri(png, "image/png") for _, _, png in page_imgs],
        "model": "glm-ocr",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await c.post(UPSTREAM_URL, json=payload)
    except httpx.TimeoutException:
        return _err(504, "Upstream OCR pipeline timed out")
    except Exception as e:
        return _err(502, f"Upstream OCR pipeline unavailable: {e}")

    if r.status_code != 200:
        return _err(502, f"Upstream error: {r.text[:300]}")

    try:
        resp = r.json()
    except Exception:
        return _err(502, "Upstream returned invalid JSON")

    md = resp.get("md_results") or resp.get("markdown_result") or ""
    details = resp.get("layout_details") or resp.get("json_result") or []

    resp["data_info"] = {
        "num_pages": len(page_imgs),
        "pages": [{"width": w, "height": h} for w, h, _ in page_imgs],
    }

    if EMBED_IMAGES and md:
        try:
            md, crops = embed_images(md, details, page_imgs)
            resp["md_results"] = md
            resp["crop_images"] = crops
        except Exception:
            pass

    if truncated:
        resp["pages_truncated"] = True

    resp["model"] = body.get("model", "glm-ocr")
    resp["request_id"] = body.get("request_id") or f"req_{uuid.uuid4().hex[:24]}"
    resp["created"] = int(time.time())
    return JSONResponse(resp)
