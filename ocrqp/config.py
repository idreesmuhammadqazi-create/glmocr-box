"""Configuration loading from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional at runtime
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    api_key: str | None
    base_url: str
    model: str
    backend: str  # "glm" or "mock"
    page_dpi: int
    table_dpi: int
    cache_dir: str
    timeout_s: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_key=os.getenv("ZAI_API_KEY"),
            base_url=os.getenv(
                "ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
            ).rstrip("/"),
            model=os.getenv("GLM_OCR_MODEL", "glm-ocr"),
            backend=os.getenv("OCRQP_BACKEND", "glm").strip().lower(),
            page_dpi=_env_int("OCRQP_PAGE_DPI", 200),
            table_dpi=_env_int("OCRQP_TABLE_DPI", 300),
            cache_dir=os.getenv("OCRQP_CACHE_DIR", ".ocrqp-cache"),
            timeout_s=_env_int("OCRQP_TIMEOUT_S", 120),
        )

    def validate(self) -> None:
        if self.backend == "glm" and not self.api_key:
            raise RuntimeError(
                "ZAI_API_KEY is not set. Set it in .env (see .env.example) "
                "or run with OCRQP_BACKEND=mock for offline mode."
            )
