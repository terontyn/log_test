import os

def _clean_db_url(raw):
    if not raw:
        return None
    s = raw.strip().strip('"').strip("'")
    if s.startswith("DATABASE_URL="):
        s = s.split("=", 1)[1].strip()
    return s

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = _clean_db_url(os.getenv("DATABASE_URL"))

OCR_MODEL = "gpt-4o"
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.70"))

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
FILE_BASE = f"https://api.telegram.org/file/bot{BOT_TOKEN}" if BOT_TOKEN else None
DOWNLOAD_DIR = "/tmp/photos"
