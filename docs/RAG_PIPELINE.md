# Hybrid RAG pipeline

```mermaid
flowchart TB
  Q[User query] --> N[Query processing<br/>whitespace normalization only - meaning preserved<br/>scope: user permissions + case/document/type filters]
  N --> D[Dense retrieval<br/>e5 'query:' embedding → pgvector cosine, HNSW<br/>top-K=20, similarity ≥ 0.2]
  N --> S[Sparse retrieval<br/>PostgreSQL FTS: per-token plainto_tsquery<br/>'english' stemmed ∪ 'simple' exact - OR-combined<br/>ranked by ts_rank_cd, top-K=20]
  D --> F[Reciprocal Rank Fusion<br/>score = Σ 1/(60 + rank)<br/>+ near-duplicate removal (3-gram Jaccard ≥ 0.9)]
  S --> F
  F --> R[Cross-encoder reranking<br/>mmarco-mMiniLMv2 multilingual<br/>score threshold -2.0, keep top 5]
  R --> C[Context construction<br/>labels S1..Sn, document, type & evidentiary nature, pages, section<br/>fenced in &lt;document&gt; tags as untrusted data, token budget]
  C --> L[Local LLM via Ollama<br/>system rules: cite every sentence, distinguish allegation/statement/<br/>observation/evidence, never infer guilt, reply INSUFFICIENT_EVIDENCE]
  L --> V[Citation validation<br/>label exists? sentence words & numbers supported by chunk?<br/>remove failed citations, flag unsupported sentences,<br/>withhold answer if nothing verifiable]
  V --> A[Answer + citations<br/>document · page · supporting passage · support score]
  A --> P[Open original page<br/>server-rendered PNG with highlight<br/>PDF text search or OCR word boxes]
```

## Experimental configurations

| Config | Stages | Citation validation |
|---|---|---|
| `vector` (Baseline 1) | dense → top 5 | no (citations reported as generated) |
| `hybrid` (Baseline 2) | dense + sparse → RRF → top 5 | no |
| `proposed` | dense + sparse → RRF → cross-encoder (threshold) → top 5 | yes |

All stages are separate modules in `backend/app/retrieval/` (`dense.py`, `sparse.py`, `fusion.py`, `reranker.py`) orchestrated by `pipeline.py`, so they are unit-testable and comparable.

## Design decisions

- **Why hybrid?** Police documents are full of exact identifiers (FIR `0087/2026`, case `RJ-2026-001`, vehicle `RJ 14 KD 4521`, sections `309(4)`) that dense embeddings blur, while paraphrased questions ("what did the robbers flee on?") need semantic matching. RRF combines both without score calibration.
- **Why FTS with two configurations?** `english` stemming helps prose; `simple` keeps Hindi tokens and identifiers intact (no stemmer for Hindi in core PostgreSQL). Tokens are OR-ed so a long question does not require every word.
- **Why a cross-encoder?** It reads query and passage jointly, which fixes RRF's weakness of rewarding chunks that merely share common words. Its score also gives a calibrated-enough threshold for *abstention*: if no chunk passes, the LLM is not called.
- **Why `multilingual-e5-small`?** 384-d, ~120 M parameters, CPU-friendly, trained for Hindi and English retrieval. Larger alternative: `BAAI/bge-m3` (1024-d) via `EMBEDDING_PROVIDER=ollama` or sentence-transformers.
- **Chunking** respects headings and statutory sections (`309.`/`Section 309` boundaries for legal documents); small sections are merged to avoid fragment chunks; every chunk stores `page_spans` (character ranges per page), so a citation passage maps back to the exact page even when a chunk spans two pages.
- **Citation validation** is lexical and conservative: it requires ≥35 % of the sentence's content words in the cited chunk and *all numbers* (dates, times, amounts, IDs) to appear there. This catches the most dangerous hallucinations (wrong times, invented amounts) at very low cost. Limitation: correct paraphrases with few shared words may lose their citation and be flagged "unverified" (shown with a dotted underline), never silently trusted.
- **Prompt-injection defence**: retrieved text is fenced and declared untrusted in the system prompt; instruction-like patterns ("ignore previous instructions…") are detected and surfaced as warnings; even if a model followed an injected instruction, the claim would have no supporting citation and would be removed.
- **No query rewriting** by the LLM: the original question is used for both retrieval paths (meaning cannot drift).

## Tunable parameters

`RETRIEVAL_TOP_K`, `RERANK_TOP_K`, `DENSE_SIMILARITY_THRESHOLD`, `RERANK_SCORE_THRESHOLD`, `RRF_K`, `CITATION_SUPPORT_THRESHOLD`, `OLLAMA_MODEL`, `LLM_TEMPERATURE` - editable at runtime in Settings (stored in `app_settings`), defaults from `.env`. Chunk size/overlap are ingestion-time settings (re-process after changing).
