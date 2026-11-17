"""Text extraction for PDF (digital + scanned via OCR), DOCX, TXT and images.

Every extracted paragraph keeps its 1-based page number so citations can point to the original page.
"""
from __future__ import annotations

import io
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.core.config import get_settings
from app.ingestion import ocr


@dataclass
class Block:
    text: str
    page: int
    is_heading: bool = False


@dataclass
class PageText:
    page: int
    blocks: list[Block] = field(default_factory=list)
    ocr_used: bool = False
    ocr_failed: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


@dataclass
class ExtractionResult:
    pages: list[PageText]
    page_count: int
    ocr_pages: list[int] = field(default_factory=list)
    ocr_failed_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


class ExtractionError(Exception):
    pass


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg"}


def extract(path: Path, ext: str, ocr_word_dir: Path | None = None, progress=None) -> ExtractionResult:
    ext = ext.lower()
    if ext == ".pdf":
        return extract_pdf(path, ocr_word_dir, progress)
    if ext == ".docx":
        return extract_docx(path)
    if ext == ".txt":
        return extract_txt(path)
    if ext in {".png", ".jpg", ".jpeg"}:
        return extract_image(path, ocr_word_dir, progress)
    raise ExtractionError(f"Unsupported file type: {ext}")


# ---------------------------------------------------------------- PDF
def _pdf_page_blocks(page: pymupdf.Page, page_no: int) -> list[Block]:
    data = page.get_text("dict", sort=True, flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_LIGATURES)
    raw: list[tuple[str, bool, float]] = []
    sizes: list[float] = []
    for b in data.get("blocks", []):
        if b.get("type") != 0:
            continue
        lines, all_bold, max_size = [], True, 0.0
        for line in b.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            lines.append("".join(s["text"] for s in line["spans"]))
            for s in spans:
                sizes.append(s["size"])
                max_size = max(max_size, s["size"])
                if not (s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower()):
                    all_bold = False
        text = "\n".join(lines).strip()
        if text:
            raw.append((text, all_bold, max_size))
    body = statistics.median(sizes) if sizes else 10.0
    blocks = []
    for text, bold, size in raw:
        short = len(text) <= 120 and "\n" not in text.strip()
        heading = short and (bold or size >= body + 1.5) and not text.rstrip().endswith((".", ","))
        blocks.append(Block(text=text, page=page_no, is_heading=heading))
    return blocks


def extract_pdf(path: Path, ocr_word_dir: Path | None = None, progress=None) -> ExtractionResult:
    settings = get_settings()
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # noqa: BLE001
        raise ExtractionError(f"Could not open PDF: {e}") from e
    if doc.needs_pass:
        raise ExtractionError("PDF is password protected")
    result = ExtractionResult(pages=[], page_count=doc.page_count)
    for i, page in enumerate(doc):
        page_no = i + 1
        blocks = _pdf_page_blocks(page, page_no)
        text_len = sum(len(b.text) for b in blocks)
        pt = PageText(page=page_no, blocks=blocks)
        if text_len < settings.ocr_min_chars_per_page:
            # Likely a scanned page: render and OCR.
            if progress:
                progress("ocr", f"OCR on page {page_no}/{doc.page_count}")
            try:
                pix = page.get_pixmap(dpi=settings.ocr_dpi)
                page_ocr = ocr.ocr_image_bytes(pix.tobytes("png"), dpi=settings.ocr_dpi)
                if ocr_word_dir is not None:
                    ocr.save_words(ocr_word_dir, page_no, page_ocr.words)
                ocr_blocks = [Block(text=p, page=page_no) for p in page_ocr.paragraphs]
                if ocr_blocks:
                    pt.blocks = ocr_blocks
                pt.ocr_used = True
                result.ocr_pages.append(page_no)
            except ocr.OCRUnavailable as e:
                pt.ocr_failed = True
                result.ocr_failed_pages.append(page_no)
                result.warnings.append(f"Page {page_no}: OCR unavailable ({e})")
        result.pages.append(pt)
    doc.close()
    return result


# ---------------------------------------------------------------- DOCX
def extract_docx(path: Path) -> ExtractionResult:
    """Extract paragraphs and tables in document order.

    DOCX files have no fixed pagination; page numbers are approximated from explicit page breaks
    and Word's last-rendered page-break markers.
    """
    import docx
    from docx.oxml.ns import qn

    try:
        d = docx.Document(str(path))
    except Exception as e:  # noqa: BLE001
        raise ExtractionError(f"Could not open DOCX: {e}") from e

    page = 1
    pages: dict[int, PageText] = {}

    def add(text: str, heading: bool):
        text = text.strip()
        if text:
            pages.setdefault(page, PageText(page=page)).blocks.append(Block(text=text, page=page, is_heading=heading))

    body = d.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            breaks = child.findall(".//" + qn("w:br"))
            if any(b.get(qn("w:type")) == "page" for b in breaks) or child.findall(".//" + qn("w:lastRenderedPageBreak")):
                if pages.get(page) and pages[page].blocks:
                    page += 1
            texts = "".join(t.text or "" for t in child.iter(qn("w:t")))
            style = child.find(qn("w:pPr") + "/" + qn("w:pStyle"))
            style_name = style.get(qn("w:val")) if style is not None else ""
            add(texts, heading=style_name.lower().startswith(("heading", "title")))
        elif child.tag == qn("w:tbl"):
            rows = []
            for tr in child.iter(qn("w:tr")):
                cells = ["".join(t.text or "" for t in tc.iter(qn("w:t"))).strip() for tc in tr.iter(qn("w:tc"))]
                rows.append(" | ".join(cells))
            add("\n".join(rows), heading=False)
    ordered = [pages[k] for k in sorted(pages)]
    return ExtractionResult(pages=ordered, page_count=max(1, len(ordered)))


# ---------------------------------------------------------------- TXT
def extract_txt(path: Path) -> ExtractionResult:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractionError("Could not decode text file")
    result = ExtractionResult(pages=[], page_count=0)
    for i, page_text in enumerate(text.split("\f")):  # form-feed = page break
        page_no = i + 1
        paras = [p.strip() for p in page_text.replace("\r\n", "\n").split("\n\n") if p.strip()]
        blocks = []
        for p in paras:
            heading = len(p) <= 100 and "\n" not in p and (p.isupper() or p.endswith(":")) and not p.endswith(".")
            blocks.append(Block(text=p, page=page_no, is_heading=heading))
        result.pages.append(PageText(page=page_no, blocks=blocks))
    result.page_count = len(result.pages)
    return result


# ---------------------------------------------------------------- Images
def extract_image(path: Path, ocr_word_dir: Path | None = None, progress=None) -> ExtractionResult:
    from PIL import Image

    if progress:
        progress("ocr", "OCR on image")
    img = Image.open(path)
    dpi = int(img.info.get("dpi", (300, 300))[0] or 300)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    try:
        page_ocr = ocr.ocr_image_bytes(buf.getvalue(), dpi=dpi)
    except ocr.OCRUnavailable as e:
        raise ExtractionError(f"OCR unavailable: {e}") from e
    if ocr_word_dir is not None:
        ocr.save_words(ocr_word_dir, 1, page_ocr.words)
    pt = PageText(page=1, blocks=[Block(text=p, page=1) for p in page_ocr.paragraphs], ocr_used=True)
    return ExtractionResult(pages=[pt], page_count=1, ocr_pages=[1])
