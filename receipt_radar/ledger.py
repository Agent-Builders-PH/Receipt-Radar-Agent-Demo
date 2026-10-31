"""Your files: expenses.csv and budget.json, plus the photo hash.

Plain Python, no AI. The tools in tools.py call these helpers, so every
number the agent reports comes from code, never from the model's own math.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from . import settings

COLUMNS = ["date", "vendor", "amount_php", "category", "photo_hash", "logged_at"]


def photo_hash(path: str | Path) -> str:
    """Fingerprint of the exact file bytes. The same photo sent twice has the same hash."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def canonical_category(name: str) -> str | None:
    """'food', 'FOOD' and 'Food' are all Food. Casing can drift, so compare case-insensitively."""
    for c in settings.CATEGORIES:
        if c.lower() == str(name).strip().lower():
            return c
    return None


def peso(amount: float) -> str:
    """4862.35 -> '₱4,862.35'; 289 -> '₱289'."""
    return f"₱{amount:,.2f}".replace(".00", "")


# --------------------------------------------------------------------------- expenses.csv

def read_rows() -> list[dict]:
    if not settings.EXPENSES_CSV.exists():
        return []
    with settings.EXPENSES_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_row(day: date, vendor: str, amount_php: float, category: str, photo: str) -> dict:
    settings.EXPENSES_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_file = not settings.EXPENSES_CSV.exists() or settings.EXPENSES_CSV.stat().st_size == 0
    row = {
        "date": day.isoformat(),
        "vendor": vendor.strip(),
        "amount_php": f"{amount_php:.2f}",
        "category": category,
        "photo_hash": photo,
        "logged_at": datetime.now().isoformat(timespec="seconds"),
    }
    with settings.EXPENSES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return row


def _same_vendor(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or a in b or b in a


def find_matches(vendor: str, amount_php: float, day: date, photo: str | None) -> list[dict]:
    """Rows with the same photo, or the same vendor and amount within one day."""
    hits = []
    for row in read_rows():
        if photo and row.get("photo_hash") == photo:
            hits.append(row)
            continue
        try:
            row_day = date.fromisoformat(row["date"])
            same_amount = abs(float(row["amount_php"]) - amount_php) < 0.01
        except (KeyError, ValueError):
            continue
        if same_amount and _same_vendor(row["vendor"], vendor) and abs((row_day - day).days) <= 1:
            hits.append(row)
    return hits


def spent(category: str, month: str) -> float:
    """Sum of one category in one month (YYYY-MM)."""
    total = 0.0
    for row in read_rows():
        if row.get("date", "").startswith(month) and canonical_category(row.get("category", "")) == category:
            total += float(row["amount_php"])
    return round(total, 2)


# --------------------------------------------------------------------------- budget.json

def load_budget() -> dict[str, float]:
    if not settings.BUDGET_JSON.exists():
        return {}
    raw = json.loads(settings.BUDGET_JSON.read_text(encoding="utf-8"))
    return {canonical_category(k) or k: float(v) for k, v in raw.items()}


def save_budget(category: str, amount_php: float) -> None:
    budget = load_budget()
    budget[category] = amount_php
    settings.BUDGET_JSON.parent.mkdir(parents=True, exist_ok=True)
    settings.BUDGET_JSON.write_text(json.dumps(budget, indent=2) + "\n", encoding="utf-8")


def budget_line(category: str, month: str) -> str:
    """'Food: ₱3,240 of ₱4,000 this month' (or '... in October 2026' for another month)."""
    if month == date.today().strftime("%Y-%m"):
        when = "this month"
    else:
        try:
            when = "in " + date.fromisoformat(month + "-01").strftime("%B %Y")
        except ValueError:
            when = f"in {month}"
    used = spent(category, month)
    limit = load_budget().get(category)
    if limit is None:
        return f"{category}: {peso(used)} {when} (no budget set)"
    left = limit - used
    tail = f"{peso(left)} left" if left >= 0 else f"over by {peso(-left)}"
    return f"{category}: {peso(used)} of {peso(limit)} {when} ({tail})"
