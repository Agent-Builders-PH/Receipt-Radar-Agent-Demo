"""Paths and settings shared by every file. You don't need to edit this."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Claude Sonnet 5.5, the same model as Episode 1.
MODEL = os.getenv("RADAR_MODEL", "claude-sonnet-5-5")

# check.py points DATA_DIR at a scratch folder so tests never touch your real ledger.
DATA_DIR = Path(os.getenv("RADAR_DATA_DIR", ROOT / "data"))
EXPENSES_CSV = DATA_DIR / "expenses.csv"
BUDGET_JSON = DATA_DIR / "budget.json"

RECEIPTS_DIR = ROOT / "receipts"
OCR_CACHE_DIR = ROOT / "ocr_cache"

# cached: read ocr_cache/<name>.json (no Lumen keys needed)
# live:   call Lumen OCR and save the result to ocr_cache/
OCR_MODE = os.getenv("OCR_MODE", "cached").strip().lower()
LUMEN_OCR_BASE_URL = os.getenv(
    "LUMEN_OCR_BASE_URL", "https://api.staging.nonlive.lumen.bayanichain.tech/ocr"
).rstrip("/")

CATEGORIES = ["Food", "Transport", "Bills", "Load", "Shopping", "Health", "Other"]
