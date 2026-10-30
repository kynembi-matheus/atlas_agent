from fastapi.testclient import TestClient
from api.main import create_app
from core.dashboard_identity import dashboard_owner
from tools.data_tools import Toolbox
from tools.sites import Site, Sites

async def test_public_site_and_owner_isolation(settings, store):
    token = dashboard_owner.set('owner-a')
    try:
        toolbox = Toolbox(settings, store, object(), None)
        result = await toolbox.call('create_site', {'title': '<script>alert(1)</script>', 'sections': [{'title': 'Info', 'text': 'Hello'}]})
    finally:
        dashboard_owner.reset(token)
    library = Sites(store)
    assert len(library.list('owner-a')) == 1
    assert library.list('owner-b') == []
    assert not library.delete('owner-b', result['id'])
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        response = client.get(result['url'])
        assert response.status_code == 200
        assert '&lt;script&gt;' in response.text and '<script>' not in response.text
        assert 'sandbox' in response.headers['content-security-policy']
        assert 'scd-dashboard-profile' not in response.cookies
    assert library.delete('owner-a', result['id'])
    assert library.get_public(result['id']) is None

async def test_sites_output_requests_static_page_without_dataset(settings, store):
    from agents.orchestrator import Agent
    from core.models import Run, RunRequest
    from types import SimpleNamespace
    from uuid import uuid4
    captured = []
    async def respond(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(output=[], output_text='Pronto')
    agent = Agent(settings, store, object(), SimpleNamespace(responses=SimpleNamespace(create=respond)))
    run = Run(id=str(uuid4()), conversation_id=str(uuid4()), prompt='Pagina sobre jovens e IA', status='running', created_at='', updated_at='')
    await agent.execute(run, RunRequest(prompt=run.prompt, output_format='sites'))
    instructions = captured[0]['input'][-1]['content']
    assert 'create_site' in instructions
    assert 'sem exigir dataset' in instructions
    assert 'create_dashboard' in instructions
    assert any(tool['name'] == 'create_site' for tool in captured[0]['tools'])
