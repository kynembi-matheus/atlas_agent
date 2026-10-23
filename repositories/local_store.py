"""Persistência local, com uma conexão SQLite por operação."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.models import Run


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = self.root / "artifacts"
        self.artifacts_dir.mkdir(exist_ok=True)
        self.database = self.root / "agent.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, run_id TEXT, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_run(self, run: Run):
        run.updated_at = now()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?)",
                       (run.id, run.conversation_id, run.model_dump_json()))

    def get_run(self, run_id: str) -> Run | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 100) -> list[Run]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs ORDER BY rowid DESC LIMIT ?",
                              (limit,)).fetchall()
        return [Run.model_validate_json(row[0]) for row in rows]

    def conversation(self, conversation_id: str, limit: int = 6) -> list[Run]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM runs WHERE conversation_id = ? ORDER BY rowid DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [Run.model_validate_json(row[0]) for row in reversed(rows)]

    def recover(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs").fetchall()
        for (payload,) in rows:
            run = Run.model_validate_json(payload)
            if run.status in {"queued", "running"}:
                run.status = "failed"
                run.error = "Execução interrompida pelo reinício do serviço. Envie o pedido novamente."
                self.save_run(run)

    def save_dataset(self, rows: list[dict], source: dict, run_id: str | None = None) -> dict:
        dataset = {"id": str(uuid4()), "rows": rows, "source": source, "created_at": now()}
        with self.connect() as db:
            db.execute("INSERT INTO datasets VALUES (?, ?, ?)",
                       (dataset["id"], run_id, encode(dataset)))
        return dataset

    def get_dataset(self, dataset_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_artifact(self, run_id: str, title: str, extension: str, content: bytes) -> dict:
        artifact_id = str(uuid4())
        filename = f"{artifact_id}.{extension}"
        (self.artifacts_dir / filename).write_bytes(content)
        artifact = {"id": artifact_id, "title": title, "filename": filename,
                    "format": extension, "created_at": now(),
                    "url": f"/api/artifacts/{artifact_id}"}
        with self.connect() as db:
            db.execute("INSERT INTO artifacts VALUES (?, ?, ?)",
                       (artifact_id, run_id, encode(artifact)))
        return artifact

    def get_artifact(self, artifact_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return json.loads(row[0]) if row else None
