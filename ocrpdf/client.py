import asyncio
import base64
import logging
import random

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError

from .config import Settings

log = logging.getLogger("ocrpdf")

RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError)


class OcrClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=0,
        )

    async def ocr_image(self, png: bytes, prompt: str) -> str:
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                kwargs = {}
                if self.settings.max_tokens:
                    kwargs["max_tokens"] = self.settings.max_tokens
                resp = await self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    temperature=0,
                    **kwargs,
                )
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("empty OCR response")
                return text
            except RETRYABLE as e:
                last_error = e
            except APIStatusError as e:
                if e.status_code is None or e.status_code < 500 and e.status_code != 429:
                    raise
                last_error = e
            except ValueError as e:
                last_error = e
            delay = min(2 ** attempt * 1.5, 30) + random.uniform(0, 1)
            log.warning("OCR call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt, self.settings.max_retries, last_error, delay)
            await asyncio.sleep(delay)
        raise RuntimeError(f"OCR call failed after {self.settings.max_retries} attempts: {last_error}")
