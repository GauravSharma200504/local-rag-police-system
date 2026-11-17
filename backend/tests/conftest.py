"""Test configuration.

Integration tests need PostgreSQL with pgvector. Set TEST_DATABASE_URL (default: the docker-compose database
on localhost:5432). They are skipped automatically when no database is reachable.

Models: tests use the deterministic `hashing` embedder (no download) and a test double for the LLM, so the
retrieval/citation logic is tested exactly; real-model quality is measured by the evaluation framework instead.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="bpi-test-"))
os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://bpi:bpi_password@localhost:5432/bpi_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["EMBEDDING_DIM"] = "384"
os.environ["RERANKER_PROVIDER"] = "none"
os.environ["DATA_DIR"] = str(TMP / "data")
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"  # unreachable on purpose: no real LLM in unit tests

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "sample_data"


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP, ignore_errors=True)


def _db_available() -> bool:
    from sqlalchemy import create_engine, text

    try:
        eng = create_engine(os.environ["DATABASE_URL"])
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def db_engine():
    if not _db_available():
        pytest.skip("PostgreSQL + pgvector not reachable (set TEST_DATABASE_URL)")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.core.database import get_engine

    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    command.upgrade(cfg, "head")
    return eng


@pytest.fixture(scope="session")
def client(db_engine):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def users(db_engine):
    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models import User, UserRole

    db = SessionLocal()
    out = {}
    for name, role in (("admin", UserRole.admin), ("io", UserRole.investigator), ("io2", UserRole.investigator),
                       ("analyst", UserRole.analyst)):
        u = User(username=f"t_{name}", password_hash=hash_password("Password@123"), role=role, full_name=name)
        db.add(u)
        db.commit()
        out[name] = u
    db.close()
    return out


def login(client, username: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": "Password@123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def headers(client, users):
    return {k: login(client, f"t_{k}") for k in users}


def wait_indexed(client, h, doc_id, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        d = client.get(f"/api/v1/documents/{doc_id}", headers=h).json()
        if d["status"] in ("indexed", "failed"):
            return d
        time.sleep(0.3)
    raise AssertionError(f"document {doc_id} not processed in time")


class FakeLLM:
    """Deterministic LLM test double. `responder(messages) -> str` decides the reply."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def chat_stream(self, model, messages, temperature=0.1, num_ctx=8192):
        self.calls.append(messages)
        text = self.responder(messages)
        for i in range(0, len(text), 12):
            yield text[i:i + 12]

    def chat(self, model, messages, temperature=0.1, num_ctx=8192, fmt=None):
        self.calls.append(messages)
        return self.responder(messages)


@pytest.fixture
def fake_llm(monkeypatch):
    def install(responder):
        llm = FakeLLM(responder)
        import app.intelligence.comparison as comp
        import app.rag.engine as engine

        monkeypatch.setattr(engine, "get_llm", lambda: llm)
        monkeypatch.setattr(comp, "get_llm", lambda: llm)
        return llm

    return install
