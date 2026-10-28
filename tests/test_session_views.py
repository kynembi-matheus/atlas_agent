from uuid import uuid4

from core.history_identity import history_owner
from core.models import Run
from core.workspace_models import CreateSubagent
from repositories.session_views import session_groups
from repositories.workspaces import Workspaces
from fastapi.testclient import TestClient
from api.main import create_app


def test_groups_user_and_principal_agents_and_limits_sessions(store):
    token = history_owner.set('owner')
    try:
        repo = Workspaces(store)
        origin = repo.reserve()
        parent = Run(id=str(uuid4()), conversation_id=origin, title='Carteira', prompt='Analise', status='completed',
                     created_at='2026-10-28T10:00:00Z', updated_at='2026-10-28T10:00:00Z')
        store.save_run(parent)
        for creator in ['user', 'principal']:
            profile = repo.create_subagent(origin, CreateSubagent(name='Agente', instructions='Confira os dados'), created_by=creator)
            child = parent.model_copy(update={'id': str(uuid4()), 'agent_profile_id': profile['id'],
                'origin_conversation_id': origin if creator == 'user' else None,
                'conversation_id': profile['independent_conversation_id'] or origin,
                'parent_run_id': parent.id if creator == 'principal' else None, 'status': 'running'})
            store.save_run(child)
            repo.save_subagent({**profile, 'run_id': child.id})
        groups = session_groups(store, 1)
        assert len(groups) == 1
        assert groups[0]['id'] == parent.id
        assert {agent['color'] for agent in groups[0]['subagents']} == {'teal', 'violet'}
        assert all(agent['run_id'] and agent['status'] == 'running' for agent in groups[0]['subagents'])
        history_owner.set('another-owner')
        assert session_groups(store) == []
    finally:
        history_owner.reset(token)


def test_delegation_without_main_execution_has_one_group(store):
    token = history_owner.set('owner')
    try:
        repo = Workspaces(store)
        origin = repo.reserve()
        profile = repo.create_subagent(origin, CreateSubagent(name='Agente', instructions='Confira os dados'), created_by='user')
        child = Run(id=str(uuid4()), conversation_id=profile['independent_conversation_id'],
                    origin_conversation_id=origin, agent_profile_id=profile['id'], prompt='Confira', status='completed',
                    context_snapshot={'title': 'Análise mensal'}, created_at='2026-10-28T10:00:00Z', updated_at='2026-10-28T10:00:00Z')
        store.save_run(child)
        repo.save_subagent({**profile, 'run_id': child.id})
        group, = session_groups(store)
        assert group['id'] is None
        assert group['conversation_id'] == origin
        assert group['title'] == 'Análise mensal'
        assert group['subagents'][0]['run_id'] == child.id
    finally:
        history_owner.reset(token)


def test_session_groups_api_is_scoped_and_limits_groups(settings, client_owner_scope):
    app = create_app(settings, mcp=object(), client=object())
    with TestClient(app) as client:
        with client_owner_scope(client):
            repo = Workspaces(app.state.store)
            for day in [1, 2]:
                origin = repo.reserve()
                parent = Run(id=str(uuid4()), conversation_id=origin, title=f'Sessão {day}',
                             prompt='Analise', status='completed', created_at=f'2026-10-0{day}T10:00:00Z', updated_at='2026-10-28T10:00:00Z')
                app.state.store.save_run(parent)
                repo.create_subagent(origin, CreateSubagent(name='Agente', instructions='Confira dados'))
        result = client.get('/api/workspace-sessions?limit=1')
        assert result.status_code == 200
        assert len(result.json()) == 1
        assert result.json()[0]['title'] == 'Sessão 2'
        assert len(result.json()[0]['subagents']) == 1
        assert client.get('/api/workspace-sessions?limit=0').status_code == 422
        client.cookies.clear()
        assert client.get('/api/workspace-sessions').json() == []
