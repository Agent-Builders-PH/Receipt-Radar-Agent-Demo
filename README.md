<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/ab-logo-white.png">
    <img src="assets/ab-logo-dark.png" alt="Agent Builders Philippines" width="320">
  </picture>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/lumen-logo-white.png">
    <img src="assets/lumen-logo-dark.png" alt="Lumen" width="150">
  </picture>
</p>

# Receipt Radar Agent: starter template

**Agent Builders PH · Episode 2.** Build a personal agent that turns a photo of a Philippine receipt into one logged expense and a budget line. Lumen OCR reads every word on the receipt, Claude reads the photo and fills in a form, and an [Agno](https://docs.agno.com) agent logs it with strict tools.

You'll build it in three phases: a **Reader** agent that always answers with a filled-in form, a **Logger** agent whose tools refuse bad calls, and a **gate** in plain Python that stops any receipt the two readers don't agree on.

📘 **Follow [MODULE.md](MODULE.md)**. It walks you through everything, from setup to logging your own receipts.

🧭 **Prefer a click-through checklist?** Open the **[walkthrough guide](https://claude.ai/artifact/VB9qtvfkokaVuCZrqqaeLm)**. It has an interactive map of how the agent works, every step with copy buttons, and tick-boxes that remember your progress. A copy is also in this repo as [WALKTHROUGH.html](WALKTHROUGH.html). GitHub shows that file as source code, so open your local copy after cloning: `start WALKTHROUGH.html` (Windows) or `open WALKTHROUGH.html` (macOS).

🖥️ **Prefer a browser?** Run `python app.py` and open http://127.0.0.1:8765: the same agent, with each step printed on a till tape. Until your TODOs are done, it shows which one the pipeline stopped at.

## Get started

```bash
uv venv --python 3.12
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
uv pip install -r requirements.txt

cp .env.example .env            # Windows: copy .env.example .env
python check.py                 # shows what's left to build
```

In `.env`, paste your Anthropic key, and the Lumen OCR key and secret the host gives you. Leave `OCR_MODE=cached`: the 10 sample receipts' OCR is already saved in `ocr_cache/`, so building never spends Lumen credits.

## How this template works

The project structure is ready. The parts you build are marked **`TODO`**, numbered to match the module:

| TODO | File | Module section |
|---|---|---|
| 1 | `receipt_radar/schema.py` → `Receipt` | §5 Phase 1: the Receipt form |
| 2 | `receipt_radar/reader.py` → `build_reader` | §5 the Reader agent |
| 3 | `receipt_radar/reader.py` → `read_receipt` | §5 send the photo and the OCR text |
| 4 | `receipt_radar/tools.py` → `log_expense` | §6 Phase 2: a strict tool |
| 5 | `receipt_radar/tools.py` → `find_duplicate` | §6 the same way |
| 6 | `receipt_radar/tools.py` → `RECEIPT_TOOLS` | §6 the Logger's tool list |
| 7 | `receipt_radar/gate.py` → `check` | §7 Phase 3: gate rules 3 to 5 |
| 8 | `cases.json`, through `check.py` | §7 run all 10 cases |

After each TODO, run the offline checks for that phase. No Claude calls, no cost:

```bash
python check.py 1 --offline     # PASS / FAIL (with a hint) / TODO
```

Drop `--offline` when a phase passes, and `check.py` sends a few real receipts to Claude. Behind by more than a phase? Copy the finished file from `solutions/` (MODULE §9).

When `python check.py 3` prints `10 of 10 cases pass`, you're done. 🎉

## Never commit secrets

`.env` is in `.gitignore`, and so is `my-receipts/`, where your own receipt photos go. Keep it that way, never paste a key in the group chat, and keep your own copy of this repo **private**.
