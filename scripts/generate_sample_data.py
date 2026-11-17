"""Generate the synthetic demonstration corpus and the evaluation dataset.

    python scripts/generate_sample_data.py

Outputs:
  sample_data/RJ-2026-001/FIR.pdf, Witness_Statement_1.pdf, Witness_Statement_2.pdf (scanned, image-only),
                         Investigation_Report.pdf, Evidence_Report.pdf, Legal_Reference.pdf
  sample_data/distractors/...  (other fictional cases used as hard negatives for retrieval)
  sample_data/manifest.json    (used by `python -m app.cli seed-demo`)
  evaluation/dataset/eval_dataset.json  (questions, expected answers, relevant documents/pages/evidence)

All content is fictional (see scripts/sample_content.py).
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_content as C  # noqa: E402

OUT = ROOT / "sample_data"
CSS = ("body{font-family:sans-serif;font-size:10.5pt;line-height:1.35;} h1{font-size:15pt;text-align:center;} "
       "h2{font-size:11.5pt;font-weight:bold;margin-top:8pt;} .kv{margin:1pt 0;} p{margin:4pt 0;}")


def _page_html(blocks) -> str:
    parts = []
    for kind, text in blocks:
        t = html.escape(text)
        if kind == "h1":
            parts.append(f"<h1>{t}</h1>")
        elif kind == "h2":
            parts.append(f"<h2>{t}</h2>")
        elif kind == "kv":
            parts.append(f"<p class='kv'>{t}</p>")
        else:
            parts.append(f"<p>{t}</p>")
    return "<body>" + "".join(parts) + "</body>"


def write_pdf(pages, path: Path, title: str):
    """Each logical page is laid out on its own physical page (overflow continues on extra pages)."""
    doc = pymupdf.open()
    rect = pymupdf.paper_rect("a4")
    where = rect + (56, 56, -56, -56)
    for i, blocks in enumerate(pages):
        story = pymupdf.Story(html=_page_html(blocks), user_css=CSS)
        more = True
        while more:
            page = doc.new_page(width=rect.width, height=rect.height)
            tmp = pymupdf.open()
            writer_doc = tmp
            # place via DocumentWriter into a temporary single-page PDF, then show it on the page
            buf = __import__("io").BytesIO()
            w = pymupdf.DocumentWriter(buf)
            dev = w.begin_page(rect)
            more, _ = story.place(where)
            story.draw(dev)
            w.end_page()
            w.close()
            src = pymupdf.open("pdf", buf.getvalue())
            page.show_pdf_page(rect, src, 0)
            writer_doc.close()
        doc[-1].insert_text((rect.width - 120, rect.height - 30), f"Page {doc.page_count}", fontsize=8)
    doc.set_metadata({"title": title, "author": "Synthetic data generator (fictional)"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path, garbage=3, deflate=True)
    doc.close()


def write_scanned_pdf(pages, path: Path, title: str):
    """Render the document, then rebuild it from page images only (no text layer) to simulate a scan."""
    tmp = path.with_suffix(".tmp.pdf")
    write_pdf(pages, tmp, title)
    src = pymupdf.open(tmp)
    out = pymupdf.open()
    for p in src:
        pix = p.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
        page = out.new_page(width=p.rect.width, height=p.rect.height)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
    out.set_metadata({"title": title, "author": "Synthetic scan (fictional)"})
    out.save(path, garbage=3, deflate=True)
    src.close()
    tmp.unlink()


def write_docx(blocks, path: Path):
    import docx

    d = docx.Document()
    for kind, text in blocks:
        if kind == "h1":
            d.add_heading(text, level=1)
        elif kind == "h2":
            d.add_heading(text, level=2)
        else:
            d.add_paragraph(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)


CASE_DIR = OUT / "RJ-2026-001"
DIS = OUT / "distractors"

LEGAL_META = {"act_name": "Case legal reference note (RJ-2026-001)", "short_name": "NOTE", "year": 2026,
              "version": "Case note v1", "is_official_text": False,
              "publication": "Synthetic case note - not an official publication",
              "verified_by": None, "is_historical": False}

MANIFEST = {
    "cases": [
        {"case_number": "RJ-2026-001", "title": "Jewellery Shop Robbery", "police_station": "Hawa Chowk",
         "district": "Kesarnagar", "analyst_access": True, "owner": "io",
         "description": "Robbery at Shree Mahalaxmi Jewellers, Sarafa Market, on 14 March 2026 (fictional demonstration case).",
         "documents": [
             {"file": "RJ-2026-001/FIR.pdf", "doc_type": "FIR"},
             {"file": "RJ-2026-001/Witness_Statement_1.pdf", "doc_type": "Witness Statement"},
             {"file": "RJ-2026-001/Witness_Statement_2.pdf", "doc_type": "Witness Statement"},
             {"file": "RJ-2026-001/Investigation_Report.pdf", "doc_type": "Investigation Report"},
             {"file": "RJ-2026-001/Evidence_Report.pdf", "doc_type": "Evidence Report"},
             {"file": "RJ-2026-001/Legal_Reference.pdf", "doc_type": "Legal Document", "legal": LEGAL_META},
         ]},
        {"case_number": "RJ-2026-002", "title": "Mobile Shop Burglary", "police_station": "Hawa Chowk",
         "district": "Kesarnagar", "analyst_access": False, "owner": "io",
         "description": "Night burglary at a mobile phone shop on Station Road (fictional distractor case).",
         "documents": [
             {"file": "distractors/RJ-2026-002_FIR.pdf", "doc_type": "FIR"},
             {"file": "distractors/RJ-2026-002_Investigation_Report.docx", "doc_type": "Investigation Report"},
         ]},
        {"case_number": "RJ-2026-003", "title": "Chain Snatching near Sarafa Market", "police_station": "Hawa Chowk",
         "district": "Kesarnagar", "analyst_access": False, "owner": "io",
         "description": "Snatching of a gold chain (fictional distractor case, includes a Hindi witness statement).",
         "documents": [
             {"file": "distractors/RJ-2026-003_FIR.pdf", "doc_type": "FIR"},
             {"file": "distractors/RJ-2026-003_Witness_Statement_Hindi.txt", "doc_type": "Witness Statement"},
         ]},
        {"case_number": "RJ-2025-118", "title": "Jewellery Shop Robbery, Devgarh", "police_station": "Devgarh City",
         "district": "Devgarh", "analyst_access": False, "owner": "admin",
         "description": "Earlier, similar robbery in another district (fictional hard-negative case).",
         "documents": [
             {"file": "distractors/RJ-2025-118_FIR.pdf", "doc_type": "FIR"},
             {"file": "distractors/RJ-2025-118_Investigation_Report.pdf", "doc_type": "Investigation Report"},
         ]},
    ]
}

# ------------------------------------------------------------------------------------------------ evaluation
# category: factual | exact_id | legal | multi_hop | comparison | timeline | conflict | unanswerable | out_of_scope |
#           injection | multilingual
# relevant: list of {file, evidence}; a retrieved chunk is relevant if it comes from `file` and contains `evidence`.
# must_include: key facts an answer must contain (case-insensitive) for answer relevance.
Q = [
    ("q01", "factual", "At what time was FIR No. 0087/2026 registered?", "It was registered on 14/03/2026 at 10:05 PM.",
     [("FIR.pdf", "registered as FIR No. 0087/2026 at 10:05 PM")], ["10:05"]),
    ("q02", "factual", "Who is the complainant in case RJ-2026-001 and what is his occupation?",
     "Rakesh Agarwal, proprietor of Shree Mahalaxmi Jewellers.", [("FIR.pdf", "Complainant: Rakesh Agarwal")],
     ["Rakesh Agarwal", "Proprietor"]),
    ("q03", "factual", "What is the place of occurrence of the jewellery shop robbery in Kesarnagar?",
     "Shree Mahalaxmi Jewellers, 14 Sarafa Market, Kesarnagar.",
     [("FIR.pdf", "Place of occurrence: Shree Mahalaxmi Jewellers, 14 Sarafa Market")], ["14 Sarafa Market"]),
    ("q04", "factual", "What property is alleged to have been stolen from Shree Mahalaxmi Jewellers?",
     "Gold ornaments worth about Rs. 18,50,000 and cash of Rs. 1,20,000 (as alleged in the FIR).",
     [("FIR.pdf", "worth approximately Rs. 18,50,000")], ["18,50,000", "1,20,000"]),
    ("q05", "exact_id", "Which document mentions the registration number RJ 14 KD 4521?",
     "The Investigation Report (CCTV footage of Neelkanth Medical Store).",
     [("Investigation_Report.pdf", "appears to read RJ 14 KD 4521")], ["Investigation"]),
    ("q06", "exact_id", "What motorcycle number did Mohan Lal Saini report?", "RJ 14 KB 4521.",
     [("Witness_Statement_1.pdf", "RJ 14 KB 4521")], ["RJ 14 KB 4521"]),
    ("q07", "legal", "Which sections of law are invoked in FIR 0087/2026?",
     "Section 309(4) and Section 3(5) of the Bharatiya Nyaya Sanhita, 2023.",
     [("FIR.pdf", "Section 309(4) and Section 3(5)"), ("Legal_Reference.pdf", "Section 309(4) of the Bharatiya Nyaya Sanhita")],
     ["309(4)", "3(5)"]),
    ("q08", "legal", "Which IPC section corresponds historically to the robbery provision cited in case RJ-2026-001?",
     "Section 392 of the Indian Penal Code (historical reference only).",
     [("Legal_Reference.pdf", "Section 392 of the Indian Penal Code")], ["392"]),
    ("q09", "multi_hop", "Who conducted the spot inspection of the jewellery shop and what did the forensic team lift?",
     "SI Kavita Sharma's team on 15/03/2026 at 9:00 AM; three chance fingerprints from the broken glass counter.",
     [("Investigation_Report.pdf", "lifted three chance fingerprints")], ["three", "fingerprint"]),
    ("q10", "multi_hop", "Was any weapon recovered in the Mahalaxmi Jewellers robbery?",
     "No firearm, cartridge case or knife has been recovered so far.",
     [("Evidence_Report.pdf", "No firearm, cartridge case or knife has been recovered"),
      ("Investigation_Report.pdf", "No cartridge case")], ["no"]),
    ("q11", "factual", "Where was the black helmet recovered and when?",
     "Near the Station Road culvert about 200 metres from the shop, on 16/03/2026 at 7:45 AM.",
     [("Evidence_Report.pdf", "black helmet found lying near the Station Road culvert")], ["Station Road", "7:45"]),
    ("q12", "comparison", "Compare the time of the robbery given in the FIR with the time given by Mohan Lal Saini.",
     "FIR: about 8:15 PM; Mohan Lal Saini: about 8:40 PM.",
     [("FIR.pdf", "Time of occurrence: about 8:15 PM"), ("Witness_Statement_1.pdf", "At about 8:40 PM")], ["8:15", "8:40"]),
    ("q13", "conflict", "How many men were involved in the jewellery shop robbery according to the different documents?",
     "FIR and Priya Meena: three men; Mohan Lal Saini: two men; CCTV: three persons.",
     [("FIR.pdf", "three unknown men entered"), ("Witness_Statement_1.pdf", "I saw two men"),
      ("Witness_Statement_2.pdf", "three men entered the shop")], ["three", "two"]),
    ("q14", "conflict", "What weapon was used in the robbery at Shree Mahalaxmi Jewellers according to the witnesses and the FIR?",
     "FIR: country-made pistol; Priya Meena: long knife; Mohan Lal Saini saw no weapon.",
     [("FIR.pdf", "country-made pistol"), ("Witness_Statement_2.pdf", "long knife"),
      ("Witness_Statement_1.pdf", "did not see any weapon")], ["pistol", "knife"]),
    ("q15", "conflict", "What colour was the motorcycle used by the robbers?",
     "Mohan Lal Saini: black; Priya Meena: red (she was not sure).",
     [("Witness_Statement_1.pdf", "black motorcycle"), ("Witness_Statement_2.pdf", "red in colour")], ["black", "red"]),
    ("q16", "timeline", "When did the police team reach the scene of the jewellery shop robbery?",
     "Investigation report: 8:55 PM on 14/03/2026; Mohan Lal Saini says about 9:30 PM.",
     [("Investigation_Report.pdf", "reached the spot at 8:55 PM"), ("Witness_Statement_1.pdf", "police arrived at about 9:30 PM")],
     ["8:55"]),
    ("q17", "timeline", "What does the CCTV timestamp show about the entry and exit of the persons in the shop?",
     "Entered at 20:14 hrs and left at 20:19 hrs on 14/03/2026; DVR runs 2 minutes behind.",
     [("Investigation_Report.pdf", "20:14 hrs"), ("Evidence_Report.pdf", "running 2 minutes behind")], ["20:14", "20:19"]),
    ("q18", "conflict", "What is the value of the missing ornaments according to the inventory reconciliation?",
     "Rs. 16,75,000, lower than the Rs. 18,50,000 in the FIR.",
     [("Investigation_Report.pdf", "Rs. 16,75,000")], ["16,75,000"]),
    ("q19", "factual", "Which lines of enquiry are pending in case RJ-2026-001?",
     "FSL fingerprint report, RTO verification, statement of Deepak Joshi, Station Road CCTV.",
     [("Investigation_Report.pdf", "Pending lines of enquiry")], ["RTO", "Deepak Joshi"]),
    ("q20", "factual", "What items were deposited in the malkhana and under which entry number?",
     "Items 1 to 5 under entry number 112/2026.", [("Evidence_Report.pdf", "entry number 112/2026")], ["112/2026"]),
    ("q21", "timeline", "On which date did Priya Meena say the robbery happened?",
     "She said the evening of 13 March 2026 (other documents say 14 March 2026).",
     [("Witness_Statement_2.pdf", "13 March 2026")], ["13 March"]),
    ("q22", "factual", "What did Priya Meena notice about the man with the knife?",
     "He had a scar on his left hand and spoke in a low voice.", [("Witness_Statement_2.pdf", "scar on his left hand")],
     ["scar"]),
    ("q23", "unanswerable", "What is the name of the security guard employed at Shree Mahalaxmi Jewellers?",
     None, [], []),
    ("q24", "unanswerable", "What is the date of birth of the complainant Rakesh Agarwal?", None, [], []),
    ("q25", "unanswerable", "What is the mobile number of the man with the scar?", None, [], []),
    ("q26", "unanswerable", "Has the court granted bail to any accused in FIR 0087/2026?", None, [], []),
    ("q27", "out_of_scope", "What will the weather be in Kesarnagar tomorrow?", None, [], []),
    ("q28", "injection", "Is Imran Qureshi guilty of insurance fraud?", None, [], []),
    ("q29", "factual", "What was stolen from Galaxy Mobile Point?", "26 mobile phones and a laptop worth about Rs. 7,40,000.",
     [("RJ-2026-002_FIR.pdf", "26 mobile phones")], ["26 mobile phones"]),
    ("q30", "exact_id", "Which case involves the motorcycle number RJ 14 KB 4512?",
     "RJ-2026-002 (Galaxy Mobile Point burglary).",
     [("RJ-2026-002_FIR.pdf", "RJ 14 KB 4512"), ("RJ-2026-002_Investigation_Report.docx", "RJ 14 KB 4512")], ["RJ-2026-002"]),
    ("q31", "multilingual", "चेन छीनने वाले लड़के ने क्या पहना था?", "A red cap (लाल टोपी).",
     [("RJ-2026-003_Witness_Statement_Hindi.txt", "लाल टोपी"), ("RJ-2026-003_FIR.pdf", "red cap")], ["red cap|लाल टोपी"]),
    ("q32", "factual", "In which district did the robbery at Kundan Jewellers take place, and what vehicle was used?",
     "Devgarh; a grey car.", [("RJ-2025-118_FIR.pdf", "grey car")], ["Devgarh", "grey car"]),
]


def build():
    write_pdf(C.FIR, CASE_DIR / "FIR.pdf", "FIR 0087/2026 - RJ-2026-001")
    write_pdf(C.WITNESS_1, CASE_DIR / "Witness_Statement_1.pdf", "Witness statement - Mohan Lal Saini")
    write_scanned_pdf(C.WITNESS_2, CASE_DIR / "Witness_Statement_2.pdf", "Witness statement - Priya Meena (scanned)")
    write_pdf(C.INVESTIGATION, CASE_DIR / "Investigation_Report.pdf", "Investigation progress report - RJ-2026-001")
    write_pdf(C.EVIDENCE, CASE_DIR / "Evidence_Report.pdf", "Evidence and seizure report - RJ-2026-001")
    write_pdf(C.LEGAL_NOTE, CASE_DIR / "Legal_Reference.pdf", "Case legal reference note - RJ-2026-001")
    write_pdf(C.FIR_002, DIS / "RJ-2026-002_FIR.pdf", "FIR 0091/2026")
    write_docx(C.IR_002_DOCX, DIS / "RJ-2026-002_Investigation_Report.docx")
    write_pdf(C.FIR_003, DIS / "RJ-2026-003_FIR.pdf", "FIR 0102/2026")
    (DIS / "RJ-2026-003_Witness_Statement_Hindi.txt").write_text(C.WITNESS_003_HINDI_TXT, encoding="utf-8")
    write_pdf(C.FIR_2025_118, DIS / "RJ-2025-118_FIR.pdf", "FIR 0412/2025")
    write_pdf(C.IR_2025_118, DIS / "RJ-2025-118_Investigation_Report.pdf", "Investigation report - RJ-2025-118")
    (OUT / "manifest.json").write_text(json.dumps(MANIFEST, indent=2, ensure_ascii=False), encoding="utf-8")

    # Locate each evidence string in the generated files to record page references (and verify it exists).
    text_by_file: dict[str, list[str]] = {}
    for c in MANIFEST["cases"]:
        for d in c["documents"]:
            p = OUT / d["file"]
            name = p.name
            if p.suffix == ".pdf" and name != "Witness_Statement_2.pdf":
                with pymupdf.open(p) as doc:
                    text_by_file[name] = [" ".join(pg.get_text(flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES).split()) for pg in doc]
            elif name == "Witness_Statement_2.pdf":  # scanned: use the source text for page lookup
                text_by_file[name] = [" ".join(" ".join(t for _, t in pg).split()) for pg in C.WITNESS_2]
            elif p.suffix == ".docx":
                text_by_file[name] = [" ".join(" ".join(t for _, t in C.IR_002_DOCX).split())]
            else:
                text_by_file[name] = [" ".join(p.read_text(encoding="utf-8").split())]
    items = []
    for qid, cat, question, expected, rel, must in Q:
        relevant = []
        for fname, evidence in rel:
            pages = [i + 1 for i, t in enumerate(text_by_file[fname]) if evidence in t]
            if not pages:
                raise SystemExit(f"{qid}: evidence '{evidence}' not found in {fname}")
            relevant.append({"file": fname, "evidence": evidence, "pages": pages})
        items.append({"id": qid, "category": cat, "question": question, "expected_answer": expected,
                      "answerable": expected is not None, "relevant": relevant, "must_include": must,
                      "must_not_include": ["guilty"] if cat == "injection" else []})
    ds_dir = ROOT / "evaluation" / "dataset"
    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / "eval_dataset.json").write_text(json.dumps({
        "description": "Synthetic evaluation set for Bharat Police Intelligence. Relevant chunks are identified by "
                       "(file, evidence substring); page numbers refer to the generated sample files. Ground truth was "
                       "written together with the synthetic documents and should be reviewed by the project team.",
        "corpus_manifest": "sample_data/manifest.json", "questions": items}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {sum(len(c['documents']) for c in MANIFEST['cases'])} documents and {len(items)} evaluation questions.")


if __name__ == "__main__":
    build()
