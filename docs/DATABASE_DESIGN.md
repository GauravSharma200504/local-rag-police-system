# Database design

PostgreSQL 16 with the `vector` extension. All primary keys are UUIDs; timestamps are `timestamptz`. Schema is created by Alembic (`backend/migrations/versions/0001_initial_schema.py`).

```mermaid
erDiagram
  users ||--o{ case_members : "member of"
  cases ||--o{ case_members : has
  users ||--o{ cases : creates
  cases ||--o{ documents : contains
  users ||--o{ documents : uploads
  documents ||--o{ document_chunks : "split into"
  documents ||--o| legal_documents : "provenance (legal)"
  documents ||--o{ extracted_entities : mentions
  document_chunks ||--o{ extracted_entities : "span in"
  users ||--o{ conversations : owns
  cases ||--o{ conversations : scopes
  conversations ||--o{ messages : contains
  messages ||--o{ citations : cites
  document_chunks ||--o{ citations : "supports"
  cases ||--o{ reports : "summaries"
  users ||--o{ audit_logs : performs
  users ||--o{ query_logs : issues

  documents {
    uuid id PK
    string title
    string sha256 UK "duplicate detection"
    string doc_type "FIR, Witness Statement, ..."
    uuid case_id FK
    uuid uploaded_by FK
    date incident_date
    string police_station
    string district
    string language
    int page_count
    jsonb ocr_pages
    string status "uploaded..indexed|failed"
    float processing_seconds
    string embedding_model
    jsonb metadata
  }
  document_chunks {
    uuid id PK
    uuid document_id FK
    int chunk_index
    text text
    int page_start
    int page_end
    jsonb page_spans "char ranges per page"
    string heading
    string section_number
    int token_count
    vector embedding "pgvector(EMBEDDING_DIM)"
    string embedding_model
    tsvector tsv "GENERATED english || simple"
  }
  legal_documents {
    uuid document_id FK
    string act_name
    string short_name "BNS, BNSS, BSA, IPC..."
    string version
    date effective_date
    string source_url
    bool is_official_text
    string verified_by
    date verification_date
    bool is_historical
    string replaced_by
  }
  extracted_entities {
    uuid id PK
    uuid document_id FK
    uuid chunk_id FK
    string entity_type
    string value
    string normalized_value
    int page
    int span_start
    int span_end
    text context
    string method
    float confidence
    string verification_status
  }
  citations {
    uuid id PK
    uuid message_id FK
    string label "S1.."
    uuid chunk_id FK
    uuid document_id FK
    int page
    text passage
    float support_score
  }
```

Other tables: `users` (username unique, Argon2id hash, role), `cases` (case_number unique), `case_members` (unique case+user), `conversations`, `messages` (content, abstained flag, retrieval metadata JSONB: config, sources with scores, warnings, timings), `reports` (type, JSONB content, status draft/human_verified), `query_logs` (latency and abstention for analytics), `audit_logs` (action, target, JSON detail - no document text), `app_settings` (runtime retrieval parameters).

## Indexes

| Index | Purpose |
|---|---|
| `ix_chunks_embedding_hnsw` - HNSW `vector_cosine_ops` on `document_chunks.embedding` | dense retrieval |
| `ix_chunks_tsv` - GIN on generated `tsv` | sparse retrieval |
| `documents.sha256` unique | idempotent upload / duplicates |
| `documents(case_id)`, `(doc_type)`, `(status)`, `(uploaded_by)` | access filter & listing |
| `document_chunks(document_id)`, `(embedding_model)`, `(section_number)` | scoping, model consistency, legal section lookup |
| `extracted_entities(document_id, entity_type)`, `(normalized_value)` | timeline, comparison |
| `audit_logs(created_at, action)`, `query_logs(created_at)` | dashboards |

## Integrity & lifecycle

- Deleting a document cascades to chunks, embeddings, entities and legal metadata (FK `ON DELETE CASCADE`); the API also deletes the stored file and OCR word boxes. Citations keep their text but lose the chunk link (`SET NULL`), preserving conversation history.
- Deleting a case keeps its documents (they become unassigned) - documents are never silently destroyed.
- Each chunk records the `embedding_model` that produced it; retrieval only compares vectors from the active model. Changing dimension → `python -m app.cli reindex --recreate`.
