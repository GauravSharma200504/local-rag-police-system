"""Local OCR using Tesseract (via pytesseract). Supports English + Hindi when language data is installed."""
from __future__ import annotations

import io
import json
import re
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings


class OCRUnavailable(Exception):
    pass


@dataclass
class OCRWord:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float  # PDF point coordinates (1/72 inch)


@dataclass
class PageOCR:
    paragraphs: list[str] = field(default_factory=list)
    words: list[OCRWord] = field(default_factory=list)


def _configure():
    import pytesseract

    settings = get_settings()
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    elif shutil.which("tesseract") is None:
        raise OCRUnavailable("Tesseract executable not found. Install Tesseract or set TESSERACT_CMD.")
    return pytesseract


@lru_cache
def available_languages() -> tuple[str, ...]:
    try:
        return tuple(_configure().get_languages(config=""))
    except Exception:  # noqa: BLE001
        return ()


def tesseract_version() -> str | None:
    try:
        return str(_configure().get_tesseract_version())
    except Exception:  # noqa: BLE001
        return None


def _lang_string() -> str:
    wanted = [lang for lang in get_settings().ocr_languages.split("+") if lang]
    have = set(available_languages())
    usable = [lang for lang in wanted if lang in have] or (["eng"] if "eng" in have else [])
    if not usable:
        raise OCRUnavailable("No requested Tesseract language data installed (need eng and/or hin)")
    return "+".join(usable)


def ocr_image_bytes(png_bytes: bytes, dpi: int = 300) -> PageOCR:
    from PIL import Image

    pytesseract = _configure()
    img = Image.open(io.BytesIO(png_bytes))
    try:
        data = pytesseract.image_to_data(img, lang=_lang_string(), output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as e:
        raise OCRUnavailable(str(e)) from e
    scale = 72.0 / dpi
    result = PageOCR()
    paras: dict[tuple[int, int], list[list[str]]] = {}
    order: list[tuple[int, int]] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word or float(data["conf"][i]) < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i])
        if key not in paras:
            paras[key] = []
            order.append(key)
        lines = paras[key]
        line_no = data["line_num"][i]
        if not lines or lines[-1][0] != line_no:
            lines.append([line_no])
        lines[-1].append(word)
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        result.words.append(OCRWord(word, x * scale, y * scale, (x + w) * scale, (y + h) * scale))
    for key in order:
        text = "\n".join(" ".join(str(t) for t in line[1:]) for line in paras[key])
        text = fix_ocr_text(text)
        if not text.strip():
            continue
        prev = result.paragraphs[-1] if result.paragraphs else ""
        # Tesseract sometimes splits one sentence into two paragraphs: re-join when the previous
        # paragraph does not end a sentence and the next one continues in lower case or with a digit.
        if prev and not prev.rstrip().endswith((".", ":", "?", "!", "।")) and re.match(r"^[a-z0-9(,]", text.strip()):
            result.paragraphs[-1] = prev + " " + text.strip()
        else:
            result.paragraphs.append(text.strip())
    return result


_PIPE_I = re.compile(r"(^|(?<=\s))\|(?=\s+[a-z])")


def fix_ocr_text(text: str) -> str:
    """Conservative fixes for frequent Tesseract confusions: a lone '|' before a lower-case word is the pronoun 'I'."""
    return _PIPE_I.sub("I", text)


def save_words(directory: Path, page: int, words: list[OCRWord]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"ocr_page_{page}.json").write_text(
        json.dumps([w.__dict__ for w in words], ensure_ascii=False), encoding="utf-8"
    )


def load_words(directory: Path, page: int) -> list[OCRWord]:
    f = directory / f"ocr_page_{page}.json"
    if not f.exists():
        return []
    return [OCRWord(**w) for w in json.loads(f.read_text(encoding="utf-8"))]
