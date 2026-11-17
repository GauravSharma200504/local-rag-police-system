"""Experimental evaluation: Vector-only RAG vs Hybrid RAG (RRF) vs Proposed (Hybrid + RRF + Cross-Encoder + Citation Validation).

    python evaluation/scripts/run_evaluation.py                       # all configs, retrieval + generation
    python evaluation/scripts/run_evaluation.py --configs vector hybrid --no-generation
    python evaluation/scripts/run_evaluation.py --limit 5             # quick smoke run

Prerequisites: database migrated, sample data generated (scripts/generate_sample_data.py). The corpus in
sample_data/manifest.json is ingested automatically (idempotent) under a dedicated evaluation admin account.
Generation metrics need a running Ollama with the configured model; otherwise only retrieval metrics are computed.

Metric definitions (see docs/EVALUATION.md):
  Relevance  - a retrieved chunk is relevant to a question if it comes from a labelled file AND contains the labelled
               evidence text (token overlap >= 0.8, tolerant to OCR noise).
  Recall@5   - share of labelled evidence items covered by the top 5 chunks.
  Precision@5- relevant chunks among the top 5 / 5.
  MRR        - 1 / rank of the first relevant chunk (0 if none in top 5).
  nDCG@5     - binary-gain nDCG; ideal DCG uses min(#evidence items, 5) relevant positions.
  Faithfulness      - share of answer sentences lexically supported (support >= 0.5) by the retrieved sources
                      (proxy metric; numbers in a sentence must appear in the source).
  Answer relevance  - share of the question's key facts (must_include) present in the answer.
  Citation accuracy - share of the answer's citations that point to a relevant chunk.
  Abstention acc.   - correct abstention on unanswerable/out-of-scope questions and correct answering otherwise.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402

DATASET = ROOT / "evaluation" / "dataset" / "eval_dataset.json"
RESULTS = ROOT / "evaluation" / "results"
_W = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)


def _toks(t: str) -> list[str]:
    return [w.lower() for w in _W.findall(t)]


def evidence_in(evidence: str, text: str) -> bool:
    if " ".join(evidence.lower().split()) in " ".join(text.lower().split()):
        return True
    ev, tx = _toks(evidence), set(_toks(text))
    return bool(ev) and sum(1 for t in ev if t in tx) / len(ev) >= 0.8


def chunk_matches(item: dict, filename: str, text: str) -> list[int]:
    """Indices of the question's evidence items satisfied by this chunk."""
    return [i for i, r in enumerate(item["relevant"]) if r["file"] == filename and evidence_in(r["evidence"], text)]


def retrieval_metrics(item: dict, cands: list, k: int = 5) -> dict:
    top = cands[:k]
    covered, rels = set(), []
    for c in top:
        m = chunk_matches(item, c.filename, c.text)
        rels.append(1 if m else 0)
        covered.update(m)
    n_ev = len(item["relevant"])
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels))
    idcg = sum(1 / math.log2(i + 2) for i in range(min(n_ev, k)))
    first = next((i + 1 for i, r in enumerate(rels) if r), None)
    return {"recall@5": len(covered) / n_ev, "precision@5": sum(rels) / k, "mrr": 1 / first if first else 0.0,
            "ndcg@5": dcg / idcg if idcg else 0.0}


def contains_fact(answer: str, fact: str) -> bool:
    norm = lambda s: " ".join(s.lower().replace(",", "").split())  # noqa: E731
    return any(norm(alt) in norm(answer) for alt in fact.split("|"))


def generation_metrics(item: dict, res, sources_by_label: dict) -> dict:
    from app.rag import citations as cit

    out = {"abstained": res.abstained}
    expected_abstain = not item["answerable"]
    if item["category"] == "injection":
        bad = any(contains_fact(res.answer, x) for x in item["must_not_include"])
        out["abstention_correct"] = bool(res.abstained or not bad)
    else:
        out["abstention_correct"] = res.abstained == expected_abstain
    if res.abstained:
        return out
    text = cit.MARKER.sub("", res.answer)
    sents = [s for s in cit.split_sentences(text) if len(cit.content_words(s)) >= 3]
    corpus = " ".join(s["text"] for s in res.sources)
    if sents:
        out["faithfulness"] = sum(1 for s in sents if cit.support_score(s, corpus) >= 0.5) / len(sents)
    if item["answerable"] and item["must_include"]:
        out["answer_relevance"] = sum(1 for f in item["must_include"] if contains_fact(res.answer, f)) / len(item["must_include"])
    if item["answerable"] and res.citations:
        ok = 0
        for c in res.citations:
            src = sources_by_label.get(c["label"])
            if src and chunk_matches(item, src["filename"], src["text"]):
                ok += 1
        out["citation_accuracy"] = ok / len(res.citations)
    elif item["answerable"]:
        out["citation_accuracy"] = 0.0
    return out


def ensure_corpus(db, log) -> dict:
    """Ingest the manifest corpus (idempotent). Returns per-document processing times."""
    from sqlalchemy import select

    from app.cli import SAMPLE_DIR, ingest_file
    from app.core.security import hash_password
    from app.models import Case, DocumentType, User, UserRole

    user = db.scalar(select(User).where(User.username == "eval_admin"))
    if user is None:
        import secrets

        user = User(username="eval_admin", full_name="Evaluation runner", role=UserRole.admin,
                    password_hash=hash_password(secrets.token_urlsafe(16)))
        db.add(user)
        db.commit()
    manifest = json.loads((SAMPLE_DIR / "manifest.json").read_text(encoding="utf-8"))
    times = {}
    for c in manifest["cases"]:
        case = db.scalar(select(Case).where(Case.case_number == c["case_number"]))
        if case is None:
            case = Case(case_number=c["case_number"], title=c["title"], police_station=c.get("police_station"),
                        district=c.get("district"), created_by=user.id, description=c.get("description", ""))
            db.add(case)
            db.commit()
        for d in c["documents"]:
            doc = ingest_file(db, SAMPLE_DIR / d["file"], DocumentType(d["doc_type"]), case, user, d.get("legal"))
            if doc.status.value != "indexed":
                raise RuntimeError(f"Ingestion failed for {d['file']}: {doc.error_message}")
            times[Path(d["file"]).name] = {"seconds": doc.processing_seconds, "pages": doc.page_count,
                                           "chunks": doc.chunk_count, "ocr_pages": len(doc.ocr_pages or [])}
            log(f"indexed {d['file']} ({doc.chunk_count} chunks)")
    return {"user": user, "documents": times}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def run(configs=("vector", "hybrid", "proposed"), generation=True, limit=None, out_dir: Path | None = None, log=print):
    from app.core.database import SessionLocal
    from app.rag.engine import answer
    from app.rag.llm import OllamaClient
    from app.retrieval.pipeline import retrieve
    from app.services.runtime_settings import load_params

    out_dir = out_dir or RESULTS
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    items = data["questions"][:limit] if limit else data["questions"]
    db = SessionLocal()
    corpus = ensure_corpus(db, log)
    user = corpus["user"]
    params = load_params(db)
    llm_status = OllamaClient().status(params.ollama_model)
    gen_enabled = generation and llm_status["reachable"] and llm_status["model_available"]
    if generation and not gen_enabled:
        log(f"Generation metrics skipped: {llm_status.get('error') or llm_status.get('hint')}")
    if settings.embedding_provider == "hashing":
        log("WARNING: EMBEDDING_PROVIDER=hashing is a lexical test embedder; results do not represent semantic models.")

    rows = []
    for config in configs:
        log(f"--- configuration: {config}")
        for item in items:
            t = time.perf_counter()
            rr = retrieve(db, user, item["question"], params, config=config, final_k=5)
            r_ms = (time.perf_counter() - t) * 1000
            row = {"config": config, "id": item["id"], "category": item["category"], "question": item["question"],
                   "retrieval_ms": round(r_ms, 1), "retrieved": [f"{c.filename}#p{c.page_start}" for c in rr.candidates]}
            if item["answerable"]:
                row.update(retrieval_metrics(item, rr.candidates))
            if gen_enabled:
                res = answer(db, user, item["question"], params, config=config, retrieval_result=rr)
                row.update(generation_metrics(item, res, {s["label"]: s for s in res.sources}))
                row["total_ms"] = round(r_ms + res.timings_ms.get("generation_ms", 0), 1)
                row["answer"] = res.answer
            rows.append(row)
            log(f"{config} {item['id']} R@5={row.get('recall@5', '-')} MRR={row.get('mrr', '-')}"
                + (f" abst={row.get('abstained')} ok={row.get('abstention_correct')}" if gen_enabled else ""))
    db.close()

    metric_keys = ["recall@5", "precision@5", "mrr", "ndcg@5", "faithfulness", "answer_relevance", "citation_accuracy",
                   "abstention_correct", "retrieval_ms", "total_ms"]
    summary = {}
    for config in configs:
        rs = [r for r in rows if r["config"] == config]
        summary[config] = {k if k != "abstention_correct" else "abstention_accuracy":
                           _mean([float(r[k]) for r in rs if k in r]) for k in metric_keys}
        summary[config]["questions"] = len(rs)
    by_category = {}
    for config in configs:
        for cat in sorted({r["category"] for r in rows}):
            rs = [r for r in rows if r["config"] == config and r["category"] == cat]
            by_category.setdefault(cat, {})[config] = {k: _mean([r[k] for r in rs if k in r]) for k in ("recall@5", "mrr")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "timestamp": stamp, "dataset": str(DATASET.relative_to(ROOT)), "questions": len(items),
        "environment": {"embedding_provider": settings.embedding_provider, "embedding_model": settings.embedding_model,
                        "reranker_provider": settings.reranker_provider, "reranker_model": settings.reranker_model,
                        "llm": params.ollama_model if gen_enabled else None, "generation_evaluated": gen_enabled,
                        "chunk_size": settings.chunk_size_tokens, "chunk_overlap": settings.chunk_overlap_tokens,
                        "retrieval_top_k": params.retrieval_top_k, "final_k": 5, "rrf_k": params.rrf_k,
                        "rerank_score_threshold": params.rerank_score_threshold},
        "ingestion": corpus["documents"],
        "avg_document_processing_seconds": _mean([d["seconds"] for d in corpus["documents"].values()]),
        "summary": summary, "by_category": by_category, "per_question": rows,
    }
    (out_dir / f"run_{stamp}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out_dir / f"summary_{stamp}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        cols = ["recall@5", "precision@5", "mrr", "ndcg@5", "faithfulness", "answer_relevance", "citation_accuracy",
                "abstention_accuracy", "retrieval_ms", "total_ms"]
        w.writerow(["config"] + cols)
        for config in configs:
            w.writerow([config] + [summary[config].get(c) for c in cols])
    with open(out_dir / f"per_question_{stamp}.csv", "w", newline="", encoding="utf-8") as f:
        cols = ["config", "id", "category", "question", "recall@5", "precision@5", "mrr", "ndcg@5", "faithfulness",
                "answer_relevance", "citation_accuracy", "abstained", "abstention_correct", "retrieval_ms", "total_ms"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    make_charts(summary, configs, out_dir, stamp)
    log(f"Results written to {out_dir} (run_{stamp}.json, summary_{stamp}.csv, charts_{stamp}_*.png)")
    return report


def make_charts(summary: dict, configs, out_dir: Path, stamp: str):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    colors = {"vector": "#94a3b8", "hybrid": "#3b82f6", "proposed": "#1e3a8a"}
    groups = [("retrieval", ["recall@5", "precision@5", "mrr", "ndcg@5"]),
              ("generation", ["faithfulness", "answer_relevance", "citation_accuracy", "abstention_accuracy"])]
    for name, keys in groups:
        if all(summary[c].get(k) is None for c in configs for k in keys):
            continue
        fig, ax = plt.subplots(figsize=(8, 4.2))
        width = 0.8 / len(configs)
        for i, c in enumerate(configs):
            vals = [summary[c].get(k) or 0 for k in keys]
            bars = ax.bar([x + i * width for x in range(len(keys))], vals, width, label=c, color=colors.get(c))
            ax.bar_label(bars, fmt="%.2f", fontsize=7)
        ax.set_xticks([x + width * (len(configs) - 1) / 2 for x in range(len(keys))], keys)
        ax.set_ylim(0, 1.1)
        ax.set_title(f"{name.title()} metrics by configuration")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(out_dir / f"charts_{stamp}_{name}.png", dpi=150)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 3.5))
    vals = [summary[c].get("retrieval_ms") or 0 for c in configs]
    bars = ax.bar(configs, vals, color=[colors.get(c) for c in configs])
    ax.bar_label(bars, fmt="%.0f ms", fontsize=8)
    ax.set_title("Average retrieval latency")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / f"charts_{stamp}_latency.png", dpi=150)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--configs", nargs="+", default=["vector", "hybrid", "proposed"], choices=["vector", "hybrid", "proposed"])
    p.add_argument("--no-generation", action="store_true", help="Only retrieval metrics (no LLM needed)")
    p.add_argument("--limit", type=int)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    run(a.configs, not a.no_generation, a.limit, a.out)


if __name__ == "__main__":
    main()
