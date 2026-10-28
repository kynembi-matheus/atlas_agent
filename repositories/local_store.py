"""Persistência local, com uma conexão SQLite por operação."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.history_identity import history_owner
from core.models import Run


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


def latest_conversations(runs, limit: int | None = None) -> list[Run]:
    conversations = {}
    for run in sorted(runs, key=lambda run: (run.created_at, run.id), reverse=True):
        conversations.setdefault(run.conversation_id, run)
    return list(conversations.values())[:limit]


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
                CREATE TABLE IF NOT EXISTS favorite_queries (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
            """)
            # Migração aditiva: registros legados permanecem sem proprietário.
            for table in ('runs', 'datasets', 'artifacts'):
                columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
                if 'owner_id' not in columns:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN owner_id TEXT')
                db.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_owner ON {table}(owner_id)')

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
            owner = history_owner.get()
            existing = db.execute('SELECT owner_id FROM runs WHERE id = ?', (run.id,)).fetchone()
            if existing:
                if owner is not None and existing[0] != owner:
                    raise ValueError('Execução fora do escopo do usuário.')
                owner = existing[0]
            db.execute("INSERT OR REPLACE INTO runs (id, conversation_id, payload, owner_id) VALUES (?, ?, ?, ?)",
                       (run.id, run.conversation_id, run.model_dump_json(), owner))

    def list_queries(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM favorite_queries ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_query(self, query_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM favorite_queries WHERE id = ?", (query_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_query(self, values: dict, query_id: str | None = None) -> dict | None:
        with self.connect() as db:
            if query_id:
                row = db.execute("SELECT payload FROM favorite_queries WHERE id = ?", (query_id,)).fetchone()
                if row is None:
                    return None
                item = {**json.loads(row[0]), **values, "updated_at": now()}
                db.execute("UPDATE favorite_queries SET payload = ? WHERE id = ?", (encode(item), query_id))
            else:
                item = {**values, "id": str(uuid4()), "created_at": now(), "updated_at": now()}
                db.execute("INSERT INTO favorite_queries VALUES (?, ?)", (item["id"], encode(item)))
        return item

    def delete_query(self, query_id: str) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM favorite_queries WHERE id = ?", (query_id,)).rowcount > 0

    def get_run(self, run_id: str) -> Run | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id = ? AND (? IS NULL OR owner_id = ?)",
                             (run_id, history_owner.get(), history_owner.get())).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 100) -> list[Run]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs WHERE json_extract(payload, '$.parent_run_id') IS NULL AND (? IS NULL OR owner_id = ?) ORDER BY rowid DESC LIMIT ?",
                              (history_owner.get(), history_owner.get(), limit)).fetchall()
        return [Run.model_validate_json(row[0]) for row in rows]

    def usage_statistics(self, temporary_runs=(), temporary_artifacts: int = 0) -> dict:
        # Aggregate all persisted requests, not the limited recent-history list.
        extra = [{"conversation_id": run.conversation_id, "status": run.status}
                 for run in temporary_runs]
        with self.connect() as db:
            row = db.execute("""
                WITH activity AS (
                    SELECT conversation_id, json_extract(payload, '$.status') AS status FROM runs
                    WHERE json_extract(payload, '$.parent_run_id') IS NULL AND (? IS NULL OR owner_id = ?)
                    UNION ALL
                    SELECT json_extract(value, '$.conversation_id'), json_extract(value, '$.status')
                    FROM json_each(?)
                )
                SELECT COUNT(DISTINCT conversation_id), COUNT(*),
                       COALESCE(SUM(status = 'completed'), 0),
                       (SELECT COUNT(*) FROM artifacts WHERE (? IS NULL OR owner_id = ?))
                FROM activity
            """, (history_owner.get(), history_owner.get(), encode(extra),
                  history_owner.get(), history_owner.get())).fetchone()
        return dict(conversations=row[0], requests=row[1], completed=row[2],
                    artifacts=row[3] + temporary_artifacts)

    def conversation(self, conversation_id: str, limit: int = 6) -> list[Run]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM runs WHERE conversation_id = ? AND json_extract(payload, '$.parent_run_id') IS NULL AND (? IS NULL OR owner_id = ?) ORDER BY rowid DESC LIMIT ?",
                (conversation_id, history_owner.get(), history_owner.get(), limit),
            ).fetchall()
        return [Run.model_validate_json(row[0]) for row in reversed(rows)]

    def list_conversations(self, limit: int | None = None) -> list[Run]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs WHERE json_extract(payload, '$.parent_run_id') IS NULL AND (? IS NULL OR owner_id = ?)",
                              (history_owner.get(), history_owner.get())).fetchall()
        return latest_conversations((Run.model_validate_json(row[0]) for row in rows), limit)

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
            db.execute("INSERT INTO datasets (id, run_id, payload, owner_id) VALUES (?, ?, ?, ?)",
                       (dataset["id"], run_id, encode(dataset), history_owner.get()))
        return dataset

    def get_dataset(self, dataset_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM datasets WHERE id = ? AND (? IS NULL OR owner_id = ?)",
                             (dataset_id, history_owner.get(), history_owner.get())).fetchone()
        return json.loads(row[0]) if row else None

    def save_artifact(self, run_id: str, title: str, extension: str, content: bytes) -> dict:
        artifact_id = str(uuid4())
        filename = f"{artifact_id}.{extension}"
        (self.artifacts_dir / filename).write_bytes(content)
        artifact = {"id": artifact_id, "title": title, "filename": filename,
                    "format": extension, "created_at": now(),
                    "url": f"/api/artifacts/{artifact_id}"}
        with self.connect() as db:
            db.execute("INSERT INTO artifacts (id, run_id, payload, owner_id) VALUES (?, ?, ?, ?)",
                       (artifact_id, run_id, encode(artifact), history_owner.get()))
        return artifact

    def get_artifact(self, artifact_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM artifacts WHERE id = ? AND (? IS NULL OR owner_id = ?)",
                             (artifact_id, history_owner.get(), history_owner.get())).fetchone()
        return json.loads(row[0]) if row else None
