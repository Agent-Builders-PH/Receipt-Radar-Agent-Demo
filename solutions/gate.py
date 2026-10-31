"""The gate: plain Python checks between the Reader and the Logger (Phase 3).

Two readers looked at the same receipt: Lumen OCR and Claude. Nothing is
logged until they agree. The rules run in order; the first one that fails
stops the run and asks you.

  1. The Reader's reply is a valid Receipt.
  2. Claude says it is sure.
  3. The amount is above 0.
  4. The amount appears in the Lumen OCR words (commas and a peso sign allowed).
  5. That OCR word's confidence is above the threshold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .lumen_ocr import OcrResult, Word
from .schema import Receipt

# Tuned on the 10 samples: clear prints read 0.90 and up; faded or blurry ones fall below 0.75.
CONFIDENCE_THRESHOLD = 0.80


@dataclass
class GateResult:
    ok: bool
    rule: int          # the rule that failed, or 0 when every rule passed
    reason: str


def as_amount(text: str) -> float | None:
    """'₱1,235.00' -> 1235.0, 'PHP289' -> 289.0, 'TOTAL' -> None."""
    cleaned = re.sub(r"(?i)php|₱|\s|,", "", text).rstrip(".:")
    if cleaned[:1] in {"P", "p"} and cleaned[1:2].isdigit():
        cleaned = cleaned[1:]  # 'P289.00', the way many tills print the peso sign
    try:
        return float(cleaned)
    except ValueError:
        return None


def find_amount(ocr: OcrResult, amount: float) -> Word | None:
    """The most confident OCR word that equals the amount, if there is one."""
    matches = [w for w in ocr.words if (v := as_amount(w.text)) is not None and abs(v - amount) < 0.005]
    return max(matches, key=lambda w: w.confidence, default=None)


def check(receipt: Receipt | None, ocr: OcrResult, threshold: float = CONFIDENCE_THRESHOLD) -> GateResult:
    # Rule 1: a refusal or a reply cut off at max_tokens is not a Receipt.
    if not isinstance(receipt, Receipt):
        return GateResult(False, 1, "Claude's reply was not a complete Receipt.")

    # Rule 2: Claude flagged a guess.
    if not receipt.sure:
        fields = ", ".join(receipt.unsure_about) or "some fields"
        return GateResult(False, 2, f"Claude isn't sure about: {fields}.")

    # TODO 7 (answer): rules 3 to 5
    # Rule 3: an amount of 0 or less is never a real expense.
    if receipt.amount_php <= 0:
        return GateResult(False, 3, f"The amount {receipt.amount_php} is not above 0.")

    # Rule 4: the second reader must have seen the same number.
    word = find_amount(ocr, receipt.amount_php)
    if word is None:
        return GateResult(False, 4, f"Claude read ₱{receipt.amount_php:,.2f}, but Lumen OCR never saw that number.")

    # Rule 5: ... and seen it clearly.
    if word.confidence < threshold:
        return GateResult(
            False, 5,
            f"Lumen saw '{word.text}' with confidence {word.confidence:.2f}, below {threshold:.2f}.",
        )

    return GateResult(True, 0, "Both readers agree.")
