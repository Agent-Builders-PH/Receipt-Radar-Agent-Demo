"""Lumen OCR: the first reader of every receipt.

Lumen is asynchronous: upload the photo, poll until it is READY, then fetch
the words. OCR is a fixed code step that runs before the agent, never a tool:
every receipt needs it, it is slow, and it costs credits, so the model should
not decide when to call it.

    OCR_MODE=cached  read ocr_cache/<name>.json (the default; no Lumen keys needed)
    OCR_MODE=live    call Lumen, then save the result to ocr_cache/<name>.json

Try it on one receipt:  python -m receipt_radar.lumen_ocr receipts/01-fastfood.jpg
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError

from .settings import LUMEN_OCR_BASE_URL, OCR_CACHE_DIR, OCR_MODE

LONG_SIDE_PX = 1500           # big phone photos are resized before Lumen and Claude see them
POLL_WAITS = [1, 2, 3]        # then every 3 s ...
POLL_LIMIT_S = 30             # ... and stop after 30 s
DONE = {"READY", "PARTIAL"}
CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff",
                 ".pdf": "application/pdf"}


@dataclass
class Word:
    text: str
    confidence: float  # 0.0 to 1.0


@dataclass
class OcrResult:
    text: str
    words: list[Word] = field(default_factory=list)
    source: str = "cached"  # "cached" or "live"


class LumenError(RuntimeError):
    pass


class LumenAuthError(LumenError):
    pass


class LumenFallback(LumenError):
    """Lumen can't help right now (credits, rate limit, outage): use the cache."""


# --------------------------------------------------------------------------- photos

def prepare_photo(path: str | Path) -> Path:
    """Upright, at most 1,500 px on the long side, saved as JPEG or PNG.

    Phones store rotation in EXIF and take 4,000 px photos; both Lumen and
    Claude read the result of this function, not the original file.
    """
    path = Path(path)
    if path.suffix.lower() in {".heic", ".heif"}:
        raise LumenError(
            f"{path.name} is an iPhone HEIC photo. Send a screenshot or a JPEG instead "
            "(on iPhone: Settings > Camera > Formats > Most Compatible)."
        )
    try:
        img = PILImage.open(path)
    except (UnidentifiedImageError, FileNotFoundError) as e:
        raise LumenError(f"Can't open {path}: {e}") from e
    img = ImageOps.exif_transpose(img)
    img.thumbnail((LONG_SIDE_PX, LONG_SIDE_PX))
    keep_png = path.suffix.lower() == ".png"
    out = Path(tempfile.gettempdir()) / f"radar-{path.stem}{'.png' if keep_png else '.jpg'}"
    if keep_png:
        img.save(out, "PNG")
    else:
        img.convert("RGB").save(out, "JPEG", quality=90)
    return out


# --------------------------------------------------------------------------- cache

def cache_path(photo: str | Path) -> Path:
    return OCR_CACHE_DIR / f"{Path(photo).stem}.json"


def load_cached(photo: str | Path) -> OcrResult:
    p = cache_path(photo)
    if not p.exists():
        raise LumenError(
            f"No cached OCR for {Path(photo).name} (looked for {p.relative_to(p.parents[1])}). "
            "Cached mode only works for the sample receipts; set OCR_MODE=live to read your own."
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    words = [Word(w["text"], float(w["confidence"])) for w in data.get("words", [])]
    return OcrResult(text=data.get("text", ""), words=words, source="cached")


def save_cache(photo: str | Path, result: OcrResult, raw: object, document_id: str) -> None:
    OCR_CACHE_DIR.mkdir(exist_ok=True)
    payload = {
        "file": Path(photo).name,
        "source": "lumen",
        "document_id": document_id,
        "text": result.text,
        "words": [{"text": w.text, "confidence": w.confidence} for w in result.words],
        "raw": raw,
    }
    cache_path(photo).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- live

def _headers() -> dict[str, str]:
    key, secret = os.getenv("LUMEN_API_KEY", ""), os.getenv("LUMEN_API_SECRET", "")
    if not key or not secret:
        raise LumenAuthError("OCR_MODE=live needs LUMEN_API_KEY and LUMEN_API_SECRET in .env.")
    return {"lumen-api-key": key, "lumen-api-secret": secret}


def _check(resp: httpx.Response) -> dict:
    """Unwrap { data, requestId } or turn the status code into the right error."""
    code = resp.status_code
    if code == 401:
        raise LumenAuthError("Lumen said 401: the API key or secret is wrong.")
    if code == 403:
        raise LumenFallback(f"Lumen said 403 (key not scoped to OCR, or out of credits): {resp.text[:200]}")
    if code in (413, 415):
        raise LumenError(f"Lumen said {code}: file too big or wrong type (not charged).")
    if code in (429, 503):
        raise LumenFallback(f"Lumen said {code}: busy, try again later.")
    if code >= 400:
        raise LumenError(f"Lumen said {code}: {resp.text[:200]}")
    body = resp.json()
    return body.get("data", body) if isinstance(body, dict) else body


def _send(client: httpx.Client, method: str, url: str, **kw) -> dict:
    """One call, with a single wait-and-retry on 429 and 503."""
    resp = client.request(method, url, **kw)
    if resp.status_code in (429, 503):
        time.sleep(3)
        resp = client.request(method, url, **kw)
    return _check(resp)


def _upload(client: httpx.Client, photo: Path) -> str:
    ctype = CONTENT_TYPES.get(photo.suffix.lower(), "image/jpeg")
    headers = {"Content-Type": ctype, "X-Lumen-Document-Name": quote(photo.name)}
    try:
        data = _send(client, "POST", "/documents", content=photo.read_bytes(), headers=headers)
    except LumenError as e:
        if "413" not in str(e) and "415" not in str(e):
            raise
        # Too big or wrong type: shrink and convert to JPEG, then retry once.
        small = Path(tempfile.gettempdir()) / f"radar-small-{photo.stem}.jpg"
        img = PILImage.open(photo).convert("RGB")
        img.thumbnail((1200, 1200))
        img.save(small, "JPEG", quality=80)
        headers = {"Content-Type": "image/jpeg", "X-Lumen-Document-Name": quote(small.name)}
        data = _send(client, "POST", "/documents", content=small.read_bytes(), headers=headers)
    return str(data["DocumentID"])


def _wait_until_ready(client: httpx.Client, doc_id: str, say=print) -> str:
    waited, i, retried = 0.0, 0, False
    while True:
        status = str(_send(client, "GET", f"/documents/{doc_id}").get("Status", "")).upper()
        say(f"  poll {i + 1}: {status or '?'}")
        if status in DONE:
            return status
        if status == "FAILED":
            if retried:
                raise LumenError("Lumen could not read this photo (FAILED twice).")
            say("  FAILED, asking Lumen to retry once")
            _send(client, "POST", f"/documents/{doc_id}/retry")
            retried = True
        pause = POLL_WAITS[i] if i < len(POLL_WAITS) else 3
        if waited + pause > POLL_LIMIT_S:
            raise LumenFallback(f"Lumen was still working after {POLL_LIMIT_S} s.")
        time.sleep(pause)
        waited += pause
        i += 1


# Lumen's word-level field names are confirmed from the portal's OCR Spec.
# The parser accepts PascalCase and camelCase so a casing change can't break it.
_TEXT_KEYS = ("Text", "text", "Value", "value", "Content", "content")
_CONF_KEYS = ("Confidence", "confidence", "Score", "score")
_WORD_LISTS = ("Words", "words")
_LINE_LISTS = ("Lines", "lines")


def _first(d: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _confidence(value) -> float:
    c = float(value)
    return c / 100 if c > 1 else c  # accept 0-1 or 0-100


def parse_pages(data) -> OcrResult:
    """Turn Lumen's pages response into plain text plus (word, confidence) pairs."""
    words: list[Word] = []
    lines: list[str] = []

    def walk(node) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        word_list = _first(node, _WORD_LISTS)
        line_list = _first(node, _LINE_LISTS)
        if isinstance(line_list, list):
            for line in line_list:
                if isinstance(line, dict):
                    t = _first(line, _TEXT_KEYS)
                    if isinstance(t, str):
                        lines.append(t)
        if isinstance(word_list, list):
            for w in word_list:
                if isinstance(w, dict):
                    t, c = _first(w, _TEXT_KEYS), _first(w, _CONF_KEYS)
                    if isinstance(t, str) and c is not None:
                        words.append(Word(t, _confidence(c)))
        for key, value in node.items():
            if key not in _WORD_LISTS and isinstance(value, (list, dict)):
                walk(value)

    walk(data)
    text = "\n".join(lines) if lines else " ".join(w.text for w in words)
    return OcrResult(text=text, words=words, source="live")


def read_live(photo: str | Path, say=print) -> OcrResult:
    photo = Path(photo)
    upright = prepare_photo(photo)
    with httpx.Client(base_url=LUMEN_OCR_BASE_URL, headers=_headers(), timeout=30) as client:
        say(f"  upload {photo.name} ...")
        doc_id = _upload(client, upright)
        say(f"  document {doc_id}")
        _wait_until_ready(client, doc_id, say)
        raw = _send(client, "GET", f"/documents/{doc_id}/pages", params={"IncludeWords": "true"})
    result = parse_pages(raw)
    if not result.words:
        raise LumenError("Lumen answered but no words were found. Check the field names in parse_pages().")
    save_cache(photo, result, raw, doc_id)
    say(f"  {len(result.words)} words, saved to ocr_cache/{photo.stem}.json")
    return result


# --------------------------------------------------------------------------- entry point

def read_receipt_text(photo: str | Path, say=print) -> OcrResult:
    """The fixed OCR step. Live mode falls back to the cache when Lumen can't help."""
    if OCR_MODE != "live":
        return load_cached(photo)
    try:
        return read_live(photo, say)
    except LumenFallback as e:
        say(f"  {e} Falling back to cached OCR.")
        return load_cached(photo)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m receipt_radar.lumen_ocr receipts/<file>")
    r = read_receipt_text(sys.argv[1])
    print(f"\n[{r.source}] {len(r.words)} words\n")
    print(r.text)
    print("\nlowest-confidence words:")
    for w in sorted(r.words, key=lambda w: w.confidence)[:5]:
        print(f"  {w.confidence:.2f}  {w.text}")
