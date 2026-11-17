"""Dense (semantic) retrieval over pgvector using cosine distance (HNSW index)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ingestion.embeddings import Embedder
from app.models import DocumentChunk, User
from app.retrieval.base_query import row_to_candidate, scoped_select
from app.retrieval.types import Candidate, RetrievalFilters


def dense_search(db: Session, user: User, query: str, embedder: Embedder, filters: RetrievalFilters,
                 top_k: int = 20, min_similarity: float = 0.0,
                 query_vector: list[float] | None = None) -> list[Candidate]:
    qvec = query_vector if query_vector is not None else embedder.embed_query(query)
    distance = DocumentChunk.embedding.cosine_distance(qvec)
    stmt = (
        scoped_select(user, filters, distance.label("distance"))
        .where(DocumentChunk.embedding_model == embedder.name, DocumentChunk.embedding.isnot(None))
        .order_by(distance)
        .limit(top_k)
    )
    results = []
    for rank, row in enumerate(db.execute(stmt).all(), start=1):
        sim = 1.0 - float(row.distance)
        if sim < min_similarity:
            continue
        c = row_to_candidate(row)
        c.scores.update(dense_similarity=sim, dense_rank=rank)
        results.append(c)
    return results
