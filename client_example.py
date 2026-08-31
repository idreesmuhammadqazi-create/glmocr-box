#!/usr/bin/env python3
import base64
import json
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
KEY = sys.argv[2] if len(sys.argv) > 2 else "changeme-please"
FILE = sys.argv[3] if len(sys.argv) > 3 else "test.pdf"

with open(FILE, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

r = httpx.post(
    f"{BASE}/paas/v4/layout_parsing",
    headers={"Authorization": f"Bearer {KEY}"},
    json={"model": "glm-ocr", "file": b64},
    timeout=900,
)
r.raise_for_status()
resp = r.json()

print(json.dumps({k: (v if k != "md_results" else v[:300] + "...")
                  for k, v in resp.items() if k != "crop_images"}, indent=2, default=str)[:2000])

with open("out.md", "w") as f:
    f.write(resp.get("md_results", ""))
with open("out.json", "w") as f:
    json.dump(resp.get("layout_details", []), f, indent=2, ensure_ascii=False)
print("\nwrote out.md and out.json")
