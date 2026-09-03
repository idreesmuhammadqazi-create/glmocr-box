import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-ocr"


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    page_dpi: int = 200
    table_dpi: int = 300
    workers: int = 3
    max_retries: int = 5
    timeout: float = 300.0
    max_tokens: int | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("ZAI_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "ZAI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        return cls(
            api_key=api_key,
            base_url=os.getenv("ZAI_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            model=os.getenv("GLM_OCR_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        )
