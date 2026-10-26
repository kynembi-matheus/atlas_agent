from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import create_app
from core.models import Run


def request(conversation_id, status='completed'):
    return Run(id=str(uuid4()), conversation_id=conversation_id, prompt='Analisar dados',
               status=status, created_at='2026-10-26T12:00:00+00:00',
               updated_at='2026-10-26T12:00:00+00:00')


def test_usage_counts_all_requests_and_groups_conversations(store):
    conversation_id = str(uuid4())
    for _ in range(105):
        store.save_run(request(conversation_id))
    failed = request(str(uuid4()), 'failed')
    store.save_run(failed)
    store.save_artifact(failed.id, 'Relatório', 'txt', b'report')
    assert store.usage_statistics() == dict(conversations=2, requests=106, completed=105, artifacts=1)


def test_profile_includes_only_current_temporary_session(settings):
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        assert client.get('/api/profile').json()['usage'] == dict(
            conversations=0, requests=0, completed=0, artifacts=0)
        conversation_id = str(uuid4())
        client.app.state.store.save_run(request(conversation_id))
        first = client.post('/api/import-sessions').json()['session_id']
        second = client.post('/api/import-sessions').json()['session_id']
        temporary = client.app.state.imports.get(first).store
        run = request(conversation_id)
        temporary.save_run(run)
        temporary.save_run(request(str(uuid4()), 'failed'))
        temporary.save_artifact(run.id, 'Análise', 'txt', b'report')
        result = client.get('/api/profile', headers={'X-Data-Session': first}).json()
        assert result['name'] == 'Usuário'
        assert 'compartilhado' in result['scope']
        assert result['usage'] == dict(conversations=2, requests=3, completed=2, artifacts=1)
        for headers in ({}, {'X-Data-Session': second}):
            assert client.get('/api/profile', headers=headers).json()['usage'] == dict(
                conversations=1, requests=1, completed=1, artifacts=0)
