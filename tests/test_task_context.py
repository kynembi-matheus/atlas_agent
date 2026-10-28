import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agents.orchestrator import Agent, RunManager
from agents.scheduler import Scheduler
from agents.subagents import StepBudget, SubagentControl
from api.main import create_app
from core.history_identity import history_owner
from core.models import AgentError, Run, RunRequest
from core.workspace_models import CreateSubagent, DelegateTask, ProposeSchedule, ScheduleTask
from repositories.local_store import now
from repositories.task_context import capture_context
from repositories.workspaces import Workspaces


@pytest.fixture
def owner():
    token = history_owner.set('context-owner')
    try:
        yield
    finally:
        history_owner.reset(token)


def source_run(store, conversation_id):
    dataset = store.save_dataset([{'saldo': 100}], {'kind': 'postgresql', 'database': 'cora',
        'sql': 'SELECT saldo FROM carteira WHERE numero_pa = 7', 'max_rows': 10,
        'possibly_truncated': True})
    run = Run(id=str(uuid4()), conversation_id=conversation_id, prompt='Analise a carteira do PA 7.',
        title='Carteira do PA 7', status='completed', created_at=now(), updated_at=now(),
        answer='Amostra de referência.', execution_options={'dataset_ids': [dataset['id']],
        'web_search_enabled': True, 'output_format': 'dashboard'})
    store.save_run(run)
    return run, dataset


class LLM:
    def __init__(self):
        self.responses = self
        self.calls = []
    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output=[], output_text='Evidências conferidas.')


async def test_scheduled_run_keeps_source_context_sources_and_options(settings, store, owner, monkeypatch):
    repo = Workspaces(store); conversation = repo.reserve()
    source, dataset = source_run(store, conversation)
    item = repo.schedule(conversation, ScheduleTask(title='Repetir análise', prompt='Atualize os indicadores.',
        source_run_id=source.id, run_at=datetime.now(UTC) + timedelta(hours=1)), None)
    assert item['context_snapshot']['request'] == source.prompt
    assert item['context_snapshot']['data_sources'][0]['sql'].endswith('numero_pa = 7')
    assert item['web_search_enabled'] is True
    assert item['output_format'] == 'dashboard'
    assert item['context_snapshot']['dataset_ids'] == [dataset['id']]
    # A conversa posterior não substitui a execução escolhida no snapshot.
    unrelated = Run(id=str(uuid4()), conversation_id=conversation, prompt='Outro assunto.',
        status='completed', created_at=now(), updated_at=now())
    store.save_run(unrelated)
    llm = LLM(); manager = RunManager(Agent(settings, store, None, llm)); scheduler = Scheduler(manager)
    monkeypatch.setattr('repositories.workspaces.now', lambda: (datetime.now(UTC) + timedelta(hours=2)).isoformat())
    await scheduler.tick()
    await asyncio.gather(*list(manager.tasks.values()))
    await asyncio.gather(*list(scheduler.waiters))
    scheduled = store.get_run(item['run_id'])
    assert scheduled.context_snapshot['source_run_id'] == source.id
    assert scheduled.execution_options.dataset_ids[0].hex == dataset['id'].replace('-', '')
    assert 'numero_pa = 7' in str(llm.calls[0]['input'][0])
    assert 'Outro assunto' not in str(llm.calls[0]['input'][0])
    await scheduler.close()


async def test_delegation_gets_application_context_and_proposals_do_not_schedule(settings, store, owner):
    repo = Workspaces(store); conversation = repo.reserve()
    source, _ = source_run(store, conversation)
    profile = repo.create_subagent(conversation, CreateSubagent(name='Revisor', instructions='Confira os limites da amostra.'))
    llm = LLM(); agent = Agent(settings, store, None, llm)
    control = SubagentControl(agent, source, RunRequest(prompt=source.prompt, web_search_enabled=True), StepBudget(6))
    proposal = control.propose_schedule(ProposeSchedule(title='Rever a carteira',
        prompt='Atualize os mesmos indicadores.', reason='Acompanhar mudanças.'))
    assert proposal['kind'] == 'schedule_proposal' and proposal['requires_confirmation'] is True
    assert repo.list_schedules() == []
    result = await control.delegate(DelegateTask(subagent_id=profile['id'], task='Revise somente os limites da amostra.'))
    assert result['status'] == 'completed'
    assert 'Analise a carteira do PA 7.' in str(llm.calls[0]['input'])
    assert 'numero_pa = 7' in str(llm.calls[0]['input'])


def test_snapshot_cannot_read_another_users_execution(store, owner):
    repo = Workspaces(store); conversation = repo.reserve()
    other = history_owner.set('another-owner')
    try:
        foreign, _ = source_run(store, str(uuid4()))
    finally:
        history_owner.reset(other)
    with pytest.raises(AgentError, match='não está disponível'):
        capture_context(store, conversation, foreign.id)


def test_context_keeps_original_request_across_delegation(store, owner):
    conversation = Workspaces(store).reserve()
    source, _ = source_run(store, conversation)
    delegated = Run(id=str(uuid4()), conversation_id=conversation, prompt='Confira os limites.',
        status='running', created_at=now(), updated_at=now(),
        context_snapshot=capture_context(store, conversation, source.id))
    snapshot = capture_context(store, conversation, current_run=delegated)
    assert snapshot['request'] == delegated.prompt
    assert snapshot['origin_request'] == source.prompt
    assert snapshot['data_sources'][0]['sql'].endswith('numero_pa = 7')


async def test_schedule_in_user_conversation_preserves_persona(settings, store, owner, monkeypatch):
    repo = Workspaces(store)
    conversation = repo.reserve()
    profile = repo.create_subagent(conversation, CreateSubagent(name='Revisor pessoal',
        instructions='Explique os limites da amostra.'), created_by='user')
    source, _ = source_run(store, profile['independent_conversation_id'])
    item = repo.schedule(source.conversation_id, ScheduleTask(title='Revisar depois',
        prompt='Atualize a revisão.', source_run_id=source.id,
        run_at=datetime.now(UTC) + timedelta(hours=1)), None)
    llm = LLM()
    manager = RunManager(Agent(settings, store, None, llm))
    scheduler = Scheduler(manager)
    monkeypatch.setattr('repositories.workspaces.now', lambda: (datetime.now(UTC) + timedelta(hours=2)).isoformat())
    await scheduler.tick()
    await asyncio.gather(*list(manager.tasks.values()))
    await asyncio.gather(*list(scheduler.waiters))
    run = store.get_run(item['run_id'])
    assert run.agent_profile_id == profile['id']
    assert run.origin_conversation_id == conversation
    assert 'Especialidade: Explique os limites da amostra.' in llm.calls[0]['instructions']
    assert 'pelo usuário nesta conversa própria' in llm.calls[0]['instructions']
    await scheduler.close()


def test_user_agent_has_own_conversation_and_keeps_its_role_on_followup(settings):
    llm = LLM()
    with TestClient(create_app(settings, mcp=object(), client=llm)) as client:
        conversation = client.post('/api/workspaces', json={}).json()['conversation_id']
        source = client.post('/api/runs', json={'prompt': 'Analise os indicadores do PA 7.',
            'conversation_id': conversation}).json()
        profile = client.post(f'/api/workspaces/{conversation}/subagents', json={
            'name': 'Meu revisor', 'instructions': 'Confira os critérios e explique os limites.'}).json()
        assert profile['created_by'] == 'user'
        body = {'subagent_id': profile['id'], 'task': 'Confira apenas os critérios.', 'source_run_id': source['id']}
        assert client.post(f'/api/workspaces/{conversation}/delegate', json=body).status_code == 409
        response = client.post(f'/api/workspaces/{conversation}/subagents/{profile["id"]}/run', json=body)
        assert response.status_code == 202
        independent = response.json()
        assert independent['conversation_id'] != conversation
        assert independent['origin_conversation_id'] == conversation
        assert independent['agent_profile_id'] == profile['id']
        assert independent['parent_run_id'] is None
        for _ in range(20):
            result = client.get(f'/api/runs/{independent["id"]}').json()
            if result['status'] == 'completed':
                break
        assert result['status'] == 'completed'
        assert result['context_snapshot']['source_run_id'] == source['id']
        followup = client.post('/api/runs', json={'prompt': 'Explique melhor.',
            'conversation_id': independent['conversation_id']}).json()
        assert followup['agent_profile_id'] == profile['id']
        for _ in range(20):
            if client.get(f'/api/runs/{followup["id"]}').json()['status'] == 'completed':
                break
        assert 'Especialidade: Confira os critérios' in llm.calls[-1]['instructions']

def test_chat_creates_and_starts_agent_and_failed_start_releases_slot(settings):
    with TestClient(create_app(settings, mcp=object(), client=LLM())) as client:
        conversation = client.post('/api/workspaces', json={}).json()['conversation_id']
        path = f'/api/workspaces/{conversation}/subagents/execute'
        invalid = client.post(path, json={'task': 'Confira os dados.', 'dataset_ids': [str(uuid4())]})
        assert invalid.status_code == 409
        assert client.get(f'/api/workspaces/{conversation}/subagents').json()['subagents'] == []
        response = client.post(path, json={'task': 'Execute a tarefa escrita no chat.'})
        assert response.status_code == 202
        run = response.json()
        profiles = client.get(f'/api/workspaces/{conversation}/subagents').json()['subagents']
        assert len(profiles) == 1
        assert profiles[0]['run_id'] == run['id']
        assert run['prompt'] == 'Execute a tarefa escrita no chat.'
        for _ in range(30):
            result = client.get(f'/api/runs/{run["id"]}').json()
            if result['status'] == 'completed':
                break
        assert result['status'] == 'completed'

def test_schedule_plan_does_not_execute_or_schedule(settings):
    class Planner:
        def __init__(self):
            self.responses = self
            self.calls = []
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(output=[SimpleNamespace(type='function_call', name='devolver_plano',
                arguments='{"title":"Resumo futuro","steps":["Conferir fontes","Gerar resumo"]}')])
    llm = Planner()
    with TestClient(create_app(settings, mcp=object(), client=llm)) as client:
        conversation = client.post('/api/workspaces', json={}).json()['conversation_id']
        response = client.post(f'/api/workspaces/{conversation}/schedules/plan',
            json={'prompt': 'Prepare o resumo da carteira do PA 7.'})
        assert response.status_code == 200
        assert response.json()['prompt'] == 'Prepare o resumo da carteira do PA 7.'
        assert len(response.json()['steps']) == 2
        assert client.get('/api/schedules').json()['schedules'] == []
        assert client.get('/api/conversations').json() == []
        assert len(llm.calls) == 1
        assert [tool['name'] for tool in llm.calls[0]['tools']] == ['devolver_plano']
