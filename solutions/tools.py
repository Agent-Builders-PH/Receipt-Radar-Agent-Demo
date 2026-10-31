"""The four strict tools the Logger agent can call (Phase 2).

Each tool is written as an explicit Function so you can see the exact schema
Claude receives. strict=True makes Claude's tool calls match the schema
exactly: every parameter present, no extra ones, enums respected.

Two locks on every guardrail, like Episode 1: the description tells Claude the
rule, and the Python behind the tool enforces it anyway.

    tool            kind   offered when          guardrail in code
    find_duplicate  read   receipt runs          same photo, or same vendor + amount within a day
    log_expense     write  receipt runs          refuses duplicates and amounts of 0 or less
    get_spending    read   always                code sums the CSV, not the model
    set_budget      write  only radar.py --ask   never offered during a receipt run
"""
from __future__ import annotations

from datetime import date

from agno.tools.function import Function

from . import ledger
from .settings import CATEGORIES

# The photo hash is attached by code, never passed by the model, so the model
# can't fake or forget it. radar.py calls start_receipt_run() before the Logger runs.
_run = {"photo_hash": None, "logged": False}


def start_receipt_run(photo_hash: str | None) -> None:
    _run["photo_hash"] = photo_hash
    _run["logged"] = False


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------- the Python behind each tool

def _find_duplicate(vendor: str, amount_php: float, date: str) -> str:
    day = _parse_day(date)
    if day is None:
        return "ERROR: date must be YYYY-MM-DD."
    hits = ledger.find_matches(vendor, amount_php, day, _run["photo_hash"])
    if not hits:
        return "NEW: no matching row. You may log it."
    row = hits[0]
    why = "the same photo" if row.get("photo_hash") == _run["photo_hash"] else "same vendor and amount within a day"
    return (f"DUPLICATE ({why}): already logged on row {row['date']}, {row['vendor']}, "
            f"{ledger.peso(float(row['amount_php']))}. Do not log it again.")


def _log_expense(date: str, vendor: str, amount_php: float, category: str) -> str:
    day = _parse_day(date)
    cat = ledger.canonical_category(category)
    if day is None:
        return "REFUSED: date must be YYYY-MM-DD."
    if cat is None:
        return f"REFUSED: category must be one of {', '.join(CATEGORIES)}."
    if amount_php <= 0:
        return "REFUSED: the amount must be above 0."
    if _run["logged"]:
        return "REFUSED: this receipt was already logged in this run. One row per receipt."
    if ledger.find_matches(vendor, amount_php, day, _run["photo_hash"]):
        return "REFUSED: this receipt is already in expenses.csv. Nothing was added."
    row = ledger.append_row(day, vendor, amount_php, cat, _run["photo_hash"] or "")
    _run["logged"] = True
    return (f"LOGGED: {row['date']}, {row['vendor']}, {ledger.peso(amount_php)}, {cat}. "
            f"{ledger.budget_line(cat, row['date'][:7])}")


def _get_spending(category: str, month: str) -> str:
    cat = ledger.canonical_category(category)
    if cat is None:
        return f"ERROR: category must be one of {', '.join(CATEGORIES)}."
    if len(month) != 7 or _parse_day(month + "-01") is None:
        return "ERROR: month must be YYYY-MM."
    return ledger.budget_line(cat, month)


def _set_budget(category: str, amount_php: float) -> str:
    cat = ledger.canonical_category(category)
    if cat is None:
        return f"REFUSED: category must be one of {', '.join(CATEGORIES)}."
    if amount_php <= 0:
        return "REFUSED: a budget must be above 0."
    ledger.save_budget(cat, amount_php)
    return f"BUDGET SET: {cat} is now {ledger.peso(amount_php)} a month."


# --------------------------------------------------------------------------- the schemas Claude sees
# Strict-mode rules: every object has additionalProperties: false, every
# property is required, and no minimum/maximum/minLength limits.

CATEGORY = {"type": "string", "enum": CATEGORIES, "description": "One of the seven categories."}

# TODO 4 (answer): the log_expense schema
LOG_EXPENSE_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "format": "date", "description": "Receipt date, YYYY-MM-DD."},
        "vendor": {"type": "string", "description": "Store or biller name."},
        "amount_php": {"type": "number", "description": "Grand total in pesos."},
        "category": CATEGORY,
    },
    "required": ["date", "vendor", "amount_php", "category"],
    "additionalProperties": False,
}

log_expense = Function(
    name="log_expense",
    description="Add one expense row. Call once per receipt, only after find_duplicate says it is new.",
    parameters=LOG_EXPENSE_SCHEMA,
    strict=True,
    entrypoint=_log_expense,
)

# TODO 5 (answer): find_duplicate, written the same way
FIND_DUPLICATE_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string", "description": "Store or biller name."},
        "amount_php": {"type": "number", "description": "Grand total in pesos."},
        "date": {"type": "string", "format": "date", "description": "Receipt date, YYYY-MM-DD."},
    },
    "required": ["vendor", "amount_php", "date"],
    "additionalProperties": False,
}

find_duplicate = Function(
    name="find_duplicate",
    description="Check whether this receipt is already in expenses.csv. Call it before log_expense.",
    parameters=FIND_DUPLICATE_SCHEMA,
    strict=True,
    entrypoint=_find_duplicate,
)

get_spending = Function(
    name="get_spending",
    description="How much was spent in one category in one month, and the budget left. "
                "Use it for every spending question; never add up numbers yourself.",
    parameters={
        "type": "object",
        "properties": {
            "category": CATEGORY,
            "month": {"type": "string", "description": "The month as YYYY-MM."},
        },
        "required": ["category", "month"],
        "additionalProperties": False,
    },
    strict=True,
    entrypoint=_get_spending,
)

set_budget = Function(
    name="set_budget",
    description="Set the monthly budget for one category. Only when the user asks for it directly.",
    parameters={
        "type": "object",
        "properties": {
            "category": CATEGORY,
            "amount_php": {"type": "number", "description": "The new monthly limit in pesos."},
        },
        "required": ["category", "amount_php"],
        "additionalProperties": False,
    },
    strict=True,
    entrypoint=_set_budget,
)

# --------------------------------------------------------------------------- which tools each run gets

# TODO 6 (answer): the Logger's tools for a receipt run. set_budget is NOT here,
# so text written on a receipt can never change your budget.
RECEIPT_TOOLS = [find_duplicate, log_expense, get_spending]

# radar.py --ask: questions and budget changes typed by you, no receipt involved.
ASK_TOOLS = [get_spending, set_budget]
