"""Probe: does the question number survive at higher DPI? (debugging aid)."""
import base64
import io
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import pymupdf
from PIL import Image

pdf = sys.argv[1]
page_no = int(sys.argv[2])
dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 300

doc = pymupdf.open(pdf)
zoom = dpi / 72
pix = doc[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
print(f"{dpi}dpi page {page_no}: {img.size}")

buf = io.BytesIO()
img.save(buf, format="PNG")
resp = requests.post(
    f"{os.environ['ZAI_BASE_URL']}/layout_parsing",
    headers={"Authorization": f"Bearer {os.environ['ZAI_API_KEY']}"},
    json={
        "model": "glm-ocr",
        "file": "data:image/png;base64,"
        + base64.b64encode(buf.getvalue()).decode(),
    },
    timeout=120,
)
print("status:", resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print("MD:", data.get("md_results", "")[:700])
    from collections import Counter

    els = data.get("layout_details", [])
    print("labels:", Counter(e.get("label") for e in els if isinstance(e, dict)))
else:
    print("error:", resp.text[:300])