"""Receipt Radar, the finished command line. You don't need to edit this file.

    python radar.py receipts/01-fastfood.jpg
    python radar.py receipts/02-ewallet.png "magkano na sa food?"
    python radar.py --ask "How much did I spend on Transport this month?"
    python radar.py --ask "Set my Food budget to 5000"

The pipeline, in order:
    photo -> Lumen OCR (code) -> Reader agent (Claude vision + schema)
          -> gate (code) -> Logger agent (Claude + strict tools) -> reply
Code does the fixed steps; the model does the judgment.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from receipt_radar import gate, ledger, tools
from receipt_radar.logger import ask, log_receipt
from receipt_radar.lumen_ocr import LumenError, read_receipt_text
from receipt_radar.reader import read_receipt
from receipt_radar.schema import Receipt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # so ₱ prints on Windows


@dataclass
class Outcome:
    status: str                        # logged | duplicate | stopped | not_logged | error | todo
    receipt: Receipt | None = None
    gate: gate.GateResult | None = None
    reply: str = ""
    tools_called: list[str] = field(default_factory=list)
    rows_added: int = 0
    ocr: object = None                 # the OcrResult, for the UI


def tool_names(run) -> list[str]:
    return [t.tool_name for t in (getattr(run, "tools", None) or []) if getattr(t, "tool_name", None)]


def process_receipt(photo: str | Path, question: str | None = None, confirm=None, say=print) -> Outcome:
    """Read, check and log one receipt. `confirm` is asked when the gate stops (None = never log)."""
    photo = Path(photo)
    if not photo.exists():
        return Outcome("error", reply=f"No such file: {photo}")

    # 1. Lumen OCR, a fixed code step.
    say(f"1. Lumen OCR reads {photo.name}")
    try:
        ocr = read_receipt_text(photo, say=lambda m: say(m))
    except LumenError as e:
        return Outcome("error", reply=str(e))
    say(f"   {len(ocr.words)} words ({ocr.source})")

    # 2. The Reader agent fills the Receipt form from the photo.
    say("2. Claude reads the photo")
    try:
        receipt = read_receipt(photo, ocr)
    except NotImplementedError as e:  # the template before TODO 2
        return Outcome("todo", reply=str(e), ocr=ocr)
    if receipt:
        say(f"   {receipt.date} | {receipt.vendor} | {ledger.peso(receipt.amount_php)} | "
            f"{receipt.category} | sure={receipt.sure}")

    # 3. The gate: nothing is logged until the checks pass.
    result = gate.check(receipt, ocr)
    say(f"3. Gate: {'pass' if result.ok else f'stopped at rule {result.rule}'}. {result.reason}")
    if not result.ok:
        if not (receipt and confirm and receipt.amount_php > 0 and confirm(receipt, result)):
            return Outcome("stopped", receipt, result,
                           reply="Not logged. Check the receipt and try again, or log it yourself.", ocr=ocr)
        say("   You confirmed it, so the Logger gets it.")

    # 4. The Logger agent decides whether and how to log, using strict tools.
    say("4. The Logger decides")
    tools.start_receipt_run(ledger.photo_hash(photo))
    before = len(ledger.read_rows())
    run = log_receipt(receipt, question)
    added = len(ledger.read_rows()) - before
    called = tool_names(run)
    reply = str(run.content or "").strip()
    if added:
        status = "logged"
    elif any("DUPLICATE" in str(t.result) for t in (run.tools or []) if t.tool_name == "find_duplicate"):
        status = "duplicate"
    else:
        status = "not_logged"
    return Outcome(status, receipt, result, reply, called, added, ocr)


def ask_yes_no(receipt: Receipt, result: gate.GateResult) -> bool:
    if not sys.stdin.isatty():
        return False
    answer = input(f"   Log {ledger.peso(receipt.amount_php)} at {receipt.vendor} anyway? [y/N] ")
    return answer.strip().lower() in {"y", "yes", "oo"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Snap a receipt, get one logged expense and a budget line.")
    p.add_argument("photo", nargs="?", help="a receipt photo, e.g. receipts/01-fastfood.jpg")
    p.add_argument("question", nargs="?", help="an optional question, e.g. 'magkano na sa food?'")
    p.add_argument("--ask", metavar="TEXT", help="ask about spending or set a budget, no receipt")
    args = p.parse_args(argv)

    if args.ask:
        run = ask(args.ask)
        print(str(run.content or "").strip())
        return 0
    if not args.photo:
        p.print_help()
        return 2

    out = process_receipt(args.photo, args.question, confirm=ask_yes_no)
    print()
    if out.status == "logged":
        rows = ledger.read_rows()
        r = rows[-1]
        print(f"Logged: {r['date']} | {r['vendor']} | {ledger.peso(float(r['amount_php']))} | {r['category']}")
        print(ledger.budget_line(r["category"], r["date"][:7]))
    if out.reply:
        print(out.reply)
    return 0 if out.status in {"logged", "duplicate"} else 1


if __name__ == "__main__":
    sys.exit(main())
