"""Render a document page as PNG with the cited passage highlighted, and return page text."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from app.ingestion import ocr
from app.ingestion.extractors import extract
from app.ingestion.pipeline import processed_dir_for
from app.models import Document

_W = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)


def _passage_pieces(passage: str) -> list[str]:
    passage = passage.replace("…", " ").strip()
    pieces = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+|\n+", passage) if len(p.strip()) >= 12]
    return pieces or ([passage] if passage else [])


def _ocr_word_rects(words: list[ocr.OCRWord], passage: str) -> list[pymupdf.Rect]:
    ptoks = [t.lower() for t in _W.findall(passage)]
    wtoks = [(_W.findall(w.text.lower()) or [""])[0] for w in words]
    if not ptoks or not wtoks:
        return []
    best_i, best = -1, 0
    probe = ptoks[: min(8, len(ptoks))]
    for i in range(len(wtoks)):
        score = sum(1 for j, t in enumerate(probe) if i + j < len(wtoks) and wtoks[i + j] == t)
        if score > best:
            best_i, best = i, score
    if best < min(3, len(probe)):
        return []
    span = words[best_i: best_i + len(ptoks)]
    return [pymupdf.Rect(w.x0, w.y0, w.x1, w.y1) for w in span]


def render_page_png(doc: Document, page_no: int, passage: str | None, zoom: float = 1.6) -> tuple[bytes, int]:
    """Returns (png_bytes, highlight_count)."""
    path = Path(doc.stored_path)
    if doc.file_ext in (".png", ".jpg", ".jpeg"):
        with pymupdf.open(path) as img:
            pdf = pymupdf.open("pdf", img.convert_to_pdf())
    elif doc.file_ext == ".pdf":
        pdf = pymupdf.open(path)
    else:
        raise ValueError("Page images are only available for PDF and image documents")
    if not 1 <= page_no <= pdf.page_count:
        raise IndexError("Page out of range")
    page = pdf[page_no - 1]
    hits = 0
    if passage:
        rects: list[pymupdf.Rect] = []
        if page_no in (doc.ocr_pages or []):
            words = ocr.load_words(processed_dir_for(doc.id), page_no)
            rects = _ocr_word_rects(words, passage)
        else:
            for piece in _passage_pieces(passage):
                found = page.search_for(piece)
                if not found and len(piece) > 60:
                    found = page.search_for(piece[:60])
                rects.extend(found)
        for r in rects:
            annot = page.add_highlight_annot(r)
            annot.set_colors(stroke=(1, 0.85, 0.1))
            annot.update()
        hits = len(rects)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
    data = pix.tobytes("png")
    pdf.close()
    return data, hits


def page_text(doc: Document, page_no: int) -> str:
    if doc.file_ext == ".pdf" and page_no in (doc.ocr_pages or []):
        words = ocr.load_words(processed_dir_for(doc.id), page_no)
        return " ".join(w.text for w in words)
    if doc.file_ext in (".png", ".jpg", ".jpeg"):
        return " ".join(w.text for w in ocr.load_words(processed_dir_for(doc.id), 1))
    result = extract(Path(doc.stored_path), doc.file_ext)
    for p in result.pages:
        if p.page == page_no:
            return p.text
    raise IndexError("Page out of range")
