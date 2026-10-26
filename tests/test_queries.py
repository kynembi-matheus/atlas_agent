"""Favoritas persistem localmente; IA e PostgreSQL são simulados."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agents.orchestrator import Agent, RunManager
from api.main import create_app
from core.models import AgentError, Run, RunRequest
from repositories.local_store import Store
from tools.data_tools import Toolbox, definitions


class QueryMCP:
    def __init__(self):
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, args))
        if name == 'list_databases':
            return ['cora', 'postgres']
        return {'rows': [{'valor': i} for i in range(15)]}


def favorite(**changes):
    return {'name': 'Indicadores', 'description': 'Resumo', 'database': 'cora',
            'sql': 'SELECT valor FROM public.indicadores', 'max_rows': 1000, **changes}


def test_crud_persists_and_validates_without_mcp(settings):
    mcp = QueryMCP()
    with TestClient(create_app(settings, mcp=mcp, client=object())) as client:
        saved = client.post('/api/queries', json=favorite())
        assert saved.status_code == 201
        item = saved.json()
        assert Store(settings.data_dir).get_query(item['id']) == item
        assert client.get('/api/queries').json()['queries'] == [item]
        updated = client.put('/api/queries/' + item['id'], json=favorite(name='Nova', sql='SELECT 2'))
        assert updated.status_code == 200
        assert updated.json()['created_at'] == item['created_at']
        assert updated.json()['sql'] == 'SELECT 2'
        for change in [{'name': '   '}, {'sql': 'DELETE FROM x'}, {'sql': 'SELECT 1; SELECT 2'},
                       {'sql': 'SELECT * INTO x FROM y'}, {'database': 'postgres'}, {'max_rows': 0}]:
            assert client.post('/api/queries', json=favorite(**change)).status_code == 422
        assert mcp.calls == []
        assert client.delete('/api/queries/' + item['id']).status_code == 204
        assert client.delete('/api/queries/' + item['id']).status_code == 404
        assert client.put('/api/queries/' + item['id'], json=favorite()).status_code == 404
        assert client.post('/api/queries/' + item['id'] + '/execute').status_code == 404


def test_execution_preserves_limits_source_and_supports_sessions(settings):
    mcp = QueryMCP()
    with TestClient(create_app(settings, mcp=mcp, client=object())) as client:
        item = client.post('/api/queries', json=favorite()).json()
        for headers in [{}, {'X-Data-Session': client.post('/api/import-sessions').json()['session_id']}]:
            response = client.post(f"/api/queries/{item['id']}/execute", headers=headers)
            assert response.status_code == 200
            result = response.json()
            assert result['row_count'] == 10
            assert result['possibly_truncated'] is True
            assert result['source']['favorite_query_id'] == item['id']
            assert result['source']['sql'] == item['sql']
            assert result['source']['database'] == 'cora'
            dataset = client.get('/api/datasets/' + result['dataset_id'], headers=headers)
            assert dataset.status_code == 200
            assert mcp.calls[-1][1]['max_rows'] == 10


async def test_tools_and_changed_database_permissions(settings, store):
    item = store.save_query(favorite())
    mcp = QueryMCP()
    toolbox = Toolbox(settings, store, mcp, None)
    assert {'list_favorite_queries', 'run_favorite_query'} <= {tool['name'] for tool in definitions()}
    assert (await toolbox.call('list_favorite_queries', {}))['queries'] == [item]
    settings.allowed_databases = ['hub']
    with pytest.raises(AgentError, match='database permitido'):
        await toolbox.call('run_favorite_query', {'query_id': item['id']})
    assert not any(name == 'query' for name, _ in mcp.calls)
    settings.allowed_databases = []
    store.save_query(favorite(sql='DELETE FROM x'), item['id'])
    toolbox = Toolbox(settings, store, mcp, None)
    with pytest.raises(AgentError, match='SELECT'):
        await toolbox.call('run_favorite_query', {'query_id': item['id']})
    assert not any(name == 'query' for name, _ in mcp.calls)


async def test_selected_query_reaches_agent_as_definition(settings, store):
    item = store.save_query(favorite())
    captured = []

    async def respond(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(output=[], output_text='Pronto')

    agent = Agent(settings, store, QueryMCP(), SimpleNamespace(responses=SimpleNamespace(create=respond)))
    request = RunRequest(prompt='Analise', query_ids=[item['id']])
    run = Run(id=str(uuid4()), conversation_id=str(uuid4()), prompt='Analise',
              status='running', created_at='', updated_at='')
    await agent.execute(run, request)
    content = captured[0]['input'][0]['content']
    assert 'ainda não executadas' in content
    assert item['sql'] in content
    assert item['id'] in content
    manager = RunManager(agent)
    with pytest.raises(AgentError, match='não existe'):
        manager.submit(RunRequest(prompt='Analise', query_ids=[uuid4()]))


def test_favorites_require_api_authorization(settings):
    from pydantic import SecretStr
    settings.app_api_key = SecretStr('test-api-key')
    with TestClient(create_app(settings, mcp=QueryMCP(), client=object())) as client:
        assert client.get('/api/queries').status_code == 401
        assert client.post('/api/queries', json=favorite()).status_code == 401
        assert client.get('/api/queries', headers={'Authorization': 'Bearer test-api-key'}).status_code == 200
