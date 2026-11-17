# Bharat Police Intelligence (BPI)

**Local AI-powered police document intelligence & legal assistance system** - a final-year B.Tech academic project.

BPI lets authorized users search, understand, summarize and compare Indian police investigation documents (FIRs, witness statements, investigation/evidence reports) and legal references, using a **hybrid RAG pipeline that runs entirely on local models**. Every answer is grounded in retrieved evidence with **validated page-level citations** that open the original page with the passage highlighted.

> **Decision-support only.** BPI never determines guilt or innocence, never recommends coercive action, and marks every AI output as a draft that requires human verification. All sample data is synthetic and fictional.

## Contributions

1. **Hybrid retrieval** - dense (pgvector, multilingual embeddings) + sparse (PostgreSQL full-text) fused with **Reciprocal Rank Fusion**.
2. **Cross-encoder reranking** of the fused candidates with a configurable score threshold.
3. **Evidence-grounded generation with citation validation** - every `[S#]` citation is checked against the actual retrieved chunk (label must exist; the sentence's words *and numbers* must be supported). Unsupported citations are removed, and an answer with no verifiable statement is withheld ("insufficient evidence").
4. **Experimental comparison** of Vector-only RAG vs Hybrid RAG vs the Proposed pipeline on a synthetic, labelled dataset (Recall@5, Precision@5, MRR, nDCG@5, faithfulness, answer relevance, citation accuracy, abstention accuracy, latency).

## Features

| Module | What it does |
|---|---|
| Dashboard | Live DB statistics: documents, chunks, cases, queries, status & type distribution, recent uploads/AI activity, local model health |
| Documents | Multi-file drag-and-drop upload (PDF, DOCX, TXT, PNG/JPG), SHA-256 duplicate detection, metadata editing, preview, extracted text & chunks, reprocess, delete (cascades to chunks/embeddings/entities/files) |
| Ingestion | PyMuPDF / python-docx extraction → Tesseract OCR (eng+hin) for scanned pages → cleaning → structure-aware chunking (700/120 tokens, configurable) → local embeddings → pgvector + FTS index → rule-based entity extraction. Idempotent, with per-stage status |
| AI Assistant | Multi-turn chat with streaming, conversation history, case scoping, retrieval-config selector, evidence panel (citations + all retrieved chunks with dense/sparse/RRF/rerank scores), copy answer/citations, click-to-open source page |
| Case Intelligence | Case workspaces with members (access control), explicit document association, timeline with conflict flags, entity table, case-scoped assistant, AI case summary |
| Document Comparison | Common facts, differing facts, potentially conflicting dates/times/vehicles, missing information - each with passages from both documents; optional AI narrative with validated citations |
| Legal Research | Search uploaded, versioned legal sources (exact section lookup + hybrid search), provenance (act, version, effective date, source URL, verification), "official text" vs "not official" labelling, separate AI explanation |
| Reports | Case summaries & comparisons as drafts → mark human-verified → export PDF/DOCX; experimental evaluation runner with tables & charts |
| Settings | Ollama/embedding/reranker/OCR status and test buttons, runtime retrieval parameters, user management, audit log |

## Architecture

```mermaid
flowchart LR
  UI[React + TypeScript + Tailwind<br/>localhost:5173] -- REST / SSE --> API[FastAPI<br/>localhost:8000]
  API --> AUTH[Auth & RBAC<br/>JWT, Argon2id]
  API --> ING[Ingestion pipeline]
  API --> RET[Retrieval engine]
  API --> RAG[RAG orchestrator +<br/>citation validator]
  API --> INT[Intelligence:<br/>entities, timeline,<br/>comparison, summary, legal]
  ING --> OCR[Tesseract OCR]
  ING --> EMB[Sentence-Transformers<br/>multilingual-e5-small]
  RET --> EMB
  RET --> RR[Cross-encoder reranker]
  RAG --> OLL[Ollama local LLM]
  ING & RET & RAG & INT --> PG[(PostgreSQL 16<br/>pgvector + FTS)]
  ING --> FS[(Local file storage)]
```

More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/RAG_PIPELINE.md](docs/RAG_PIPELINE.md) · [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) · [docs/EVALUATION.md](docs/EVALUATION.md) · [PROJECT_STATUS.md](PROJECT_STATUS.md)

## Technology stack

Frontend: React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui-style components (Radix primitives), Lucide, Axios, Recharts.
Backend: Python 3.11+, FastAPI, Pydantic, SQLAlchemy 2, Alembic. Database: PostgreSQL 16 + pgvector (HNSW) + full-text search.
AI: Ollama (default `llama3.2:3b`), Sentence-Transformers (`intfloat/multilingual-e5-small`, 384-d, Hindi+English), cross-encoder (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, multilingual). Documents: PyMuPDF, python-docx, Tesseract.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | `py -3.11` on Windows |
| Node.js | 18+ (20 LTS recommended) | |
| Docker Desktop | recent | for PostgreSQL + pgvector |
| Ollama | recent | https://ollama.com - native install recommended |
| Tesseract OCR | 5.x | Windows: UB Mannheim installer; tick **Hindi** in "Additional language data" |
| RAM / disk | 8 GB RAM minimum (16 GB comfortable); ~6 GB disk for models + dependencies | |

## Installation (Windows, PowerShell)

```powershell
# 0. In the project folder
copy .env.example .env          # then edit SECRET_KEY (and TESSERACT_CMD if tesseract is not on PATH)

# 1. Database (PostgreSQL 16 + pgvector) - data persists in the 'pgdata' Docker volume
docker compose up -d db

# 2. Backend
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-ml.txt
alembic upgrade head

# 3. Models (one-time download, then everything works offline)
python -m app.cli download-models          # embedding + reranker (~1 GB, asks for confirmation)
ollama pull llama3.2:3b                    # ~2 GB. Low RAM? try qwen2.5:3b or gemma2:2b

# 4. Demo data (fictional case RJ-2026-001 + distractor cases) and demo users
python ..\scripts\generate_sample_data.py
python -m app.cli seed-demo                # prints generated passwords for admin / io.sharma / analyst.verma

# 5. Run the API
uvicorn app.main:app --port 8000

# 6. Frontend (new terminal)
cd frontend
npm install
npm run dev                                # http://localhost:5173
```

Or run everything with `powershell -ExecutionPolicy Bypass -File .\start.ps1 -Seed` (first run) and `.\start.ps1` afterwards. Linux/macOS: `./start.sh --seed`.

To create your own admin instead of demo users: `python -m app.cli create-admin --username admin`.

### Docker Compose (database + backend)

```bash
cp .env.example .env
docker compose up -d --build db backend         # backend runs migrations on start
docker compose exec backend python -m app.cli download-models --yes
docker compose exec backend python /app/scripts/generate_sample_data.py
docker compose exec backend python -m app.cli seed-demo
# Ollama on the host (default) is reached via host.docker.internal; or: docker compose --profile ollama up -d ollama
# Frontend: npm run dev in ./frontend, or: docker compose --profile frontend up -d frontend
```

Volumes `pgdata`, `appdata` (uploaded files), `hfmodels` (model cache) and `ollama` persist across restarts.

### Offline operation

After models are downloaded once, set `HF_HUB_OFFLINE=1` in `.env`. No component calls an external API: embeddings, reranking, OCR and generation are local, and there is no cloud fallback.

## Environment variables

See [.env.example](.env.example) - every variable is documented there. Key ones: `DATABASE_URL`, `SECRET_KEY`, `EMBEDDING_PROVIDER/MODEL/DIM`, `RERANKER_PROVIDER/MODEL`, `OLLAMA_BASE_URL/MODEL`, `CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `TESSERACT_CMD`, `OCR_LANGUAGES`. Retrieval thresholds and the Ollama model can also be changed at runtime in **Settings**.

Changing the embedding model/dimension requires re-indexing: set `EMBEDDING_DIM` and run `python -m app.cli reindex --recreate`.

## Demo walkthrough (for the project viva)

1. Log in as `io.sharma` → **Dashboard** shows 12 indexed documents across 4 fictional cases.
2. **Documents** → open *Witness Statement 2* → it was a scanned PDF; see "OCR pages: 1" and the extracted text.
3. **AI Assistant** → scope *RJ-2026-001* → ask "*Find differences in incident times across documents*". Click a citation chip → the original PDF page opens with the passage highlighted.
4. Ask "*Who has been arrested in this case?*" → it answers from the investigation report that no person has been arrested so far (with citation). Ask "*What is the name of the shop's security guard?*" → no document contains this, so the assistant states that sufficient evidence was not found instead of inventing a name.
5. **Case Intelligence → RJ-2026-001 → Timeline** → three flagged discrepancies (incident time 8:15 vs 8:40 PM, incident date 13 vs 14 March, police arrival 8:55 vs 9:30 PM).
6. **Document Comparison** → FIR vs Witness Statement 1 → conflicting times, the vehicle number found only in B, missing information.
7. **Case → Generate case summary** → **Reports** → export PDF/DOCX → mark human-verified.
8. Log in as `analyst.verma` → only RJ-2026-001 is visible; documents of other cases are never retrieved.
9. **Reports → Experimental evaluation** → run all three configurations → measured tables and charts.

## API

Interactive OpenAPI docs: http://localhost:8000/docs. All routes are under `/api/v1`:

`POST /auth/login`, `GET /auth/me`, `GET|POST /users`, `PATCH /users/{id}` ·
`POST /documents/upload`, `GET /documents`, `GET|PATCH|DELETE /documents/{id}`, `POST /documents/{id}/reprocess`, `GET /documents/{id}/file`, `/chunks`, `/entities`, `/pages/{n}/image?passage=`, `/pages/{n}/text` ·
`POST|GET /cases`, `GET|PATCH|DELETE /cases/{id}`, `POST /cases/{id}/members`, `POST /cases/{id}/documents`, `GET /cases/{id}/timeline`, `GET /cases/{id}/entities`, `POST /cases/{id}/summary` ·
`GET|POST /chat/conversations`, `GET|DELETE /chat/conversations/{id}`, `POST /chat/conversations/{id}/messages`, `POST /chat/conversations/{id}/stream` (SSE), `POST /search` ·
`POST /intelligence/compare`, `POST /intelligence/timeline`, `PATCH /entities/{id}` · `POST /legal/search`, `GET /legal/sources`, `PATCH /legal/sources/{id}` ·
`GET /reports`, `GET|PATCH|DELETE /reports/{id}`, `GET /reports/{id}/export?format=pdf|docx` ·
`GET /dashboard`, `GET /settings/models`, `POST /settings/models/test/{llm|embedding|reranker}`, `GET|PUT /settings/retrieval`, `GET /audit-logs`, `GET /evaluation/results`, `POST /evaluation/run`.

## Tests

```bash
# Backend (needs PostgreSQL+pgvector; uses a separate database and the offline test embedder + an LLM test double)
docker compose exec db createdb -U bpi bpi_test
cd backend && TEST_DATABASE_URL=postgresql+psycopg://bpi:bpi_password@localhost:5432/bpi_test pytest -q
# Windows PowerShell:  $env:TEST_DATABASE_URL="postgresql+psycopg://bpi:bpi_password@localhost:5432/bpi_test"; pytest -q

# Frontend
cd frontend && npm test
```

Backend tests cover PDF/DOCX/TXT extraction, OCR, cleaning, chunking (size, overlap, page spans, legal sections), embeddings, entity extraction, RRF, deduplication, reranking, citation validation, prompt-injection flagging and the complete API workflow: upload → extract → OCR → chunk → embed → store → retrieve (vector/hybrid/proposed) → answer → validate citations → open the original page with highlight, plus unauthorized-access blocking, hallucination withholding, abstention, streaming, comparison, timeline conflicts, legal search, summaries/exports, idempotent reprocessing and cascading delete.

## Evaluation

```bash
python evaluation/scripts/run_evaluation.py                       # all 3 configs, retrieval + generation
python evaluation/scripts/run_evaluation.py --configs vector hybrid --no-generation
```
Results (JSON, CSV, PNG charts) are written to `evaluation/results/`. See [docs/EVALUATION.md](docs/EVALUATION.md). **No results are included - run it on your machine with the real models.**

## Security considerations

Argon2id password hashing; short-lived JWT; role-based access (admin / investigator / analyst); case-membership-based **document-level access enforced inside SQL before retrieval** (unauthorized chunks never reach ranking or the LLM; responses do not reveal whether a forbidden document exists); content-addressed storage (no user-controlled paths); MIME/magic-byte validation and size limits; parameterized SQL via SQLAlchemy; React escaping (no raw HTML rendering); restrictive CORS; security headers; audit log of logins, uploads, views, queries, exports and admin actions (no document text logged); retrieved text is fenced as untrusted data and instruction-like text is flagged (prompt-injection defence); simple login throttling. Local hosting does not automatically make a deployment secure - use TLS (reverse proxy), disk encryption, OS hardening, backups, and change all demo credentials and `SECRET_KEY`.

## Known limitations

- Retrieval metrics depend on models: the evaluation must be run with the real embedding/reranker/LLM on your hardware.
- Lexical citation validation (word + number overlap) is a proxy for entailment; paraphrased but correct sentences can be flagged as unverified.
- Entity extraction is rule-based (high precision on structured fields, lower recall on free-text names/places); review/verify in the UI.
- DOCX has no fixed pagination; page numbers follow explicit page breaks.
- Cross-encoder input is truncated to 512 tokens per chunk.
- The legal module only knows what an administrator uploads. The sample `Legal_Reference.pdf` is a case note that cites sections; it is **not** statutory text. Upload the official BNS/BNSS/BSA/Constitution PDFs (India Code / Gazette) for real legal search.
- Small LLMs (3B) can be slow on CPU (tens of seconds per answer) and sometimes produce citations that get removed by validation.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Ollama is not reachable` | Start Ollama (`ollama serve` or the tray app); check `OLLAMA_BASE_URL` |
| `Model 'x' is not installed` | `ollama pull x` or pick an installed model in Settings |
| Out of memory with the LLM | Use `qwen2.5:3b`, `gemma2:2b` or `phi3:mini`; reduce `LLM_NUM_CTX` to 4096 |
| `Could not load embedding model` | Run `python -m app.cli download-models` once with internet |
| Scanned PDF fails "OCR unavailable" | Install Tesseract (with Hindi data) and set `TESSERACT_CMD` |
| `type "vector" does not exist` | Use the `pgvector/pgvector:pg16` image (docker compose) |
| Dimension mismatch after model change | Set `EMBEDDING_DIM` and run `python -m app.cli reindex --recreate` |
| Documents stuck after restart | They are marked failed on startup - click **Reprocess** |
