# Experimental evaluation

## Goal

Measure whether the proposed pipeline (Hybrid + RRF + Cross-Encoder Reranking + Citation Validation) improves retrieval and grounded generation over two baselines:

| ID | Configuration |
|---|---|
| Baseline 1 | `vector` - dense retrieval only |
| Baseline 2 | `hybrid` - dense + sparse (PostgreSQL FTS) fused by RRF |
| Proposed | `proposed` - hybrid + RRF + cross-encoder reranking (+ threshold) + citation validation |

## Dataset

`evaluation/dataset/eval_dataset.json` - 32 questions written together with the synthetic corpus (`scripts/generate_sample_data.py`), so every label is checked to exist in the generated files at generation time.

Corpus: 12 fictional documents in 4 cases - the main case RJ-2026-001 (FIR, two witness statements - one **scanned**, investigation report, evidence report, legal note) plus **hard negatives**: another jewellery robbery (RJ-2025-118), a burglary on the same street with a near-identical vehicle number `RJ 14 KB 4512` vs `RJ 14 KB 4521` (RJ-2026-002, includes a DOCX and a prompt-injection string), and a chain snatching with a Hindi witness statement (RJ-2026-003).

| Category | # | Tests |
|---|---|---|
| factual | 10 | single-fact lookup |
| exact_id | 3 | FIR/vehicle/identifier matching (sparse retrieval strength) |
| legal | 2 | section citations, historical IPC reference |
| multi_hop | 2 | facts spread over sentences/documents |
| comparison | 1 | same fact in two documents |
| conflict | 4 | deliberately contradictory documents |
| timeline | 3 | times/dates across documents |
| multilingual | 1 | Hindi query over a Hindi document |
| unanswerable | 4 | answer absent from all documents → must abstain |
| out_of_scope | 1 | unrelated question → must abstain |
| injection | 1 | must not follow the injected instruction (no "guilty") |

Each answerable item lists `relevant: [{file, evidence, pages}]`, `expected_answer` and `must_include` key facts. **The project team should review the ground truth** (human-reviewed labels are a requirement for reporting).

## Metrics

Retrieval (answerable questions, top 5 chunks). A chunk is relevant if it comes from a labelled file and contains the labelled evidence text (≥ 80 % token overlap, tolerant to OCR noise).

- **Recall@5** = labelled evidence items covered / total evidence items
- **Precision@5** = relevant chunks in top 5 / 5
- **MRR** = 1 / rank of first relevant chunk
- **nDCG@5** = binary-gain DCG / ideal DCG (ideal uses min(#evidence, 5) positions)

Generation (needs Ollama):

- **Faithfulness** - share of answer sentences supported by the retrieved sources (≥ 50 % content-word overlap and all numbers present). A lexical proxy; optionally complement with manual grading of a sample.
- **Answer relevance** - share of `must_include` facts present in the answer.
- **Citation accuracy** - share of the answer's citations pointing to a relevant chunk.
- **Abstention accuracy** - unanswerable/out-of-scope → abstained; answerable → answered; injection → did not output the injected claim.

Performance: average retrieval latency, end-to-end latency, average document processing time (from ingestion).

## Running

```bash
# prerequisites: DB migrated, models downloaded, Ollama running with OLLAMA_MODEL pulled
python scripts/generate_sample_data.py
python evaluation/scripts/run_evaluation.py                      # all configs, retrieval + generation
python evaluation/scripts/run_evaluation.py --no-generation      # retrieval only (no LLM needed)
python evaluation/scripts/run_evaluation.py --configs hybrid proposed --limit 10
```

Or from the UI: **Reports → Experimental evaluation** (admin). The corpus is ingested automatically (idempotent) under an `eval_admin` account, so evaluation always sees all 12 documents.

Outputs in `evaluation/results/`: `latest.json`, `run_<ts>.json` (environment, ingestion times, summary, per-category, per-question rows with answers), `summary_<ts>.csv`, `per_question_<ts>.csv`, `charts_<ts>_retrieval.png`, `charts_<ts>_generation.png`, `charts_<ts>_latency.png`.

## Reporting guidance

- Report the exact environment block from `run_<ts>.json` (models, thresholds, hardware).
- Run each configuration at least 3 times for latency and report mean ± std; retrieval metrics are deterministic for fixed models.
- Discuss per-category results: hybrid retrieval is expected to matter most for `exact_id`; reranking for `conflict`/`multi_hop`; citation validation for faithfulness/abstention - **but only claim what the measured numbers show**.
- The dataset is small and synthetic; state this as a threat to validity.

No numbers are included in this repository: results must come from your own runs.
