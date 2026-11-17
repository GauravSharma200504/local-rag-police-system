"""End-to-end API tests against a real PostgreSQL + pgvector database.

Workflow verified: Upload PDF → Extract → OCR (scanned) → Chunk → Embed → Store → Query → Retrieve (dense+sparse)
→ RRF → Rerank → Generate (LLM test double) → Validate citations → Open original page with highlight.
"""
from __future__ import annotations

import json
import re
import time

import pytest

from tests.conftest import SAMPLE, wait_indexed

pytestmark = pytest.mark.usefixtures("db_engine")
API = "/api/v1"
STATE: dict = {}


def first_source_sentence(messages) -> str:
    """Extractive responder: answers with the first substantive sentence of source S1, cited [S1]."""
    content = messages[-1]["content"]
    m = re.search(r"\[S1\][^\n]*\n<document>\n(.*?)\n</document>", content, re.S)
    if not m:
        return "INSUFFICIENT_EVIDENCE"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", m.group(1)) if len(s.split()) >= 6]
    return f"{sentences[0].rstrip('.')} [S1]." if sentences else "INSUFFICIENT_EVIDENCE"


def upload(client, h, path, doc_type, case_id=None, extra=None):
    data = {"doc_type": doc_type, **({"case_id": case_id} if case_id else {}), **(extra or {})}
    with open(path, "rb") as f:
        r = client.post(f"{API}/documents/upload", headers=h, data=data, files={"files": (path.name, f)})
    return r


# ------------------------------------------------------------------ auth
def test_login_rejects_bad_password(client, users):
    r = client.post(f"{API}/auth/login", json={"username": "t_io", "password": "wrong-password"})
    assert r.status_code == 401
    assert client.get(f"{API}/documents").status_code == 401


def test_me(client, headers):
    assert client.get(f"{API}/auth/me", headers=headers["io"]).json()["role"] == "investigator"


# ------------------------------------------------------------------ ingestion
def test_create_case_and_ingest(client, headers):
    r = client.post(f"{API}/cases", headers=headers["io"], json={"case_number": "RJ-2026-001", "title": "Jewellery Shop Robbery",
                                                                  "police_station": "Hawa Chowk", "district": "Kesarnagar"})
    assert r.status_code == 201, r.text
    STATE["case"] = r.json()["id"]
    files = [("FIR.pdf", "FIR"), ("Witness_Statement_1.pdf", "Witness Statement"), ("Witness_Statement_2.pdf", "Witness Statement"),
             ("Investigation_Report.pdf", "Investigation Report"), ("Evidence_Report.pdf", "Evidence Report")]
    ids = {}
    for name, dtype in files:
        r = upload(client, headers["io"], SAMPLE / "RJ-2026-001" / name, dtype, STATE["case"])
        assert r.status_code == 201, r.text
        ids[name] = r.json()["results"][0]["document"]["id"]
    # A second investigator's case that the first investigator must never see
    r = client.post(f"{API}/cases", headers=headers["io2"], json={"case_number": "RJ-2026-002", "title": "Mobile Shop Burglary"})
    STATE["case2"] = r.json()["id"]
    for name, dtype in (("RJ-2026-002_FIR.pdf", "FIR"), ("RJ-2026-002_Investigation_Report.docx", "Investigation Report")):
        r = upload(client, headers["io2"], SAMPLE / "distractors" / name, dtype, STATE["case2"])
        ids[name] = r.json()["results"][0]["document"]["id"]
    for name, doc_id in ids.items():
        owner = headers["io2"] if name.startswith("RJ-2026-002") else headers["io"]
        d = wait_indexed(client, owner, doc_id)
        assert d["status"] == "indexed", (name, d["error_message"])
        assert d["chunk_count"] > 0 and d["page_count"] >= 1
    STATE["ids"] = ids
    w2 = client.get(f"{API}/documents/{ids['Witness_Statement_2.pdf']}", headers=headers["io"]).json()
    assert w2["ocr_pages"] == [1], "scanned witness statement must be OCR'd"


def test_duplicate_upload_detected(client, headers):
    r = upload(client, headers["io"], SAMPLE / "RJ-2026-001" / "FIR.pdf", "FIR", STATE["case"])
    res = r.json()["results"][0]
    assert res["duplicate"] is True and res["document"]["id"] == STATE["ids"]["FIR.pdf"]


def test_upload_validation(client, headers, tmp_path):
    fake = tmp_path / "evil.pdf"
    fake.write_bytes(b"MZ\x90\x00 not a pdf")
    assert upload(client, headers["io"], fake, "FIR").json()["results"][0]["error"]
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    assert "Unsupported" in upload(client, headers["io"], exe, "FIR").json()["results"][0]["error"]
    assert upload(client, headers["analyst"], SAMPLE / "RJ-2026-001" / "FIR.pdf", "FIR").status_code == 403


def test_chunks_and_entities_have_page_provenance(client, headers):
    fir = STATE["ids"]["FIR.pdf"]
    chunks = client.get(f"{API}/documents/{fir}/chunks", headers=headers["io"]).json()
    assert {c["page_start"] for c in chunks} == {1, 2}
    ents = client.get(f"{API}/documents/{fir}/entities", headers=headers["io"]).json()
    pages = {}
    for e in ents:
        pages.setdefault((e["entity_type"], e["normalized_value"]), set()).add(e["page"])
    assert pages[("FIR_NUMBER", "0087/2026")] == {1, 2}  # header on p.1, registration sentence on p.2
    assert pages[("AMOUNT", "rs. 18,50,000")] == {2}
    assert pages[("TIME", "20:15")] == {1}


# ------------------------------------------------------------------ retrieval
@pytest.mark.parametrize("config", ["vector", "hybrid", "proposed"])
def test_retrieval_configs(client, headers, config):
    r = client.post(f"{API}/search", headers=headers["io"], json={"query": "RJ 14 KD 4521 number plate", "config": config})
    assert r.status_code == 200
    res = r.json()
    assert res["results"], config
    assert res["results"][0]["document_id"] == STATE["ids"]["Investigation_Report.pdf"]
    if config != "vector":
        assert res["stage_counts"]["sparse"] > 0 and "rrf" in res["results"][0]["scores"]


def test_sparse_exact_identifier_match(client, headers):
    res = client.post(f"{API}/search", headers=headers["io"], json={"query": "malkhana entry number 112/2026", "config": "hybrid"}).json()
    top = res["results"][0]
    assert top["document_id"] == STATE["ids"]["Evidence_Report.pdf"] and top["scores"].get("sparse_rank") == 1


def test_hindi_document_and_query_are_supported(client, headers, users):
    r = upload(client, headers["io"], SAMPLE / "distractors" / "RJ-2026-003_Witness_Statement_Hindi.txt", "Witness Statement")
    doc_id = r.json()["results"][0]["document"]["id"]
    d = wait_indexed(client, headers["io"], doc_id)
    assert d["language"] in ("hi", "mixed")
    res = client.post(f"{API}/search", headers=headers["io"], json={"query": "लाल टोपी", "config": "hybrid"}).json()
    assert res["results"][0]["document_id"] == doc_id


# ------------------------------------------------------------------ access control
def test_unauthorized_document_access_blocked(client, headers):
    other = STATE["ids"]["RJ-2026-002_FIR.pdf"]
    assert client.get(f"{API}/documents/{other}", headers=headers["io"]).status_code == 404
    assert client.get(f"{API}/documents/{other}/file", headers=headers["io"]).status_code == 404
    assert client.get(f"{API}/documents/{other}/pages/1/image", headers=headers["io"]).status_code == 404
    listing = client.get(f"{API}/documents", headers=headers["io"]).json()
    assert other not in {d["id"] for d in listing["items"]}


def test_unauthorized_chunks_never_retrieved(client, headers):
    for config in ("vector", "hybrid", "proposed"):
        res = client.post(f"{API}/search", headers=headers["io"],
                          json={"query": "Galaxy Mobile Point 26 mobile phones RJ 14 KB 4512", "config": config}).json()
        assert STATE["ids"]["RJ-2026-002_FIR.pdf"] not in {r["document_id"] for r in res["results"]}
        assert STATE["ids"]["RJ-2026-002_Investigation_Report.docx"] not in {r["document_id"] for r in res["results"]}
    # The owner can retrieve it
    res = client.post(f"{API}/search", headers=headers["io2"], json={"query": "Galaxy Mobile Point", "config": "hybrid"}).json()
    assert res["results"][0]["document_id"] == STATE["ids"]["RJ-2026-002_FIR.pdf"]


def test_analyst_access_via_case_membership(client, headers, users):
    fir = STATE["ids"]["FIR.pdf"]
    assert client.get(f"{API}/documents/{fir}", headers=headers["analyst"]).status_code == 404
    assert not client.post(f"{API}/search", headers=headers["analyst"], json={"query": "jewellery robbery"}).json()["results"]
    r = client.post(f"{API}/cases/{STATE['case']}/members", headers=headers["io"], json={"user_id": str(users["analyst"].id)})
    assert r.status_code == 200
    assert client.get(f"{API}/documents/{fir}", headers=headers["analyst"]).status_code == 200
    assert client.delete(f"{API}/documents/{fir}", headers=headers["analyst"]).status_code == 403


# ------------------------------------------------------------------ RAG answer + citations
def _conversation(client, h, case_id=None):
    return client.post(f"{API}/chat/conversations", headers=h, json={"case_id": case_id}).json()["id"]


def test_answer_with_validated_citation_and_source_page(client, headers, fake_llm):
    fake_llm(first_source_sentence)
    cid = _conversation(client, headers["io"], STATE["case"])
    r = client.post(f"{API}/chat/conversations/{cid}/messages", headers=headers["io"],
                    json={"question": "Where was the black helmet recovered?",
                          "document_ids": [STATE["ids"]["Evidence_Report.pdf"]]})
    assert r.status_code == 200, r.text
    msg = r.json()
    assert not msg["abstained"] and msg["citations"]
    c = msg["citations"][0]
    sources = msg["retrieval"]["sources"]
    assert sources[0]["label"] == "S1" and sources[0]["chunk_id"] == c["chunk_id"]
    assert c["passage"].rstrip("…") in sources[0]["text"] or c["passage"][:60] in sources[0]["text"]
    assert sources[0]["page_start"] <= c["page"] <= sources[0]["page_end"]
    assert c["document_id"] == STATE["ids"]["Evidence_Report.pdf"]
    # Open the cited page with the passage highlighted
    img = client.get(f"{API}/documents/{c['document_id']}/pages/{c['page']}/image", headers=headers["io"],
                     params={"passage": c["passage"]})
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert int(img.headers["X-Highlight-Count"]) > 0
    # Conversation history persisted with citations
    conv = client.get(f"{API}/chat/conversations/{cid}", headers=headers["io"]).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["citations"][0]["label"] == c["label"]


def test_ocr_page_highlight(client, headers, fake_llm):
    fake_llm(first_source_sentence)
    w2 = STATE["ids"]["Witness_Statement_2.pdf"]
    img = client.get(f"{API}/documents/{w2}/pages/1/image", headers=headers["io"],
                     params={"passage": "The man with the knife had a scar on his left hand."})
    assert img.status_code == 200 and int(img.headers["X-Highlight-Count"]) > 0


def test_hallucinated_answer_is_withheld(client, headers, fake_llm):
    fake_llm(lambda m: "The accused Vikram Singh was arrested on 21 March 2026 at Jaipur [S1]. He confessed [S9].")
    cid = _conversation(client, headers["io"], STATE["case"])
    msg = client.post(f"{API}/chat/conversations/{cid}/messages", headers=headers["io"],
                      json={"question": "Who was arrested in this case?"}).json()
    assert msg["abstained"] and not msg["citations"]
    assert "Sufficient evidence was not found" in msg["content"]
    assert any("non-existent" in w for w in msg["retrieval"]["warnings"])


def test_model_abstention_is_respected(client, headers, fake_llm):
    fake_llm(lambda m: "INSUFFICIENT_EVIDENCE")
    cid = _conversation(client, headers["io"], STATE["case"])
    msg = client.post(f"{API}/chat/conversations/{cid}/messages", headers=headers["io"],
                      json={"question": "What was the result of the FSL fingerprint comparison?"}).json()
    assert msg["abstained"]


def test_no_retrieval_means_abstention_without_llm(client, headers, fake_llm):
    llm = fake_llm(first_source_sentence)
    client.put(f"{API}/settings/retrieval", headers=headers["admin"], json={"dense_similarity_threshold": 0.99})
    try:
        cid = _conversation(client, headers["io"], STATE["case"])
        msg = client.post(f"{API}/chat/conversations/{cid}/messages", headers=headers["io"],
                          json={"question": "zxqv plorbt", "config": "vector"}).json()
        assert msg["abstained"] and llm.calls == []
    finally:
        client.put(f"{API}/settings/retrieval", headers=headers["admin"], json={"dense_similarity_threshold": 0.2})


def test_prompt_injection_in_document_is_flagged(client, headers, fake_llm):
    fake_llm(first_source_sentence)
    cid = _conversation(client, headers["io2"], STATE["case2"])
    msg = client.post(f"{API}/chat/conversations/{cid}/messages", headers=headers["io2"],
                      json={"question": "What does the FIR of Galaxy Mobile Point say about the AI assistant system note?"}).json()
    assert any("resembling instructions" in w for w in msg["retrieval"]["warnings"])


def test_streaming_endpoint(client, headers, fake_llm):
    fake_llm(first_source_sentence)
    cid = _conversation(client, headers["io"], STATE["case"])
    with client.stream("POST", f"{API}/chat/conversations/{cid}/stream", headers=headers["io"],
                       json={"question": "What items were seized from the jewellery shop?"}) as r:
        body = "".join(r.iter_text())
    events = re.findall(r"event: (\w+)\ndata: (.*)\n\n", body)
    names = [e for e, _ in events]
    assert names[0] == "sources" and "token" in names and names[-1] == "final"
    final = json.loads(events[-1][1])
    assert final["role"] == "assistant" and final["citations"]


# ------------------------------------------------------------------ intelligence
def test_document_comparison(client, headers, fake_llm):
    fake_llm(lambda m: "Both documents mention Shree Mahalaxmi Jewellers [S1][S2].")
    r = client.post(f"{API}/intelligence/compare", headers=headers["io"],
                    json={"document_a": STATE["ids"]["FIR.pdf"], "document_b": STATE["ids"]["Witness_Statement_1.pdf"],
                          "narrative": True})
    assert r.status_code == 200
    s = r.json()["content"]["structured"]
    time_conflicts = [c for c in s["conflicts"] if c["type"] == "TIME"]
    assert time_conflicts, s["conflicts"]
    msg = time_conflicts[0]["message"]
    assert "8:15" in msg and "8:40" in msg
    assert time_conflicts[0]["a"][0]["page"] >= 1 and time_conflicts[0]["b"][0]["passage"]
    assert any(c["label"] == "Case identifiers" for c in s["common"])
    assert r.json()["content"]["narrative"]["available"]
    STATE["comparison_report"] = r.json()["report"]["id"]


def test_case_timeline_flags_conflicts(client, headers):
    t = client.get(f"{API}/cases/{STATE['case']}/timeline", headers=headers["io"]).json()
    assert t["events"] and all(e["page"] >= 1 for e in t["events"])
    kinds = {(c["type"], c["category"]) for c in t["conflicts"]}
    assert ("time", "incident") in kinds
    assert ("date", "incident") in kinds  # Priya Meena says 13 March, others 14 March
    natures = {e["nature"] for e in t["events"]}
    assert {"allegation", "witness statement", "investigative observation"} <= natures


def test_legal_source_upload_and_search(client, headers):
    extra = {"act_name": "Case legal reference note", "short_name": "NOTE", "is_official_text": "false"}
    assert upload(client, headers["io"], SAMPLE / "RJ-2026-001" / "Legal_Reference.pdf", "Legal Document", extra=extra).status_code == 403
    r = upload(client, headers["admin"], SAMPLE / "RJ-2026-001" / "Legal_Reference.pdf", "Legal Document", extra=extra)
    doc_id = r.json()["results"][0]["document"]["id"]
    assert wait_indexed(client, headers["admin"], doc_id)["status"] == "indexed"
    res = client.post(f"{API}/legal/search", headers=headers["analyst"], json={"query": "historical IPC section for robbery"}).json()
    assert res["results"] and res["results"][0]["document_id"] == doc_id
    assert res["results"][0]["legal"]["is_official_text"] is False
    assert "NOT marked as official" in res["results"][0]["text_label"]
    missing = client.post(f"{API}/legal/search", headers=headers["io"], json={"query": "Section 103 BNS"}).json()
    assert "No legal source for 'BNS'" in missing["message"]
    assert all(not r["legal"]["is_official_text"] for r in missing["results"])
    strict = client.post(f"{API}/legal/search", headers=headers["io"], json={"query": "Section 103", "act": "BNS"}).json()
    assert strict["results"] == []


def test_case_summary_report_and_export(client, headers, fake_llm):
    fake_llm(first_source_sentence)
    r = client.post(f"{API}/cases/{STATE['case']}/summary", headers=headers["io"])
    assert r.status_code == 202
    rid = r.json()["id"]
    for _ in range(300):
        rep = client.get(f"{API}/reports/{rid}", headers=headers["io"]).json()
        if rep["status"] != "generating":
            break
        time.sleep(0.2)
    assert rep["status"] == "draft", rep
    content = rep["content"]
    assert "AI-GENERATED DRAFT" in content["disclaimer"]
    assert {s["key"] for s in content["sections"]} == {"overview", "incident_details", "evidence", "investigation_observations"}
    assert len(content["witness_statements"]) == 2 and content["people"] and content["important_dates"]
    assert any("discrepancy" in m.lower() for m in content["missing_information"])
    pdf = client.get(f"{API}/reports/{rid}/export", headers=headers["io"], params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    docx = client.get(f"{API}/reports/{rid}/export", headers=headers["io"], params={"format": "docx"})
    assert docx.status_code == 200 and docx.content.startswith(b"PK")
    assert client.patch(f"{API}/reports/{rid}", headers=headers["io"], json={"status": "human_verified"}).json()["status"] == "human_verified"
    assert client.get(f"{API}/reports/{rid}", headers=headers["io2"]).status_code == 404


def test_dashboard_reflects_database(client, headers):
    d = client.get(f"{API}/dashboard", headers=headers["io"]).json()
    assert d["totals"]["documents"] >= 6 and d["totals"]["chunks"] > 0 and d["totals"]["cases"] == 1
    assert d["status_counts"].get("indexed", 0) >= 6 and d["totals"]["queries"] > 0
    assert client.get(f"{API}/audit-logs", headers=headers["io"]).status_code == 403
    logs = client.get(f"{API}/audit-logs", headers=headers["admin"]).json()
    assert {"document_uploaded", "assistant_query", "login"} <= {l["action"] for l in logs}


def test_reprocess_is_idempotent_and_delete_cascades(client, headers):
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import DocumentChunk, ExtractedEntity

    doc = STATE["ids"]["Evidence_Report.pdf"]
    before = client.get(f"{API}/documents/{doc}", headers=headers["io"]).json()["chunk_count"]
    client.post(f"{API}/documents/{doc}/reprocess", headers=headers["io"])
    after = wait_indexed(client, headers["io"], doc)
    assert after["status"] == "indexed" and after["chunk_count"] == before
    assert client.delete(f"{API}/documents/{doc}", headers=headers["io"]).status_code == 204
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc)) == 0
    assert db.scalar(select(func.count()).select_from(ExtractedEntity).where(ExtractedEntity.document_id == doc)) == 0
    db.close()
    assert client.get(f"{API}/documents/{doc}", headers=headers["io"]).status_code == 404
