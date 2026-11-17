# Architecture

## Overview

BPI is a modular monolith: one FastAPI process (plus two in-process worker threads) and one PostgreSQL database. All AI components run locally. There are no microservices and no cloud dependencies.

```mermaid
flowchart TB
  subgraph Browser
    FE[React SPA<br/>pages · components · services]
  end
  subgraph Backend[FastAPI backend - app/]
    API[api/ routers<br/>auth · documents · cases · chat · intelligence · system]
    CORE[core/<br/>config · database · security · deps]
    SVC[services/<br/>access control · audit · storage · viewer · jobs · settings]
    ING[ingestion/<br/>extractors · ocr · cleaner · chunker · embeddings · pipeline · worker]
    RET[retrieval/<br/>dense · sparse · fusion · reranker · pipeline]
    RAG[rag/<br/>prompts · llm · citations · engine]
    INT[intelligence/<br/>entities · timeline · comparison · summary · legal · export]
  end
  subgraph Local AI
    OLL[Ollama LLM]
    ST[Sentence-Transformers<br/>embeddings + cross-encoder]
    TES[Tesseract OCR]
  end
  DB[(PostgreSQL 16<br/>pgvector HNSW + GIN FTS)]
  FS[(data/uploads<br/>data/processed)]
  FE -- "REST + SSE /api/v1 (Vite proxy)" --> API
  API --> SVC & ING & RET & RAG & INT
  ING --> TES & ST & DB & FS
  RET --> ST & DB
  RAG --> OLL
  INT --> RAG & DB
```

## Layers

| Layer | Responsibility | Never does |
|---|---|---|
| `api/` | HTTP, validation (Pydantic), auth dependencies, response shaping via `services/serializers.py` | business logic, returning ORM objects |
| `services/` | access control, audit, storage, page rendering, background jobs, runtime settings | HTTP concerns |
| `ingestion/` | turn a file into cleaned, chunked, embedded, indexed rows | access control (it processes a known document) |
| `retrieval/` | permission-scoped candidate generation and ranking | generation |
| `rag/` | prompting, local LLM calls, citation validation | retrieval SQL |
| `intelligence/` | entities, timeline, comparison, summaries, legal search, exports | — |

Models are behind small interfaces (`Embedder`, `Reranker`, `OllamaClient`) so they can be swapped by configuration without code changes.

## Document ingestion

```mermaid
flowchart LR
  U[Upload] --> V{validate<br/>ext · magic bytes · size}
  V -- reject --> X[error to user]
  V --> H[SHA-256<br/>duplicate?]
  H -- duplicate --> D[return existing document]
  H --> S[store original<br/>uploads/ab/sha.ext]
  S --> Q[queue: single worker thread]
  Q --> E[extract text per page<br/>PyMuPDF · python-docx · txt]
  E --> O{page text < 40 chars?}
  O -- yes --> OCR[render 300 dpi →<br/>Tesseract eng+hin<br/>+ word boxes saved]
  O -- no --> C
  OCR --> C[clean: ligatures, hyphenation,<br/>whitespace, keep fields/lists]
  C --> K[chunk ≈700 tokens / 120 overlap<br/>heading- & section-aware,<br/>page_spans recorded]
  K --> M[embed in batches]
  M --> T[(transaction: replace chunks<br/>+ tsvector + entities)]
  T --> I[status = indexed]
```

States: `uploaded → extracting → ocr → chunking → embedding → indexed | failed`. Each transition is committed, so the UI shows live progress. Re-processing deletes and re-creates a document's chunks and entities inside one transaction (idempotent). On restart, documents left mid-pipeline are marked failed with a "Reprocess" hint.

## Request flow for a question

```mermaid
sequenceDiagram
  participant UI
  participant API as /chat/.../stream
  participant R as retrieval.pipeline
  participant DB as PostgreSQL
  participant X as Cross-encoder
  participant L as Ollama
  participant V as citations.validate
  UI->>API: question (+case scope, config)
  API->>R: retrieve(user, query, filters)
  R->>DB: dense: ORDER BY embedding <=> q (access filter in WHERE)
  R->>DB: sparse: tsv @@ tsquery ORDER BY ts_rank_cd (access filter in WHERE)
  R->>R: RRF fusion + dedup
  R->>X: rerank top-K, threshold
  API-->>UI: event: sources
  API->>L: system prompt + fenced sources + history
  L-->>API: tokens
  API-->>UI: event: token (streamed)
  API->>V: validate [S#] against chunks
  API->>DB: persist message, citations, query log, audit
  API-->>UI: event: final (validated answer + citations)
```

## Access control model

- Roles: **admin** (everything), **investigator** (upload/edit documents they own or in cases they belong to), **analyst** (read & query only in cases they belong to).
- Document visibility = uploaded by the user ∪ documents of cases the user is a member of ∪ legal reference documents. Admins see all.
- The visibility predicate (`services/access.py`) is added to every document query **and to both retrieval SQL statements**, so chunks the user may not read are never scored, fused, reranked or shown to the LLM.
- Forbidden and non-existent documents both return 404 (existence is not leaked).

## Deployment

- `docker-compose.yml`: `db` (pgvector/pgvector:pg16, volume `pgdata`), `backend` (Python 3.11 + Tesseract eng/hin + CPU PyTorch; volumes for uploads and model cache), optional `ollama` and `frontend` profiles.
- Native development: backend `uvicorn` on :8000, Vite on :5173 with a proxy for `/api`.
- The app runs offline once Python/Node dependencies, the Hugging Face models and the Ollama model are present.

## Security notes

See README → Security considerations. Threats considered: unauthorized cross-case access (SQL-level filter + tests), path traversal (content-addressed storage, filename sanitization), malicious uploads (extension + magic bytes + size), XSS (React escaping, no `dangerouslySetInnerHTML`), SQL injection (SQLAlchemy parameters; FTS built from `plainto_tsquery` per token), prompt injection in documents (fenced untrusted context, instruction-pattern warnings, answers withheld if unverifiable), credential attacks (Argon2id, login throttle), sensitive logging (audit stores identifiers only).
