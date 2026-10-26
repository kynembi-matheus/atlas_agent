from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import create_app
from core.models import Run
from repositories.temporary_store import TemporaryStore


def run_at(index, conversation_id=None):
    return Run(id=str(uuid4()), conversation_id=conversation_id or str(uuid4()),
               prompt=f'Pedido {index}', status='completed',
               created_at=f'2026-10-26T{index // 60:02}:{index % 60:02}:00+00:00',
               updated_at='2026-10-26T00:00:00+00:00')


def test_history_includes_all_conversations_and_limits_after_grouping(settings, store):
    runs = [run_at(index) for index in range(105)]
    for run in reversed(runs):
        store.save_run(run)
    latest = run_at(110, runs[-1].conversation_id)
    store.save_run(latest)
    # Updating an old execution must not move it ahead of newer messages.
    store.save_run(runs[0])
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        all_runs = client.get('/api/conversations').json()
        assert len(all_runs) == 105
        assert all_runs[0]['id'] == latest.id
        assert all_runs[-1]['id'] == runs[0].id
        assert client.get('/api/conversations?limit=5').json() == all_runs[:5]
        assert client.get('/api/conversations?limit=0').status_code == 422
        page = client.get('/historico')
        assert page.status_code == 200
        assert 'id="all-history"' in page.text


def test_temporary_history_respects_session_isolation(store, tmp_path):
    persistent = run_at(1)
    store.save_run(persistent)
    first = TemporaryStore(store, tmp_path / 'sessions', str(uuid4()))
    second = TemporaryStore(store, tmp_path / 'sessions', str(uuid4()))
    temporary = run_at(2)
    first.save_run(temporary)
    assert [run.id for run in first.list_conversations()] == [temporary.id, persistent.id]
    assert [run.id for run in first.list_conversations(1)] == [temporary.id]
    assert [run.id for run in second.list_conversations()] == [persistent.id]
    assert [run.id for run in store.list_conversations()] == [persistent.id]
