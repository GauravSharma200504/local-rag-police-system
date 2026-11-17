# Project status

_Last updated: 18 Nov 2026 (initial implementation)._

## Completed and verified (in the build environment)

| Area | Verification |
|---|---|
| FastAPI backend, SQLAlchemy models, Alembic migration (pgvector + generated tsvector + HNSW/GIN indexes) | migration applied on PostgreSQL with pgvector 0.8.7 |
| Auth (Argon2id + JWT), roles, case-membership access control enforced in retrieval SQL | integration tests (unauthorized document/file/page/chunk access blocked for all 3 configs) |
| Upload validation, SHA-256 duplicates, content-addressed storage | tests |
| Extraction: PDF (PyMuPDF, ligature-safe), DOCX (headings, tables, page breaks), TXT (UTF-8/Hindi) | unit tests on sample files |
| OCR: Tesseract eng+hin for scanned pages, word boxes stored for highlighting | unit + integration test on the scanned witness statement |
| Cleaning, structure-aware chunking (size, overlap, page spans, legal sections) | unit tests |
| Embeddings: sentence-transformers / Ollama / hashing (test) providers | hashing tested; real models **not** tested here (see below) |
| Dense (pgvector), sparse (FTS), RRF, dedup, reranker interface, 3 retrieval configs | unit + integration tests |
| RAG engine, SSE streaming, citation validation, abstention, prompt-injection flagging | integration tests with an LLM test double |
| Page rendering with highlighted passage (PDF text + OCR boxes) | integration tests (`X-Highlight-Count > 0`) |
| Entities, timeline with conflict flags, document comparison, case summary job, legal search with provenance, PDF/DOCX export | integration tests |
| Dashboard, audit log, settings, evaluation endpoints | integration tests / live smoke test |
| Synthetic corpus (12 docs, 4 cases) + 32-question labelled dataset | generator validates every label |
| Evaluation script (3 configs, retrieval + generation metrics, CSV/JSON/PNG) | executed end-to-end with the test embedder (results discarded) |
| React frontend: 8 modules + login, citation chips, evidence panel, document viewer | `tsc` clean, `vite build` OK, 5 Vitest tests, API smoke test through the Vite proxy |
| Docker Compose, start scripts, README and docs | compose file validated as YAML |

Test totals at hand-over: **backend 49 passed**, **frontend 5 passed**.

## Not verified in the build environment (must be done on the target machine)

The build sandbox had no access to Hugging Face, Ollama or Docker, so these were implemented but **not executed** there:

1. Loading `intfloat/multilingual-e5-small` and the cross-encoder (`python -m app.cli download-models`, then Settings → "Load & test").
2. Real generation with Ollama (`ollama pull llama3.2:3b`, Settings → "Test inference").
3. `docker compose up --build` (backend image build, Tesseract `hin` package in the image).
4. The experimental evaluation with real models → produces the result tables/charts for the report.
5. Windows `start.ps1` end-to-end.
6. Visual review of the UI in a browser.

## Known issues / limitations

- Citation validation is lexical; correct paraphrases may be marked "unverified".
- Rule-based entities: person/location recall on free text is limited (structured fields work well).
- The bundled `Legal_Reference.pdf` is a case note, not statutory text. Upload official BNS/BNSS/BSA/Constitution PDFs for real legal research.
- Frontend bundle is ~880 KB (no code-splitting yet).
- Login throttling is in-memory (resets on restart).

## Next steps (in order)

1. On your machine: `docker compose up -d db` → backend setup → `download-models` → `ollama pull llama3.2:3b` → `generate_sample_data.py` → `seed-demo` → run the demo walkthrough in README.
2. Run `pytest` and `npm test` locally (see README → Tests).
3. Run `python evaluation/scripts/run_evaluation.py` (3× for latency), review the ground truth in `eval_dataset.json`, and put the measured tables/charts into the project report.
4. Upload official legal texts (with version and source URL) and add legal questions to the evaluation set.
5. Optional improvements: NLI-based citation verification with a small local model, LLM-assisted entity extraction verified against spans, code-splitting the frontend, refresh-token rotation.

## Continuation instructions

All code is in this folder. The backend entry point is `backend/app/main.py`; tests are in `backend/tests/` and `frontend/src/__tests__/`. To continue development, read `docs/ARCHITECTURE.md` first; every module has a docstring explaining its role.
