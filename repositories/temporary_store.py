"""Dados Parquet e execuções de sessão que nunca são gravados no SQLite persistente."""
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd

from core.models import AgentError, Run
from repositories.local_store import Store, encode, now, latest_conversations


def remove_session_directory(path: Path, root: Path):
    resolved, parent = path.resolve(), root.resolve()
    # A remoção recursiva só aceita uma pasta UUID dentro da área temporária gerenciada.
    if resolved == parent or not resolved.is_relative_to(parent) or path.is_symlink():
        raise AgentError('Diretório temporário fora da área permitida.')
    try:
        UUID(path.name)
    except ValueError:
        raise AgentError('Diretório temporário inválido.') from None
    if path.is_dir():
        shutil.rmtree(resolved)


class TemporaryStore:
    def __init__(self, persistent: Store, root: Path, session_id: str):
        self.persistent, self.root = persistent, root / session_id
        self.root.mkdir(parents=True)
        self.artifacts_dir = self.root / 'artifacts'
        self.artifacts_dir.mkdir()
        self.datasets, self.runs, self.artifacts = {}, {}, {}
        self.closed = False

    def require_open(self):
        if self.closed:
            raise AgentError('A sessão temporária expirou. Importe os dados novamente.')

    def save_dataset(self, rows: list[dict], source: dict, run_id: str | None = None):
        self.require_open()
        dataset_id = str(uuid4())
        normalized = json.loads(encode(rows))
        frame = pd.DataFrame(normalized)
        path = self.root / f'{dataset_id}.parquet'
        partial = path.with_suffix('.partial')
        try:
            for name, dtype in source.get('inferred_types', {}).items():
                if name not in frame:
                    continue
                if dtype == 'integer':
                    frame[name] = frame[name].astype('Int64')
                elif dtype == 'date':
                    frame[name] = pd.to_datetime(frame[name], errors='raise')
                elif dtype == 'boolean':
                    frame[name] = frame[name].astype('boolean')
            frame.to_parquet(partial, engine='pyarrow', index=False)
            partial.replace(path)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise AgentError('Não foi possível armazenar os dados temporários em Parquet.') from exc
        metadata = {'id': dataset_id, 'source': {**source, 'temporary': True}, 'created_at': now(),
                    'row_count': len(frame), 'columns': list(frame.columns)}
        self.datasets[dataset_id] = metadata
        return {**metadata, 'rows': normalized}

    def get_dataset(self, dataset_id: str):
        self.require_open()
        metadata = self.datasets.get(dataset_id)
        if metadata is None:
            return self.persistent.get_dataset(dataset_id)
        path = self.root / f'{dataset_id}.parquet'
        if not path.is_file():
            return None
        frame = pd.read_parquet(path, engine='pyarrow')
        rows = frame.astype(object).where(frame.notna(), None).to_dict(orient='records')
        for row in rows:
            for name, value in row.items():
                if isinstance(value, (date, datetime)):
                    row[name] = value.isoformat()
        return {**metadata, 'rows': json.loads(encode(rows))}

    def remove_dataset(self, dataset_id: str):
        self.datasets.pop(dataset_id, None)
        (self.root / f'{dataset_id}.parquet').unlink(missing_ok=True)

    def save_run(self, run: Run):
        self.require_open()
        run.updated_at = now()
        self.runs[run.id] = run.model_copy(deep=True)

    def get_run(self, run_id: str):
        self.require_open()
        run = self.runs.get(run_id)
        return run.model_copy(deep=True) if run else self.persistent.get_run(run_id)

    def list_runs(self, limit: int = 100):
        self.require_open()
        runs = [*self.persistent.list_runs(limit), *self.runs.values()]
        return sorted(runs, key=lambda run: run.created_at, reverse=True)[:limit]

    def conversation(self, conversation_id: str, limit: int = 6):
        runs = [*self.persistent.conversation(conversation_id, limit),
                *(run for run in self.runs.values() if run.conversation_id == conversation_id)]
        return sorted(runs, key=lambda run: run.created_at)[-limit:]

    def list_conversations(self, limit: int | None = None):
        self.require_open()
        return latest_conversations(
            [*self.persistent.list_conversations(), *self.runs.values()], limit)

    def has_conversation(self, conversation_id: str | None):
        return any(run.conversation_id == conversation_id for run in self.runs.values())

    def usage_statistics(self):
        self.require_open()
        return self.persistent.usage_statistics(self.runs.values(), len(self.artifacts))

    def save_artifact(self, run_id: str, title: str, extension: str, content: bytes):
        self.require_open()
        artifact_id = str(uuid4())
        filename = f'{artifact_id}.{extension}'
        (self.artifacts_dir / filename).write_bytes(content)
        artifact = {'id': artifact_id, 'title': title, 'filename': filename, 'format': extension,
                    'created_at': now(), 'url': f'/api/artifacts/{artifact_id}', 'temporary': True}
        self.artifacts[artifact_id] = artifact
        return artifact

    def get_artifact(self, artifact_id: str):
        self.require_open()
        return self.artifacts.get(artifact_id) or self.persistent.get_artifact(artifact_id)

    def artifact_path(self, artifact: dict):
        root = self.artifacts_dir if artifact['id'] in self.artifacts else self.persistent.artifacts_dir
        return root / artifact['filename']

    def recover(self):
        pass

    def close(self):
        self.closed = True
        self.datasets.clear()
        self.runs.clear()
        self.artifacts.clear()
        remove_session_directory(self.root, self.root.parent)
