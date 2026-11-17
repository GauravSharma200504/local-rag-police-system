"""Chronological timeline construction from extracted entities with conflict flagging.

Contradictory dates/times are flagged and every version is shown with its source; nothing is resolved silently.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentType, ExtractedEntity

NATURE = {
    DocumentType.FIR: "allegation",
    DocumentType.WITNESS_STATEMENT: "witness statement",
    DocumentType.INVESTIGATION_REPORT: "investigative observation",
    DocumentType.EVIDENCE_REPORT: "documentary evidence",
    DocumentType.CHARGE_SHEET: "allegation (charge sheet)",
    DocumentType.LEGAL_DOCUMENT: "legal reference",
    DocumentType.OTHER: "document record",
}

EVENT_CATEGORIES = {
    "incident": re.compile(r"\b(robbery|robbed|looted|incident|occurred|occurrence|entered|threatened|snatched|"
                           r"fled|escaped|ran out|came out|come out|attacked|broke into|took place|"
                           r"(two|three|four|unknown) (unknown )?(men|persons))\b", re.I),
    "report_to_police": re.compile(r"\b(lodged|registered|reported to|informed the police|called (the )?(police|112|100)|complaint)\b", re.I),
    "police_arrival": re.compile(r"\b(reached the (spot|scene)|arrived at the (spot|scene|shop)|police (team )?(reached|arrived))\b", re.I),
    "scene_examination": re.compile(r"\b(inspected|examined the scene|site inspection|spot inspection|forensic team)\b", re.I),
    "recovery_seizure": re.compile(r"\b(recovered|seized|seizure)\b", re.I),
}


def categorize(text: str) -> str | None:
    for name, pattern in EVENT_CATEGORIES.items():
        if pattern.search(text):
            return name
    return None


def _nearest_time(context: str, category: str | None, times: list[dict]) -> dict | None:
    """When a sentence holds several times, pick the one closest to the phrase that defines the event."""
    if not times:
        return None
    if len(times) == 1 or not category:
        return times[0]
    m = EVENT_CATEGORIES[category].search(context)
    if not m:
        return times[0]
    anchor = m.start()

    def dist(t):
        i = context.find(t["value"])
        return abs(i - anchor) if i >= 0 else 10**6
    return min(times, key=dist)


def _minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def build_timeline(db: Session, document_ids: list[uuid.UUID]) -> dict:
    if not document_ids:
        return {"events": [], "conflicts": [], "flags": []}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(document_ids)))}
    ents = db.scalars(
        select(ExtractedEntity)
        .where(ExtractedEntity.document_id.in_(document_ids), ExtractedEntity.entity_type.in_(["DATE", "TIME", "PERSON", "LOCATION"]))
        .order_by(ExtractedEntity.document_id, ExtractedEntity.page, ExtractedEntity.span_start)
    ).all()

    by_sentence: dict[tuple, dict] = {}
    for e in ents:
        key = (e.document_id, e.context)
        ev = by_sentence.setdefault(key, {"dates": [], "times": [], "people": [], "locations": [], "page": e.page,
                                          "chunk_id": e.chunk_id})
        bucket = {"DATE": "dates", "TIME": "times", "PERSON": "people", "LOCATION": "locations"}[e.entity_type]
        if e.normalized_value not in [x["normalized"] for x in ev[bucket]]:
            ev[bucket].append({"value": e.value, "normalized": e.normalized_value})

    events, flags = [], []
    for (doc_id, context), ev in by_sentence.items():
        if not ev["dates"] and not ev["times"]:
            continue
        doc = docs[doc_id]
        dates = sorted({d["normalized"] for d in ev["dates"]})
        category = categorize(context)
        t = _nearest_time(context, category, ev["times"])
        base = {
            "description": context, "document_id": str(doc_id), "document_title": doc.title,
            "doc_type": doc.doc_type.value, "page": ev["page"], "chunk_id": str(ev["chunk_id"]) if ev["chunk_id"] else None,
            "nature": NATURE.get(doc.doc_type, "document record"), "category": category,
            "time": t["normalized"] if t else None, "time_text": t["value"] if t else None,
            "people": [p["value"] for p in ev["people"]], "locations": [loc["value"] for loc in ev["locations"]],
            "flags": [],
        }
        if not dates:
            events.append({**base, "date": None, "flags": ["missing_date"]})
        for d in dates:
            events.append({**base, "date": d})

    events.sort(key=lambda e: (e["date"] or "9999-99-99", e["time"] or "99:99", e["document_title"]))

    # Conflict detection: same event category, different dates or times (> 10 min apart) across documents.
    conflicts = []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        if e["category"] in ("incident", "report_to_police", "police_arrival"):
            grouped[e["category"]].append(e)
    for category, evs in grouped.items():
        times = [e for e in evs if e["time"]]
        distinct_times = sorted({e["time"] for e in times})
        if len(distinct_times) > 1 and _minutes(distinct_times[-1]) - _minutes(distinct_times[0]) > 10 \
                and len({e["document_id"] for e in times}) > 1:
            conflicts.append({
                "type": "time", "category": category,
                "message": f"Documents report different times for the {category.replace('_', ' ')}: "
                           + ", ".join(distinct_times) + ". Not resolved automatically - verify against originals.",
                "versions": [{"value": e["time_text"], "normalized": e["time"], "document_title": e["document_title"],
                              "document_id": e["document_id"], "page": e["page"], "nature": e["nature"],
                              "passage": e["description"]} for e in times],
            })
            for e in times:
                e["flags"].append("conflicting_time")
        dated = [e for e in evs if e["date"]]
        distinct_dates = sorted({e["date"] for e in dated})
        if len(distinct_dates) > 1 and category == "incident" and len({e["document_id"] for e in dated}) > 1:
            conflicts.append({
                "type": "date", "category": category,
                "message": f"Documents report different dates for the incident: {', '.join(distinct_dates)}.",
                "versions": [{"value": e["date"], "normalized": e["date"], "document_title": e["document_title"],
                              "document_id": e["document_id"], "page": e["page"], "nature": e["nature"],
                              "passage": e["description"]} for e in dated],
            })
            for e in dated:
                e["flags"].append("conflicting_date")

    # Chronological inconsistency: police report/arrival recorded before the incident on the same day.
    inc = [e for e in events if e["category"] == "incident" and e["date"] and e["time"]]
    for e in events:
        if e["category"] in ("report_to_police", "police_arrival") and e["date"] and e["time"]:
            earlier = [i for i in inc if i["date"] == e["date"] and i["document_id"] == e["document_id"] and i["time"] > e["time"]]
            if earlier:
                e["flags"].append("chronology_inconsistent")
                flags.append(f"In {e['document_title']} (p.{e['page']}), a {e['category'].replace('_', ' ')} at {e['time']} "
                             f"precedes an incident time of {earlier[0]['time']} in the same document.")
    missing = sum(1 for e in events if "missing_date" in e["flags"])
    if missing:
        flags.append(f"{missing} time reference(s) have no explicit date in the same sentence.")
    return {"events": events, "conflicts": conflicts, "flags": flags}
