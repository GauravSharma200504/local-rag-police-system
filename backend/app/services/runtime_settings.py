"""Runtime-editable retrieval/generation parameters stored in app_settings (key 'retrieval')."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting


@dataclass
class RetrievalParams:
    retrieval_top_k: int
    rerank_top_k: int
    dense_similarity_threshold: float
    rerank_score_threshold: float
    rrf_k: int
    citation_support_threshold: float
    ollama_model: str
    llm_temperature: float

    @classmethod
    def defaults(cls) -> RetrievalParams:
        s = get_settings()
        return cls(**{f.name: getattr(s, f.name) for f in fields(cls)})

    def to_dict(self) -> dict:
        return asdict(self)


KEY = "retrieval"


def load_params(db: Session) -> RetrievalParams:
    params = RetrievalParams.defaults()
    row = db.get(AppSetting, KEY)
    if row and isinstance(row.value, dict):
        for f in fields(RetrievalParams):
            if f.name in row.value:
                setattr(params, f.name, type(getattr(params, f.name))(row.value[f.name]))
    return params


def save_params(db: Session, updates: dict) -> RetrievalParams:
    params = load_params(db)
    for f in fields(RetrievalParams):
        if f.name in updates and updates[f.name] is not None:
            setattr(params, f.name, type(getattr(params, f.name))(updates[f.name]))
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=params.to_dict()))
    else:
        row.value = params.to_dict()
    db.commit()
    return params
