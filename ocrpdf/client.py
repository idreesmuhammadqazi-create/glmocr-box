import asyncio
import base64
import logging
import random
from typing import Dict, List, NamedTuple

import httpx

from .config import Settings

log = logging.getLogger("ocrpdf")

RETRY_STATUS = {429, 500, 502, 503, 504}


class LayoutResult(NamedTuple):
    md: str
    elements: List[Dict]


class OcrClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.timeout,
        )

    async def parse_image(self, png: bytes, kind: str = "page") -> LayoutResult:
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        body = {"model": self.settings.model, "file": data_url}
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            retry_after = None
            try:
                resp = await self.client.post("/layout_parsing", json=body)
                if resp.status_code in RETRY_STATUS:
                    retry_after = resp.headers.get("Retry-After")
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                data = resp.json()
                if data.get("error"):
                    raise RuntimeError(f"API error: {data['error']}")
                md = data.get("md_results") or ""
                elements = data.get("layout_details") or []
                if elements and isinstance(elements[0], list):
                    elements = elements[0]
                return LayoutResult(md=md.strip(), elements=elements)
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as e:
                status = getattr(e, "response", None)
                if status is not None and status.status_code not in RETRY_STATUS:
                    raise RuntimeError(f"API error HTTP {status.status_code}: {status.text[:300]}")
                last_error = e
            except RuntimeError as e:
                raise
            except Exception as e:
                last_error = e
            delay = min(2 ** attempt * 2, 60) + random.uniform(0, 2)
            if retry_after:
                try:
                    delay = max(delay, float(retry_after) + random.uniform(0, 1))
                except ValueError:
                    pass
            log.warning("%s OCR call failed (attempt %d/%d): %s — retrying in %.1fs",
                        kind, attempt, self.settings.max_retries, last_error, delay)
            await asyncio.sleep(delay)
        raise RuntimeError(f"{kind} OCR call failed after {self.settings.max_retries} attempts: {last_error}")

    async def close(self) -> None:
        await self.client.aclose()
