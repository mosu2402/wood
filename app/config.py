import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _abs_sqlite(url: str) -> str:
    """Make relative sqlite paths relative to the project folder, not the shell's cwd."""
    prefix = "sqlite:///"
    if url.startswith(prefix) and not url.startswith(prefix + "/") and ":memory:" not in url:
        rel = url[len(prefix):]
        path = (BASE_DIR / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return prefix + path.as_posix()
    return url


class Settings:
    DATABASE_URL = _abs_sqlite(os.getenv("DATABASE_URL", "sqlite:///./data/luxe.db"))
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))
    BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Luxe Laminate")
    BUSINESS_ADDRESS = os.getenv("BUSINESS_ADDRESS", "")
    BUSINESS_PHONE = os.getenv("BUSINESS_PHONE", "")
    BUSINESS_GSTIN = os.getenv("BUSINESS_GSTIN", "")
    BACKUP_DIR = (BASE_DIR / os.getenv("BACKUP_DIR", "./backups")).resolve()
    BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "30"))
    # Round GST on each bill line to whole rupees (172.80 -> 173), as done in the shop's sheets
    GST_ROUND_RUPEE = os.getenv("GST_ROUND_RUPEE", "1").strip().lower() in ("1", "true", "yes")
    BILL_TERMS = os.getenv("BILL_TERMS", "Goods once sold will not be accepted back.|Subject to Ahmedabad jurisdiction only. E.& O.E.")
    BANK_DETAILS = os.getenv("BANK_DETAILS", "")

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def sqlite_path(self) -> Path:
        return Path(self.DATABASE_URL.replace("sqlite:///", "", 1))


settings = Settings()
