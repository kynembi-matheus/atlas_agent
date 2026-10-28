from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agents.orchestrator import Agent
from api.main import create_app
from core.models import AgentError, Run, RunRequest
from integrations.web_search import search_web
from repositories.local_store import now


def test_status_identifies_the_loaded_search_provider(settings):
    settings.internet_search_model = 'configured-web-model'
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        status = client.get('/api/status').json()
        assert status['internet_search_provider'] == 'openai'
        assert status['internet_search_model'] == 'configured-web-model'


def result(*, completed=True, sources=True):
    payload = {'output': [
        {'type': 'web_search_call', 'status': 'completed' if completed else 'failed',
         'action': {'sources': [{'url': 'https://example.org/'}] if sources else []}},
        {'type': 'message', 'content': [{'annotations': [{'type': 'url_citation',
          'url': 'https://example.org/', 'title': 'Fonte oficial'}] if sources else []}]},
    ]}
    return SimpleNamespace(output_text='Síntese com fonte.', model_dump=lambda: payload)


async def test_hosted_search_requires_real_search_and_keeps_sources(settings):
    create = AsyncMock(return_value=result())
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    response = await search_web(client, settings, 'Consulta pública', 3)
    assert response['results'] == [{'url': 'https://example.org/', 'title': 'Fonte oficial'}]
    assert response['provider'] == 'OpenAI web_search'
    request = create.call_args.kwargs
    assert request['store'] is False
    assert request['tool_choice'] == 'required'
    assert request['input'] == 'Consulta pública'
    assert request['model'] == settings.openai_model
    assert request['tools'][0]['type'] == 'web_search'


@pytest.mark.parametrize('completed,sources', [(False, True), (True, False)])
async def test_unverified_search_cannot_be_reported_as_success(settings, completed, sources):
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
        return_value=result(completed=completed, sources=sources))))
    with pytest.raises(AgentError):
        await search_web(client, settings, 'Consulta', 2)


async def test_search_failure_removes_tool_and_prevents_network_retries(settings, store):
    import json

    run = Run(id='test-web', conversation_id='test-conversation', prompt='Pesquise',
              status='running', created_at=now(), updated_at=now())
    requests = []
    class Client:
        def __init__(self):
            self.responses = self
        async def create(self, **kwargs):
            requests.append(kwargs)
            if kwargs['tools'][0]['type'] == 'web_search':
                return result(completed=False)
            if len(requests) == 1:
                return SimpleNamespace(output=[SimpleNamespace(type='function_call',
                    name='search_web', arguments=json.dumps({'query': 'Consulta pública'}),
                    call_id='search')], output_text='')
            assert 'search_web' not in {tool['name'] for tool in kwargs['tools']}
            return SimpleNamespace(output=[], output_text='A pesquisa ficou indisponível.')
    await Agent(settings, store, None, Client()).execute(run, RunRequest(prompt='Pesquise',
                                                                         web_search_enabled=True))
    assert len(requests) == 3
    assert 'indisponível' in run.answer
