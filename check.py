"""Phase checks for Receipt Radar. Run it after every phase.

    python check.py            # setup, plus the quick offline checks for every phase (free)
    python check.py 1          # Phase 1: offline checks, then a live check with Claude
    python check.py 2          # Phase 2: same
    python check.py 3          # Phase 3: offline checks, then all 10 cases in cases.json (TODO 8)
    python check.py 3 --offline   # skip the live part (no Claude calls, no cost)

Each line says PASS, FAIL (with the one thing to fix) or TODO (not written yet).
Live checks use cached OCR and a scratch copy of data/, so your own
expenses.csv and budget.json are never touched.
"""
from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AGNO_PIN = "3.1.3"
SAMPLE_CLEAR, SAMPLE_BLURRY = "01-fastfood.jpg", "04-blurry.jpg"
OFFLINE, LIVE = [], []


def offline(phase: int):
    def register(fn):
        OFFLINE.append((phase, fn))
        return fn
    return register


def live(phase: int):
    def register(fn):
        LIVE.append((phase, fn))
        return fn
    return register


class Todo(Exception):
    pass


def todo(message: str):
    raise Todo(message)


# ---------------------------------------------------------------- helpers

@contextlib.contextmanager
def scratch_data():
    """Point the ledger at a throwaway copy of data/ (fresh, empty expenses.csv)."""
    from receipt_radar import settings
    saved = settings.DATA_DIR, settings.EXPENSES_CSV, settings.BUDGET_JSON
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if saved[2].exists():
            shutil.copyfile(saved[2], tmp / "budget.json")
        settings.DATA_DIR, settings.EXPENSES_CSV, settings.BUDGET_JSON = tmp, tmp / "expenses.csv", tmp / "budget.json"
        try:
            yield tmp
        finally:
            settings.DATA_DIR, settings.EXPENSES_CSV, settings.BUDGET_JSON = saved


def receipt(**overrides):
    from receipt_radar.schema import Receipt
    if not Receipt.model_fields:
        todo("this check needs TODO 1 (the Receipt fields in schema.py) first")
    fields = dict(date=date(2026, 10, 28), vendor="Bida Burger", amount_php=289.0,
                  category="Food", sure=True, unsure_about=[])
    fields.update(overrides)
    return Receipt(**fields)


def ocr_of(*words):
    from receipt_radar.lumen_ocr import OcrResult, Word
    return OcrResult(text=" ".join(w for w, _ in words), words=[Word(w, c) for w, c in words])


def require_schema_fields():
    from receipt_radar.schema import Receipt
    want = {"date", "vendor", "amount_php", "category", "sure", "unsure_about"}
    have = set(Receipt.model_fields)
    if not have:
        todo("TODO 1: add the six Receipt fields in receipt_radar/schema.py")
    missing = want - have
    assert not missing, f"Receipt is missing: {', '.join(sorted(missing))}"
    assert not have - want, f"Receipt has extra fields: {', '.join(sorted(have - want))}"


def strict_schema_problems(schema: dict, props: list[str]) -> str | None:
    if not schema:
        return "empty"
    if schema.get("type") != "object":
        return 'needs "type": "object"'
    if set(schema.get("properties", {})) != set(props):
        return f"properties should be exactly {props}"
    if set(schema.get("required", [])) != set(props):
        return "strict mode: list every property in required"
    if schema.get("additionalProperties") is not False:
        return 'strict mode: add "additionalProperties": False'
    banned = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength"}
    for name, spec in schema["properties"].items():
        if banned & set(spec):
            return f"{name}: no numeric or length limits in a strict schema (the gate checks amounts)"
    return None


# ================================================================ Phase 0: setup

@offline(0)
def env_and_samples_ready():
    env = ROOT / ".env"
    assert env.exists(), "No .env yet. Run: copy .env.example .env   then paste your Anthropic key into it"
    from receipt_radar import settings
    key = os.getenv("ANTHROPIC_API_KEY", "")
    assert key and "your-key" not in key and key.startswith("sk-ant-"), \
        "ANTHROPIC_API_KEY in .env is empty or still the placeholder"
    assert settings.OCR_MODE in {"cached", "live"}, "OCR_MODE must be cached or live"
    have = importlib.metadata.version("agno")
    assert have == AGNO_PIN, f"agno {have} is installed; this module is pinned to {AGNO_PIN}. Run: uv pip install -r requirements.txt"
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    for c in cases:
        assert (settings.RECEIPTS_DIR / c["file"]).exists(), f"missing receipts/{c['file']}"
        assert (settings.OCR_CACHE_DIR / f"{Path(c['file']).stem}.json").exists(), f"missing ocr_cache for {c['file']}"
    print(f"      setup ok, OCR_MODE={settings.OCR_MODE}, agno {have}")


@offline(0)
def browser_ui_ready():
    import app  # the web page: python app.py
    assert app.UI.exists(), "ui/index.html is missing"


@live(0)
def anthropic_key_works():
    import anthropic
    try:
        anthropic.Anthropic().models.list(limit=1)  # free: lists models, no tokens
    except anthropic.AuthenticationError:
        raise AssertionError("Anthropic rejected the key in .env (401). Create a new key in the Claude Console.")


# ================================================================ Phase 1: read

@offline(1)
def todo1_receipt_schema():
    require_schema_fields()
    from receipt_radar.schema import Receipt
    props = Receipt.model_json_schema()["properties"]

    def kind(name):
        p = props[name]
        return p.get("type") or p.get("anyOf") or p.get("$ref")

    assert props["date"].get("format") == "date", "date should be a date (from datetime import date)"
    assert kind("vendor") == "string", "vendor should be a str"
    assert kind("amount_php") == "number", "amount_php should be a float"
    assert set(props["category"].get("enum", [])) == {"Food", "Transport", "Bills", "Load", "Shopping", "Health", "Other"}, \
        "category should be the Category Literal (the seven categories)"
    assert kind("sure") == "boolean", "sure should be a bool"
    items = props["unsure_about"].get("items", {})
    assert kind("unsure_about") == "array" and set(items.get("enum", [])) == {"date", "vendor", "amount", "category"}, \
        "unsure_about should be list[UnsureField]"
    banned = {"minimum", "exclusiveMinimum", "maximum", "maxLength", "minLength"}
    for name, spec in props.items():
        assert not banned & set(spec), f"{name}: no Field(gt=...) or length limits; structured outputs reject them"


@offline(1)
def todo2_reader_agent():
    from agno.agent import Agent
    from receipt_radar import reader
    from receipt_radar.schema import Receipt
    try:
        agent = reader.build_reader()
    except NotImplementedError:
        todo("TODO 2: build the Reader agent in receipt_radar/reader.py")
    assert isinstance(agent, Agent), "build_reader() should return an Agent"
    assert agent.output_schema is Receipt, "pass output_schema=Receipt so the reply is a Receipt"
    assert not agent.tools, "the Reader has no tools; it only reads"
    assert agent.model is not None and "claude" in agent.model.id, "use model=Claude(id=MODEL)"


@offline(1)
def todo3_photo_and_ocr_text():
    from agno.agent import Agent
    from agno.media import Image
    from receipt_radar import reader
    from receipt_radar.schema import Receipt
    if not Receipt.model_fields:
        todo("TODO 3 needs TODO 1 first")
    try:
        reader.build_reader()
    except NotImplementedError:
        todo("TODO 3 needs TODO 2 first")
    ocr = ocr_of(("TOTAL", 0.99), ("P289.00", 0.98))
    good = receipt()
    with mock.patch.object(Agent, "run", return_value=SimpleNamespace(content=good)) as run:
        got = reader.read_receipt(ROOT / "receipts" / SAMPLE_CLEAR, ocr)
    if not run.called:
        todo("TODO 3: call reader.run(...) with the OCR text and the photo")
    args, kwargs = run.call_args
    message = args[0] if args else kwargs.get("input", "")
    assert "P289.00" in str(message), "the message should contain the OCR text (ocr.text)"
    images = kwargs.get("images") or []
    assert images and isinstance(images[0], Image), "pass the photo as images=[Image(filepath=...)]"
    assert images[0].filepath, "use Image(filepath=upright)"
    assert got is good, "return run.content when it is a Receipt"
    with mock.patch.object(Agent, "run", return_value=SimpleNamespace(content="Sorry, I can't read that")):
        assert reader.read_receipt(ROOT / "receipts" / SAMPLE_CLEAR, ocr) is None, \
            "a reply that is not a Receipt should give None"


@live(1)
def clear_sample_is_sure_blurry_is_not():
    from receipt_radar.lumen_ocr import read_receipt_text
    from receipt_radar.reader import read_receipt
    from receipt_radar.schema import Receipt
    clear = ROOT / "receipts" / SAMPLE_CLEAR
    r = read_receipt(clear, read_receipt_text(clear, say=lambda m: None))
    assert isinstance(r, Receipt), "the clear sample did not come back as a Receipt"
    print(f"      clear:  {r.date} | {r.vendor} | {r.amount_php} | {r.category} | sure={r.sure}")
    assert r.sure, "the clear sample should come back sure: true"
    assert r.vendor and r.amount_php > 0 and r.category, "the clear sample should fill date, vendor, amount and category"
    blurry = ROOT / "receipts" / SAMPLE_BLURRY
    b = read_receipt(blurry, read_receipt_text(blurry, say=lambda m: None))
    print(f"      blurry: sure={getattr(b, 'sure', None)} unsure_about={getattr(b, 'unsure_about', None)}")
    assert b is None or not b.sure, "the blurry sample should come back sure: false"


# ================================================================ Phase 2: log

@offline(2)
def todo4_log_expense_strict():
    from agno.tools.function import Function
    from receipt_radar import tools
    if not tools.LOG_EXPENSE_SCHEMA or tools.log_expense is None:
        todo("TODO 4: write LOG_EXPENSE_SCHEMA and the log_expense Function in receipt_radar/tools.py")
    problem = strict_schema_problems(tools.LOG_EXPENSE_SCHEMA, ["date", "vendor", "amount_php", "category"])
    assert not problem, f"LOG_EXPENSE_SCHEMA: {problem}"
    assert isinstance(tools.log_expense, Function), "log_expense should be a Function(...)"
    assert tools.log_expense.name == "log_expense", 'name="log_expense"'
    assert tools.log_expense.strict is True, "add strict=True"
    assert tools.log_expense.parameters == tools.LOG_EXPENSE_SCHEMA, "parameters=LOG_EXPENSE_SCHEMA"
    assert getattr(tools.log_expense.entrypoint, "__name__", "") == "_log_expense", "entrypoint=_log_expense"


@offline(2)
def todo5_find_duplicate_strict():
    from agno.tools.function import Function
    from receipt_radar import tools
    if not tools.FIND_DUPLICATE_SCHEMA or tools.find_duplicate is None:
        todo("TODO 5: write FIND_DUPLICATE_SCHEMA and the find_duplicate Function")
    problem = strict_schema_problems(tools.FIND_DUPLICATE_SCHEMA, ["vendor", "amount_php", "date"])
    assert not problem, f"FIND_DUPLICATE_SCHEMA: {problem}"
    assert isinstance(tools.find_duplicate, Function), "find_duplicate should be a Function(...)"
    assert tools.find_duplicate.name == "find_duplicate", 'name="find_duplicate"'
    assert tools.find_duplicate.strict is True, "add strict=True"
    assert getattr(tools.find_duplicate.entrypoint, "__name__", "") == "_find_duplicate", "entrypoint=_find_duplicate"


@offline(2)
def todo6_receipt_tool_list():
    from receipt_radar import tools
    names = [getattr(t, "name", None) for t in tools.RECEIPT_TOOLS]
    if "log_expense" not in names or "find_duplicate" not in names:
        todo("TODO 6: add find_duplicate and log_expense to RECEIPT_TOOLS")
    assert "get_spending" in names, "keep get_spending in RECEIPT_TOOLS"
    assert "set_budget" not in names, "set_budget must never be offered during a receipt run"
    assert [t.name for t in tools.ASK_TOOLS] == ["get_spending", "set_budget"], "ASK_TOOLS changed"


@offline(2)
def guardrails_live_in_code():
    from receipt_radar import ledger, tools
    with scratch_data():
        tools.start_receipt_run("hash-one")
        assert tools._log_expense("2026-10-28", "Bida Burger", 0, "Food").startswith("REFUSED"), "amount 0 must be refused"
        assert tools._log_expense("2026-10-28", "Bida Burger", 289, "food").startswith("LOGGED"), "a good row should log"
        assert len(ledger.read_rows()) == 1
        assert tools._log_expense("2026-10-28", "Bida Burger", 289, "Food").startswith("REFUSED"), "one row per run"
        tools.start_receipt_run("hash-one")
        assert tools._find_duplicate("Bida Burger", 289, "2026-10-28").startswith("DUPLICATE"), "same photo is a duplicate"
        assert tools._log_expense("2026-10-28", "Bida Burger", 289, "Food").startswith("REFUSED"), "duplicates are refused in code"
        tools.start_receipt_run("hash-two")
        assert tools._find_duplicate("bida burger", 289, "2026-10-29").startswith("DUPLICATE"), \
            "same vendor and amount a day later is a duplicate"
        assert tools._find_duplicate("Bida Burger", 150, "2026-10-28").startswith("NEW")
        assert len(ledger.read_rows()) == 1


@live(2)
def logs_once_then_says_already_logged():
    from radar import process_receipt
    from receipt_radar import ledger
    quiet = lambda m: None
    with scratch_data():
        first = process_receipt(ROOT / "receipts" / SAMPLE_CLEAR, say=quiet)
        print(f"      first run:  {first.status}, tools {first.tools_called}")
        assert first.status == "logged" and len(ledger.read_rows()) == 1, \
            f"expected one new row in expenses.csv, got status {first.status}. {first.reply}"
        again = process_receipt(ROOT / "receipts" / SAMPLE_CLEAR, say=quiet)
        print(f"      second run: {again.status}, reply: {again.reply[:80]}")
        assert len(ledger.read_rows()) == 1, "the second run added a row; find_duplicate should stop it"
        assert again.status == "duplicate", "the second run should say it is already logged"


# ================================================================ Phase 3: guard and test

@offline(3)
def gate_rules_1_and_2():
    from receipt_radar import gate
    ocr = ocr_of(("TOTAL", 0.99), ("P289.00", 0.97))
    assert gate.check(None, ocr).rule == 1, "rule 1: no Receipt, no logging"
    r = gate.check(receipt(sure=False, unsure_about=["amount"]), ocr)
    assert r.rule == 2, "rule 2: stop when Claude isn't sure"


@offline(3)
def todo7_gate_rules_3_to_5():
    from receipt_radar import gate
    ocr = ocr_of(("TOTAL", 0.99), ("P289.00", 0.97))
    zero = gate.check(receipt(amount_php=0), ocr)
    if zero.ok:
        todo("TODO 7: add gate rules 3 to 5 in receipt_radar/gate.py")
    assert zero.rule == 3, "rule 3: an amount of 0 or less should stop at rule 3"
    missing = gate.check(receipt(amount_php=299.0), ocr)
    assert not missing.ok and missing.rule == 4, "rule 4: stop when the amount isn't in the OCR words"
    faint = gate.check(receipt(), ocr_of(("TOTAL", 0.99), ("P289.00", 0.55)))
    assert not faint.ok and faint.rule == 5, "rule 5: stop when that OCR word's confidence is below the threshold"
    for words in ([("TOTAL", 0.99), ("P289.00", 0.97)], [("₱289.00", 0.95)], [("PHP", 0.99), ("289.00", 0.93)]):
        assert gate.check(receipt(), ocr_of(*words)).ok, f"should pass: {words}"
    big = gate.check(receipt(amount_php=1235.0), ocr_of(("₱1,235.00", 0.91)))
    assert big.ok, "allow commas and a peso sign in the OCR word"


@offline(3)
def cases_file_is_complete():
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 10, "cases.json should have the 10 samples"
    for c in cases:
        assert c["expect"]["status"] in {"logged", "duplicate", "stopped"}, f"case {c['id']}: unknown status"


def judge(case: dict, out, budget_before: dict) -> str | None:
    """None when the case passed, otherwise what went wrong."""
    from receipt_radar import ledger
    want = case["expect"]
    if out.status != want["status"]:
        extra = f" ({out.gate.reason})" if out.gate and not out.gate.ok else ""
        return f"expected {want['status']}, got {out.status}{extra}"
    if want["status"] == "logged":
        row = ledger.read_rows()[-1]
        if ledger.canonical_category(row["category"]) != want["category"]:
            return f"category {row['category']}, expected {want['category']}"
        if "amount_php" in want and abs(float(row["amount_php"]) - want["amount_php"]) > 0.005:
            return f"amount {row['amount_php']}, expected {want['amount_php']}"
    if want.get("calls") and want["calls"] not in out.tools_called:
        return f"should call {want['calls']}, called {out.tools_called}"
    if want.get("budget_unchanged"):
        if "set_budget" in out.tools_called or ledger.load_budget() != budget_before:
            return "the budget changed during a receipt run"
    return None


@live(3)
def todo8_all_cases_pass():
    from radar import process_receipt
    from receipt_radar import ledger
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    passed = 0
    with scratch_data():
        for case in cases:
            before = ledger.load_budget()
            out = process_receipt(ROOT / "receipts" / case["file"], case.get("question"), say=lambda m: None)
            problem = judge(case, out, before)
            passed += problem is None
            mark = "PASS" if problem is None else "FAIL"
            detail = problem or out.status + (f", {out.gate.reason}" if out.gate and not out.gate.ok else "")
            print(f"      {mark} #{case['id']:<2} {case['tests']:<38} {detail}")
            if case.get("question") and out.reply:
                print(f"           reply: {out.reply.splitlines()[0][:90]}")
    print(f"      {passed} of {len(cases)} cases pass")
    assert passed == len(cases), f"{len(cases) - passed} case(s) failed; see the FAIL lines above"


# ================================================================ runner

NEXT = {
    0: "Setup is done. Start Phase 1: TODOs 1 to 3 in schema.py and reader.py, then python check.py 1",
    1: "Phase 1 done. Start Phase 2: TODOs 4 to 6 in tools.py, then python check.py 2",
    2: "Phase 2 done. Start Phase 3: TODO 7 in gate.py, then python check.py 3 (that is TODO 8)",
    3: "All phases done. Try it: python radar.py receipts/01-fastfood.jpg",
}


def run(fn) -> str:
    name = fn.__name__.replace("_", " ")
    try:
        fn()
    except Todo as t:
        print(f"  TODO  {name}: {t}")
        return "todo"
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return "fail"
    except Exception as e:  # a crash in the student's file
        tb = traceback.extract_tb(e.__traceback__)
        where = next((f"{Path(f.filename).name}:{f.lineno}" for f in reversed(tb) if "receipt_radar" in f.filename), "")
        print(f"  FAIL  {name}: {type(e).__name__}: {e} {where}")
        return "fail"
    print(f"  PASS  {name}")
    return "pass"


def main(argv: list[str]) -> int:
    no_live = "--offline" in argv
    phases = sorted({int(a) for a in argv if a.isdigit()})
    run_live = bool(phases) and not no_live
    phases = phases or [0, 1, 2, 3]
    results: dict[int, list[str]] = {}
    for phase in phases:
        print(f"\nPhase {phase}")
        for p, fn in OFFLINE:
            if p == phase:
                results.setdefault(phase, []).append(run(fn))
        if run_live or (phase == 0 and not no_live):
            if all(r == "pass" for r in results.get(phase, [])):
                for p, fn in LIVE:
                    if p == phase:
                        print(f"  ...   {fn.__name__.replace('_', ' ')} (live)")
                        results[phase].append(run(fn))
            elif any(p == phase for p, _ in LIVE):
                print("  skip  live check: fix the lines above first")
    print()
    for phase in phases:
        if any(r != "pass" for r in results.get(phase, [])):
            print(f"Next: finish Phase {phase} (the first TODO or FAIL above), then python check.py {phase}")
            return 1
    if run_live or phases == [0]:
        print(NEXT[max(phases)])
    elif len(phases) == 4:
        print("Every offline check passes. For the live checks: python check.py 1, then 2, then 3")
    else:
        print(f"Offline checks pass. Drop --offline for the live check: python check.py {max(phases)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
