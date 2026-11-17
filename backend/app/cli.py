"""Command-line utilities.

  python -m app.cli create-admin --username admin [--password ...]
  python -m app.cli create-user --username io1 --role investigator
  python -m app.cli seed-demo            # demo users + case RJ-2026-001 + sample documents (synchronous ingestion)
  python -m app.cli download-models      # one-time download of embedding + reranker models (asks for confirmation)
  python -m app.cli reindex [--recreate] # re-embed all chunks after changing the embedding model
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

from sqlalchemy import select, text

from app.core.config import PROJECT_DIR, get_settings
from app.core.database import SessionLocal, get_engine
from app.core.security import hash_password
from app.models import Case, CaseMember, Document, DocumentStatus, DocumentType, LegalDocument, User, UserRole

SAMPLE_DIR = PROJECT_DIR / "sample_data"


def _create_user(db, username: str, password: str, role: UserRole, full_name: str = "") -> User:
    u = db.scalar(select(User).where(User.username == username))
    if u:
        print(f"User '{username}' already exists - leaving unchanged.")
        return u
    u = User(username=username, password_hash=hash_password(password), role=role, full_name=full_name)
    db.add(u)
    db.commit()
    print(f"Created {role.value} user '{username}'.")
    return u


def cmd_create_user(args, role: UserRole | None = None):
    password = args.password or getpass.getpass(f"Password for {args.username}: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters")
    db = SessionLocal()
    _create_user(db, args.username, password, role or UserRole(args.role), args.full_name or "")
    db.close()


def ingest_file(db, path: Path, doc_type: DocumentType, case: Case | None, user: User, legal: dict | None = None) -> Document:
    """Synchronous ingestion used by seeding and evaluation (same pipeline as the API)."""
    from app.ingestion.pipeline import process_document
    from app.services.storage import store_upload

    data = path.read_bytes()
    stored = store_upload(path.name, data)
    doc = db.scalar(select(Document).where(Document.sha256 == stored.sha256))
    if doc is None:
        doc = Document(title=path.stem.replace("_", " "), original_filename=path.name, stored_path=str(stored.path),
                       mime_type=stored.mime, file_ext=stored.ext, sha256=stored.sha256, size_bytes=stored.size,
                       doc_type=doc_type, case_id=case.id if case else None, uploaded_by=user.id,
                       police_station=case.police_station if case else None, district=case.district if case else None,
                       classification="restricted", metadata_json={})
        db.add(doc)
        db.flush()
        if legal:
            db.add(LegalDocument(document_id=doc.id, **legal))
        db.commit()
    if doc.status != DocumentStatus.indexed or doc.embedding_model is None:
        doc = process_document(db, doc.id)
    return doc


def cmd_seed_demo(args):
    import json

    manifest_path = SAMPLE_DIR / "manifest.json"
    if not manifest_path.exists():
        sys.exit("sample_data/manifest.json not found. Run: python scripts/generate_sample_data.py")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = SessionLocal()
    admin_pw = args.admin_password or secrets.token_urlsafe(9)
    admin = _create_user(db, "admin", admin_pw, UserRole.admin, "System Administrator")
    io_pw = args.officer_password or secrets.token_urlsafe(9)
    io_user = _create_user(db, "io.sharma", io_pw, UserRole.investigator, "SI Kavita Sharma (fictional)")
    analyst_pw = args.analyst_password or secrets.token_urlsafe(9)
    analyst = _create_user(db, "analyst.verma", analyst_pw, UserRole.analyst, "Analyst R. Verma (fictional)")
    for c in manifest["cases"]:
        case = db.scalar(select(Case).where(Case.case_number == c["case_number"]))
        if case is None:
            case = Case(case_number=c["case_number"], title=c["title"], description=c.get("description", ""),
                        police_station=c.get("police_station"), district=c.get("district"), created_by=admin.id)
            db.add(case)
            db.commit()
        members = [admin, io_user] + ([analyst] if c.get("analyst_access") else [])
        for m in members:
            if not db.scalar(select(CaseMember).where(CaseMember.case_id == case.id, CaseMember.user_id == m.id)):
                db.add(CaseMember(case_id=case.id, user_id=m.id))
        db.commit()
        for d in c["documents"]:
            doc = ingest_file(db, SAMPLE_DIR / d["file"], DocumentType(d["doc_type"]), case, io_user if c.get("owner") == "io" else admin,
                              d.get("legal"))
            print(f"  [{doc.status.value}] {c['case_number']} / {d['file']} ({doc.chunk_count} chunks)"
                  + (f"  ERROR: {doc.error_message}" if doc.error_message else ""))
    db.close()
    print("\nDemo credentials (CHANGE THESE after the demo - Settings > Users):")
    if args.admin_password is None:
        print(f"  admin / {admin_pw}")
    if args.officer_password is None:
        print(f"  io.sharma / {io_pw}  (investigator: member of all demo cases)")
    if args.analyst_password is None:
        print(f"  analyst.verma / {analyst_pw}  (analyst: access to RJ-2026-001 only)")


def cmd_download_models(args):
    s = get_settings()
    targets = []
    if s.embedding_provider == "sentence_transformers":
        targets.append(("embedding", s.embedding_model))
    if s.reranker_provider == "cross_encoder":
        targets.append(("reranker", s.reranker_model))
    if not targets:
        print("No Hugging Face models configured.")
        return
    print("This will download (one time, ~0.5 GB each) to the local Hugging Face cache:")
    for kind, m in targets:
        print(f"  - {kind}: {m}")
    if not args.yes and input("Proceed? [y/N] ").strip().lower() != "y":
        print("Cancelled.")
        return
    from sentence_transformers import CrossEncoder, SentenceTransformer

    for kind, m in targets:
        print(f"Downloading {m} ...")
        (SentenceTransformer if kind == "embedding" else CrossEncoder)(m)
    print(f"Done. Also pull the LLM once:  ollama pull {s.ollama_model}")


def cmd_reindex(args):
    from app.ingestion.pipeline import process_document

    s = get_settings()
    if args.recreate:
        print(f"Recreating embedding column with dimension {s.embedding_dim} (all embeddings are cleared) ...")
        with get_engine().begin() as conn:
            conn.execute(text("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw"))
            conn.execute(text("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding"))
            conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN embedding vector({int(s.embedding_dim)})"))
            conn.execute(text("CREATE INDEX ix_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops)"))
    db = SessionLocal()
    ids = list(db.scalars(select(Document.id)))
    for i, doc_id in enumerate(ids, 1):
        d = process_document(db, doc_id)
        print(f"[{i}/{len(ids)}] {d.title}: {d.status.value}")
    db.close()


def main():
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--username", default="admin")
    a.add_argument("--password")
    a.add_argument("--full-name", default="System Administrator")
    u = sub.add_parser("create-user")
    u.add_argument("--username", required=True)
    u.add_argument("--password")
    u.add_argument("--full-name", default="")
    u.add_argument("--role", choices=[r.value for r in UserRole], default="investigator")
    s = sub.add_parser("seed-demo")
    s.add_argument("--admin-password")
    s.add_argument("--officer-password")
    s.add_argument("--analyst-password")
    d = sub.add_parser("download-models")
    d.add_argument("--yes", action="store_true")
    r = sub.add_parser("reindex")
    r.add_argument("--recreate", action="store_true")
    args = p.parse_args()
    if args.cmd == "create-admin":
        cmd_create_user(args, UserRole.admin)
    elif args.cmd == "create-user":
        cmd_create_user(args)
    elif args.cmd == "seed-demo":
        cmd_seed_demo(args)
    elif args.cmd == "download-models":
        cmd_download_models(args)
    elif args.cmd == "reindex":
        cmd_reindex(args)


if __name__ == "__main__":
    main()
