"""Receipt Radar in your browser. You don't need to edit this file.

    python app.py            # then open http://127.0.0.1:8765

A small local web page on top of radar.py: pick a receipt, watch the four
steps (Lumen OCR, the Reader, the gate, the Logger), and see your ledger and
budget update. It uses the same code as the command line, so in the template
it shows exactly which TODO the pipeline stops at.

Plain Python standard library: no web framework to install. It listens on
127.0.0.1 only, so nobody else on the Wi-Fi can reach it.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import traceback
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from radar import Outcome, process_receipt, tool_names
from receipt_radar import ledger, settings, tools
from receipt_radar.logger import ask
from receipt_radar.schema import Receipt

ROOT = Path(__file__).resolve().parent
UI = ROOT / "ui" / "index.html"
MY_RECEIPTS = ROOT / "my-receipts"          # your own photos (in .gitignore)
FOLDERS = {"receipts": settings.RECEIPTS_DIR, "my-receipts": MY_RECEIPTS}
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MAX_UPLOAD = 10 * 1024 * 1024               # Lumen's limit is 10 MiB
PORT = int(os.getenv("RADAR_PORT", "8765"))
LOCK = threading.Lock()                     # one receipt at a time: the tools keep per-run state

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# --------------------------------------------------------------------------- what the page shows

def photos() -> list[dict]:
    out = []
    for src, folder in FOLDERS.items():
        if folder.exists():
            for p in sorted(folder.iterdir()):
                if p.suffix.lower() in PHOTO_TYPES:
                    out.append({"src": src, "name": p.name})
    return out


def months_in_ledger(rows: list[dict]) -> list[str]:
    months = {r["date"][:7] for r in rows if len(r.get("date", "")) >= 7}
    months.add(date.today().strftime("%Y-%m"))
    return sorted(months, reverse=True)


def budget_summary(month: str) -> list[dict]:
    budget = ledger.load_budget()
    rows = []
    for cat in settings.CATEGORIES:
        spent = ledger.spent(cat, month)
        limit = budget.get(cat)
        if limit is None and not spent:
            continue
        rows.append({"category": cat, "spent": spent, "limit": limit})
    return rows


def state(month: str | None = None) -> dict:
    rows = ledger.read_rows()
    months = months_in_ledger(rows)
    latest_row_month = rows[-1]["date"][:7] if rows else months[0]
    month = month if month in months else latest_row_month
    return {
        "ocr_mode": settings.OCR_MODE,
        "model": settings.MODEL,
        "photos": photos(),
        "month": month,
        "months": months,
        "budget": budget_summary(month),
        "rows": list(reversed(rows))[:100],
    }


def hint_for(out: Outcome) -> str:
    """Point template users at the TODO that stopped the run."""
    if out.status == "todo":
        return out.reply
    if out.status == "stopped" and out.gate and out.gate.rule == 1:
        if not Receipt.model_fields:
            return "The Receipt form has no fields yet: TODO 1 in receipt_radar/schema.py."
        return "The Reader returned nothing. Is TODO 3 done in receipt_radar/reader.py?"
    names = [getattr(t, "name", None) for t in tools.RECEIPT_TOOLS]
    if out.status == "not_logged" and "log_expense" not in names:
        return "The Logger has no log_expense tool yet: TODOs 4 to 6 in receipt_radar/tools.py."
    return ""


def outcome_json(out: Outcome) -> dict:
    ocr = out.ocr
    data = {
        "status": out.status,
        "reply": out.reply,
        "hint": hint_for(out),
        "tools": out.tools_called,
        "ocr": None,
        "receipt": None,
        "gate": None,
        "row": None,
    }
    if ocr is not None:
        lowest = sorted(ocr.words, key=lambda w: w.confidence)[:3]
        data["ocr"] = {
            "source": ocr.source,
            "count": len(ocr.words),
            "text": ocr.text,
            "lowest": [{"text": w.text, "confidence": round(w.confidence, 2)} for w in lowest],
        }
    if out.receipt is not None:
        data["receipt"] = json.loads(out.receipt.model_dump_json())
    if out.gate is not None:
        data["gate"] = {"ok": out.gate.ok, "rule": out.gate.rule, "reason": out.gate.reason}
    if out.status == "logged":
        row = ledger.read_rows()[-1]
        data["row"] = {**row, "budget_line": ledger.budget_line(row["category"], row["date"][:7])}
    return data


def friendly(e: Exception) -> str:
    name = type(e).__name__
    if name == "AuthenticationError":
        return "Anthropic rejected the key in .env (401). Paste a working key into .env and restart the app."
    if isinstance(e, NotImplementedError):
        return str(e)
    return f"{name}: {e}"


# --------------------------------------------------------------------------- the web server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, code: int = 200) -> None:
        self.send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

    def send_file(self, path: Path) -> None:
        if not path.is_file():
            return self.send_json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send(path.read_bytes(), ctype)

    def body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # GET ---------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            return self.send(UI.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/state":
            return self.send_json(state((q.get("month") or [None])[0]))
        if url.path == "/photo":
            folder = FOLDERS.get((q.get("src") or [""])[0])
            name = Path(unquote((q.get("name") or [""])[0])).name
            return self.send_file(folder / name) if folder and name else self.send_json({"error": "not found"}, 404)
        if url.path.startswith("/assets/"):
            return self.send_file(ROOT / "assets" / Path(url.path).name)
        self.send_json({"error": "not found"}, 404)

    # POST --------------------------------------------------------------
    def do_POST(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/upload":
                return self.upload()
            if url.path == "/api/process":
                return self.process()
            if url.path == "/api/ask":
                return self.ask()
            if url.path == "/api/clear":
                return self.clear()
            self.send_json({"error": "not found"}, 404)
        except Exception as e:  # show the problem on the page, and the details in the terminal
            traceback.print_exc()
            self.send_json({"error": friendly(e)}, 500)

    def upload(self):
        name = Path(unquote(self.headers.get("X-Filename", ""))).name
        n = int(self.headers.get("Content-Length") or 0)
        if Path(name).suffix.lower() not in PHOTO_TYPES:
            return self.send_json({"error": "Use a JPEG, PNG or WebP photo."}, 400)
        if n > MAX_UPLOAD:
            return self.send_json({"error": "That photo is over 10 MB. Take a smaller one or a screenshot."}, 400)
        MY_RECEIPTS.mkdir(exist_ok=True)
        (MY_RECEIPTS / name).write_bytes(self.rfile.read(n))
        self.send_json({"src": "my-receipts", "name": name})

    def process(self):
        req = self.body_json()
        folder = FOLDERS.get(req.get("src", ""))
        name = Path(req.get("name", "")).name
        if not folder or not (folder / name).is_file():
            return self.send_json({"error": "Pick a receipt first."}, 400)
        question = (req.get("question") or "").strip() or None
        confirm = (lambda receipt, result: True) if req.get("force") else None
        with LOCK:
            out = process_receipt(folder / name, question, confirm=confirm, say=lambda m: print(m))
        self.send_json(outcome_json(out))

    def ask(self):
        question = (self.body_json().get("question") or "").strip()
        if not question:
            return self.send_json({"error": "Type a question first."}, 400)
        with LOCK:
            run = ask(question)
        self.send_json({"reply": str(run.content or "").strip(), "tools": tool_names(run)})

    def clear(self):
        if not self.body_json().get("confirm"):
            return self.send_json({"error": "Not cleared."}, 400)
        settings.EXPENSES_CSV.parent.mkdir(parents=True, exist_ok=True)
        settings.EXPENSES_CSV.write_text(",".join(ledger.COLUMNS) + "\n", encoding="utf-8")
        self.send_json({"ok": True})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Receipt Radar is running at {url}  (OCR_MODE={settings.OCR_MODE}, model {settings.MODEL})")
    print("Press Ctrl+C to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
