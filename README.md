<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/ab-logo-white.png">
    <img src="assets/ab-logo-dark.png" alt="Agent Builders Philippines" width="300">
  </picture>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/lumen-logo-white.png">
    <img src="assets/lumen-logo-dark.png" alt="Lumen" width="150">
  </picture>
</p>

# Receipt Radar Agent: build-along template

**Agent Builders PH · Episode 2 · Fri, Nov 6, 2026, 2:00 PM PHT.** Snap a receipt and get one logged expense plus a budget line. Lumen OCR reads the raw text, Claude reads the photo and fills in a form, and an [Agno](https://docs.agno.com) agent logs it with strict tools.

```
python radar.py receipts/01-fastfood.jpg

Logged: 2026-10-28 | Bida Burger | ₱289 | Food
Food: ₱289 of ₱4,000 in October 2026 (₱3,711 left)
```

You build it in the session by filling in **eight `TODO`s** across four files.

📘 **Follow [MODULE.md](MODULE.md)**, the step-by-step module.

## Setup in five commands (Windows PowerShell)

```powershell
uv venv --python 3.12
.venv\Scripts\activate
uv pip install -r requirements.txt
copy .env.example .env          # then paste your Anthropic key into .env
python check.py
```

macOS / Linux: `source .venv/bin/activate` and `cp .env.example .env`.

You need Python 3.12, [uv](https://docs.astral.sh/uv/), an Anthropic API key, and the Lumen OCR key and secret the host gives you. The sample receipts' OCR is saved in `ocr_cache/`, so you build in cached mode, then use Lumen live for your own receipts.

## The three phases

| Phase | Files you edit | TODOs | Check |
|---|---|---|---|
| 1. Read | `receipt_radar/schema.py`, `receipt_radar/reader.py` | 1 to 3 | `python check.py 1` |
| 2. Log | `receipt_radar/tools.py` | 4 to 6 | `python check.py 2` |
| 3. Guard and test | `receipt_radar/gate.py` | 7, then 8 = run all of `cases.json` | `python check.py 3` |

`check.py` prints **PASS**, **FAIL** (with the one thing to fix) or **TODO** (not written yet).

**Prefer clicking?** Run `python app.py` and open http://127.0.0.1:8765. You get the same agent in your browser: pick a receipt and watch each step print on a till tape. Until you finish the TODOs, it shows which one the pipeline stopped at.

**Behind?** Copy the matching file from `solutions/` and keep going. For example: `copy solutions\schema.py receipt_radar\schema.py`.
