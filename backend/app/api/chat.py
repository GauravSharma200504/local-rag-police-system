from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.cases import ensure_case_access
from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.models import Citation, Conversation, Message, QueryLog, User
from app.rag.engine import AnswerResult, answer_stream
from app.retrieval.pipeline import CONFIGS, retrieve
from app.retrieval.types import RetrievalFilters
from app.services.audit import audit
from app.services.runtime_settings import load_params
from app.services.serializers import conversation_out, message_out

router = APIRouter(tags=["chat"])


class ConversationIn(BaseModel):
    title: str | None = None
    case_id: uuid.UUID | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    document_ids: list[uuid.UUID] | None = None
    doc_types: list[str] | None = None
    include_legal: bool = True
    config: str = "proposed"


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    case_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] | None = None
    doc_types: list[str] | None = None
    config: str = "proposed"
    top_k: int | None = None


def _own_conversation(db: Session, user: User, cid: uuid.UUID) -> Conversation:
    conv = db.get(Conversation, cid)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/chat/conversations")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()))
    return [conversation_out(c) for c in rows]


@router.post("/chat/conversations", status_code=201)
def create_conversation(body: ConversationIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_case_access(db, user, body.case_id)
    conv = Conversation(user_id=user.id, case_id=body.case_id, title=body.title or "New conversation")
    db.add(conv)
    db.commit()
    return conversation_out(conv, with_messages=True)


@router.get("/chat/conversations/{cid}")
def get_conversation(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return conversation_out(_own_conversation(db, user, cid), with_messages=True)


@router.delete("/chat/conversations/{cid}", status_code=204)
def delete_conversation(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_own_conversation(db, user, cid))
    db.commit()
    return Response(status_code=204)


def _persist(db: Session, conv: Conversation, user: User, question: str, result: AnswerResult, q_type="chat"):
    msg = Message(conversation_id=conv.id, role="assistant", content=result.answer, abstained=result.abstained,
                  retrieval_meta={"config": result.config, "retrieval": result.retrieval, "sources": result.sources,
                                  "warnings": result.warnings, "unsupported_sentences": result.unsupported_sentences,
                                  "timings_ms": result.timings_ms, "llm_error": result.llm_error})
    db.add(msg)
    db.flush()
    for c in result.citations:
        db.add(Citation(message_id=msg.id, label=c["label"], chunk_id=uuid.UUID(c["chunk_id"]),
                        document_id=uuid.UUID(c["document_id"]), document_title=c["document_title"], page=c["page"],
                        passage=c["passage"], support_score=c["support"] or 0.0, verified=c["support"] is not None))
    if conv.title == "New conversation":
        conv.title = question[:80]
    conv.updated_at = func.now()
    db.add(QueryLog(user_id=user.id, query_type=q_type, retrieval_config=result.config, num_results=len(result.sources),
                    abstained=result.abstained, retrieval_ms=result.timings_ms.get("retrieval_ms", 0),
                    total_ms=result.timings_ms.get("total_ms", 0)))
    audit(db, user, "assistant_query", "conversation", conv.id, config=result.config,
          sources=[s["document_id"] for s in result.sources])
    db.commit()
    db.refresh(msg)
    return msg


def _prepare(db: Session, user: User, conv: Conversation, body: AskIn):
    if body.config not in CONFIGS:
        raise HTTPException(422, f"config must be one of {CONFIGS}")
    history = [{"role": m.role, "content": m.content} for m in conv.messages][-6:]
    db.add(Message(conversation_id=conv.id, role="user", content=body.question))
    db.commit()
    filters = RetrievalFilters(case_id=conv.case_id, document_ids=body.document_ids, doc_types=body.doc_types,
                               exclude_legal=not body.include_legal)
    return history, filters


@router.post("/chat/conversations/{cid}/messages")
def ask(cid: uuid.UUID, body: AskIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = _own_conversation(db, user, cid)
    history, filters = _prepare(db, user, conv, body)
    final = None
    for event, payload in answer_stream(db, user, body.question, load_params(db), history=history, filters=filters,
                                        config=body.config):
        if event == "final":
            final = payload
    msg = _persist(db, conv, user, body.question, final)
    return message_out(msg)


@router.post("/chat/conversations/{cid}/stream")
def ask_stream(cid: uuid.UUID, body: AskIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Server-Sent Events: `sources`, many `token`, then `final` (validated answer with citations)."""
    conv = _own_conversation(db, user, cid)
    history, filters = _prepare(db, user, conv, body)
    user_id, conv_id = user.id, conv.id

    def gen():
        s = SessionLocal()
        try:
            u, c = s.get(User, user_id), s.get(Conversation, conv_id)
            for event, payload in answer_stream(s, u, body.question, load_params(s), history=history, filters=filters,
                                                config=body.config):
                if event == "token":
                    yield f"event: token\ndata: {json.dumps(payload)}\n\n"
                elif event == "sources":
                    yield f"event: sources\ndata: {json.dumps(payload)}\n\n"
                else:
                    msg = _persist(s, c, u, body.question, payload)
                    yield f"event: final\ndata: {json.dumps(message_out(msg))}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"
        finally:
            s.close()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/search")
def search(body: SearchIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Retrieval only (no LLM). Exposes per-stage scores for transparency and debugging."""
    if body.config not in CONFIGS:
        raise HTTPException(422, f"config must be one of {CONFIGS}")
    ensure_case_access(db, user, body.case_id)
    t = time.perf_counter()
    params = load_params(db)
    rr = retrieve(db, user, body.query, params, RetrievalFilters(case_id=body.case_id, document_ids=body.document_ids,
                                                                  doc_types=body.doc_types), body.config,
                  final_k=body.top_k or params.rerank_top_k)
    ms = (time.perf_counter() - t) * 1000
    db.add(QueryLog(user_id=user.id, query_type="search", retrieval_config=body.config, num_results=len(rr.candidates),
                    abstained=not rr.candidates, retrieval_ms=ms, total_ms=ms))
    db.commit()
    return {"config": rr.config, "results": [c.to_dict() for c in rr.candidates], "timings_ms": rr.timings_ms,
            "stage_counts": rr.stage_counts}
