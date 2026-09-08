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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _default_ca_bundle() -> str | None:
    """Pick a CA bundle that works in this environment.

    Preference: explicit OCRQP_CA_BUNDLE, then the system bundle (works through
    the egress proxy), else None (requests' default).
    """
    explicit = os.getenv("OCRQP_CA_BUNDLE")
    if explicit:
        return explicit
    for cand in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
        if os.path.exists(cand):
            return cand
    return None


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
    ca_bundle: str | None  # path to a CA bundle for TLS verification
    table_rescue: bool  # re-OCR table crops at higher DPI (pass 2)
    rescue_max_area: float  # skip rescue for tables covering > this page fraction

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_key=os.getenv("ZAI_API_KEY"),
            base_url=os.getenv(
                "ZAI_BASE_URL", "https://api.z.ai/api/paas/v4"
            ).rstrip("/"),
            model=os.getenv("GLM_OCR_MODEL", "glm-ocr"),
            backend=os.getenv("OCRQP_BACKEND", "glm").strip().lower(),
            page_dpi=_env_int("OCRQP_PAGE_DPI", 200),
            table_dpi=_env_int("OCRQP_TABLE_DPI", 300),
            cache_dir=os.getenv("OCRQP_CACHE_DIR", ".ocrqp-cache"),
            timeout_s=_env_int("OCRQP_TIMEOUT_S", 120),
            ca_bundle=_default_ca_bundle(),
            table_rescue=_env_bool("OCRQP_TABLE_RESCUE", True),
            rescue_max_area=_env_float("OCRQP_RESCUE_MAX_AREA", 0.5),
        )

    def validate(self) -> None:
        if self.backend == "glm" and not self.api_key:
            raise RuntimeError(
                "ZAI_API_KEY is not set. Set it in .env (see .env.example) "
                "or run with OCRQP_BACKEND=mock for offline mode."
            )
