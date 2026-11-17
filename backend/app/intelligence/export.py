"""Export reports (case summary, comparison) to PDF (PyMuPDF Story) and DOCX (python-docx)."""
from __future__ import annotations

import html
import io
import re

import pymupdf

_MARK = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")


def report_to_blocks(report_type: str, title: str, content: dict, status: str) -> list[tuple[str, str]]:
    """Normalize a report into (kind, text) blocks: kind in h1, h2, p, li, small."""
    b: list[tuple[str, str]] = [("h1", title)]
    b.append(("small", f"Status: {'HUMAN VERIFIED' if status == 'human_verified' else 'DRAFT - requires human verification'}"))
    if content.get("disclaimer"):
        b.append(("small", content["disclaimer"]))
    if content.get("generated_at"):
        b.append(("small", f"Generated: {content['generated_at']}   Model: {content.get('model', '-')}"))
    if report_type == "case_summary":
        b.append(("h2", "Source documents"))
        for d in content.get("documents", []):
            b.append(("li", f"{d['title']} ({d['doc_type']}, {d['pages']} page(s))"))
        for s in content.get("sections", []):
            b.append(("h2", s["title"]))
            b.append(("p", s["text"]))
        if content.get("important_dates"):
            b.append(("h2", "Important dates"))
            for d in content["important_dates"]:
                for ev in d["events"][:6]:
                    b.append(("li", f"{d['date']}{' ' + ev['time'] if ev.get('time') else ''} - {ev['description']} "
                                    f"({ev['document_title']}, p.{ev['page']}; {ev['nature']})"))
        if content.get("people"):
            b.append(("h2", "People and entities mentioned"))
            for p in content["people"][:30]:
                srcs = "; ".join(f"{s['document_title']} p.{s['page']}" for s in p["sources"][:4])
                b.append(("li", f"{p['value']} - {p['mentions']} mention(s) [{srcs}]"))
        if content.get("witness_statements"):
            b.append(("h2", "Witness statements"))
            for w in content["witness_statements"]:
                b.append(("p", f"{w['document_title']}: {w['text']}"))
        if content.get("missing_information"):
            b.append(("h2", "Missing information and unresolved discrepancies"))
            for m in content["missing_information"]:
                b.append(("li", m))
    elif report_type == "comparison":
        s = content.get("structured", {})
        b.append(("p", f"Document A: {content.get('a', {}).get('title')}   Document B: {content.get('b', {}).get('title')}"))
        for key, head in (("conflicts", "Potentially conflicting statements"), ("common", "Common facts"),
                          ("different", "Different facts"), ("missing", "Missing information")):
            b.append(("h2", head))
            for item in s.get(key, []):
                if key == "conflicts":
                    b.append(("li", item["message"]))
                elif key == "common":
                    b.append(("li", f"{item['label']}: {item['value']} (A p.{item['a']['page']}, B p.{item['b']['page']})"))
                elif key == "different":
                    side = item["only_in"]
                    b.append(("li", f"{item['label']}: {item['value']} - only in {side.upper()} (p.{item[side]['page']})"))
                else:
                    b.append(("li", item["message"]))
        if content.get("narrative", {}).get("text"):
            b.append(("h2", "AI narrative comparison"))
            b.append(("p", content["narrative"]["text"]))
    cites = content.get("citations") or content.get("narrative", {}).get("citations") or []
    if cites:
        b.append(("h2", "Citations"))
        for c in cites:
            b.append(("li", f"[{c['label']}] {c['document_title']}, page {c['page']}: \"{c['passage']}\""))
    return b


def to_pdf(blocks: list[tuple[str, str]]) -> bytes:
    parts = []
    for kind, text in blocks:
        t = html.escape(text).replace("\n", "<br/>")
        if kind == "li":
            parts.append(f"<p class='li'>&#8226; {t}</p>")
        else:
            parts.append(f"<{'p' if kind in ('p', 'small') else kind} class='{kind}'>{t}</{'p' if kind in ('p', 'small') else kind}>")
    css = ("body{font-family:sans-serif;font-size:10pt;} h1{font-size:16pt;color:#0f1d3a;} "
           "h2{font-size:12pt;color:#0f1d3a;margin-top:10pt;} .small{font-size:8pt;color:#555;} .li{margin-left:10pt;}")
    story = pymupdf.Story(html="<body>" + "".join(parts) + "</body>", user_css=css)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    rect = pymupdf.paper_rect("a4")
    where = rect + (50, 50, -50, -50)
    more = True
    while more:
        dev = writer.begin_page(rect)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buf.getvalue()


def to_docx(blocks: list[tuple[str, str]]) -> bytes:
    import docx
    from docx.shared import Pt, RGBColor

    d = docx.Document()
    for kind, text in blocks:
        if kind == "h1":
            d.add_heading(text, level=1)
        elif kind == "h2":
            d.add_heading(text, level=2)
        elif kind == "li":
            d.add_paragraph(text, style="List Bullet")
        elif kind == "small":
            r = d.add_paragraph().add_run(text)
            r.font.size = Pt(8)
            r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
        else:
            d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
