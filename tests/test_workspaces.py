import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agents.orchestrator import Agent, RunManager
from agents.scheduler import Scheduler
from agents.subagents import CONTROL_TOOLS
from api.main import create_app
from core.history_identity import history_owner
from core.models import AgentError, RunRequest
from core.schedule_recurrence import next_occurrence
from core.workspace_models import CreateSubagent, DelegateTask, ScheduleTask
from repositories.workspaces import Workspaces
from tools.data_tools import Toolbox


@pytest.fixture
def owner():
    token = history_owner.set('owner-a')
    try:
        yield
    finally:
        history_owner.reset(token)


class LLM:
    def __init__(self):
        self.responses = self
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if 'Especialidade:' in kwargs['instructions']:
            assert not CONTROL_TOOLS & {tool['name'] for tool in kwargs['tools']}
            return SimpleNamespace(output=[], output_text='Evidência do auxiliar.')
        return SimpleNamespace(output=[], output_text='Síntese do principal.')


def schedule_args():
    return ScheduleTask(title='Resumo diário', prompt='Prepare um resumo dos indicadores.',
                        run_at=datetime.now(UTC) + timedelta(hours=1))


def test_recurrence_preserves_local_time_and_skips_missed_days():
    item = {'run_at': '2026-03-07T14:00:00+00:00', 'frequency': 'daily', 'timezone': 'America/New_York'}
    assert next_occurrence(item, datetime.fromisoformat('2026-03-07T14:01:00+00:00')) == '2026-03-08T13:00:00+00:00'
    item.update(frequency='weekly', weekdays=[0, 4], timezone='UTC')
    assert next_occurrence(item, datetime.fromisoformat('2026-03-10T15:00:00+00:00')) == '2026-03-13T14:00:00+00:00'


def test_recurring_schedule_rearms_once_and_cancel_prevents_resurrection(store, owner):
    repo = Workspaces(store)
    item = repo.schedule(repo.reserve(), schedule_args().model_copy(update={'frequency': 'daily'}), None)
    repo.finish_schedule(item, 'completed')
    next_item = repo.list_schedules()[0]
    assert next_item['status'] == 'pending'
    assert next_item['run_id'] != item['run_id']
    assert next_item['last_run_id'] == item['run_id']
    repo.finish_schedule(item, 'completed')
    assert repo.list_schedules()[0]['run_id'] == next_item['run_id']
    assert repo.cancel_schedule(item['id'])
    repo.finish_schedule(next_item, 'completed')
    assert repo.list_schedules()[0]['status'] == 'cancelled'


def test_weekly_schedule_requires_days_matching_start():
    args = schedule_args().model_dump()
    with pytest.raises(ValidationError):
        ScheduleTask(**{**args, 'frequency': 'weekly', 'weekdays': []})


def test_schedule_requires_future_timezone_and_subagent_limit_is_atomic(store, owner):
    with pytest.raises(ValidationError):
        ScheduleTask(title='Teste', prompt='Teste válido', run_at='2000-01-01T10:00:00Z')
    with pytest.raises(ValidationError):
        ScheduleTask(title='Teste', prompt='Teste válido', run_at='2099-01-01T10:00:00')
    repo = Workspaces(store)
    key = repo.reserve()

    def create(index):
        token = history_owner.set('owner-a')
        try:
            return repo.create_subagent(key, CreateSubagent(name=f'Auxiliar {index}', instructions='Avalie os indicadores.'))
        except AgentError:
            return None
        finally:
            history_owner.reset(token)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(item is not None for item in pool.map(create, range(4))) == 2
    assert len(repo.list_subagents(key)) == 2


async def test_two_subagents_return_to_principal_and_do_not_pollute_history(settings, store, owner):
    repo = Workspaces(store)
    key = repo.reserve()
    profiles = [repo.create_subagent(key, CreateSubagent(name=f'Auxiliar {index}', instructions='Avalie os indicadores.')) for index in range(2)]
    llm = LLM()
    manager = RunManager(Agent(settings, store, None, llm))
    run = manager.submit(RunRequest(prompt='Compare as evidências.', conversation_id=key,
        subagent_tasks=[DelegateTask(subagent_id=item['id'], task='Avalie o indicador.') for item in profiles]))
    await manager.tasks[run.id]
    finished = store.get_run(run.id)
    assert finished.status == 'completed'
    assert finished.answer == 'Síntese do principal.'
    assert len(llm.calls) == 3
    assert all(item['status'] == 'completed' for item in repo.list_subagents(key))
    assert [item.id for item in store.list_runs()] == [run.id]
    assert [item.id for item in store.conversation(key)] == [run.id]
    assert 'Evidência do auxiliar' in str(llm.calls[-1]['input'])
    assert any(event.get('tool') == 'delegate_to_subagents' and event['kind'] == 'tool_result'
               for event in finished.events)
    assert not manager.agent.active_subagents


async def test_shared_budget_reserves_main_synthesis_and_children_cannot_delegate(settings, store, owner):
    settings.max_agent_steps = 2
    repo = Workspaces(store); key = repo.reserve()
    profile = repo.create_subagent(key, CreateSubagent(name='Auxiliar', instructions='Avalie os indicadores.'))
    llm = LLM(); manager = RunManager(Agent(settings, store, None, llm))
    run = manager.submit(RunRequest(prompt='Resuma.', conversation_id=key,
        subagent_tasks=[DelegateTask(subagent_id=profile['id'], task='Verifique o tema.')]))
    await manager.tasks[run.id]
    assert len(llm.calls) == 2
    assert llm.calls[-1]['tools'] == []
    assert store.get_run(run.id).status == 'completed'
    with pytest.raises(AgentError):
        await Toolbox(settings, store, None, run, is_subagent=True).call('create_subagent',
            {'name': 'Proibido', 'instructions': 'Crie outro auxiliar.'})


async def test_cancelling_subagent_keeps_main_alive(settings, store, owner):
    started = asyncio.Event()
    class WaitingLLM(LLM):
        async def create(self, **kwargs):
            if 'Especialidade:' in kwargs['instructions']:
                started.set(); await asyncio.Event().wait()
            return await super().create(**kwargs)
    repo = Workspaces(store); key = repo.reserve()
    profile = repo.create_subagent(key, CreateSubagent(name='Auxiliar', instructions='Avalie o tema.'))
    manager = RunManager(Agent(settings, store, None, WaitingLLM()))
    run = manager.submit(RunRequest(prompt='Resuma.', conversation_id=key,
        subagent_tasks=[DelegateTask(subagent_id=profile['id'], task='Verifique o tema.')]))
    await asyncio.wait_for(started.wait(), 2)
    assert manager.agent.cancel_subagent(key, profile['id'])
    await manager.tasks[run.id]
    assert store.get_run(run.id).status == 'completed'
    assert repo.get_subagent(key, profile['id'])['status'] == 'cancelled'


async def test_parallel_subagents_are_cancelled_with_the_principal(settings, store, owner):
    both_started = asyncio.Event()
    active = []
    class WaitingLLM(LLM):
        async def create(self, **kwargs):
            active.append(kwargs)
            if len(active) == 2:
                both_started.set()
            await asyncio.Event().wait()
    repo = Workspaces(store); key = repo.reserve()
    profiles = [repo.create_subagent(key, CreateSubagent(name=f'Auxiliar {i}', instructions='Avalie o tema.')) for i in range(2)]
    manager = RunManager(Agent(settings, store, None, WaitingLLM()))
    run = manager.submit(RunRequest(prompt='Verifique em paralelo.', conversation_id=key,
        subagent_tasks=[DelegateTask(subagent_id=profile['id'], task='Verifique o tema.') for profile in profiles]))
    await asyncio.wait_for(both_started.wait(), 2)
    assert len(manager.agent.active_subagents) == 2
    await manager.cancel(run.id)
    assert store.get_run(run.id).status == 'cancelled'
    assert not manager.agent.active_subagents
    assert all(item['status'] == 'cancelled' for item in repo.list_subagents(key))


async def test_scheduler_dispatches_once_as_owner_and_restores_after_restart(settings, store, owner, monkeypatch):
    repo = Workspaces(store); key = repo.reserve()
    item = repo.schedule(key, schedule_args(), None)
    llm = LLM(); manager = RunManager(Agent(settings, store, None, llm)); scheduler = Scheduler(manager)
    assert repo.due() == []
    monkeypatch.setattr('repositories.workspaces.now', lambda: (datetime.now(UTC) + timedelta(hours=2)).isoformat())
    await scheduler.tick()
    await asyncio.gather(*list(manager.tasks.values()))
    await asyncio.gather(*list(scheduler.waiters))
    assert repo.list_schedules()[0]['status'] == 'completed'
    await scheduler.tick()
    assert len(llm.calls) == 1
    assert len(store.list_runs()) == 1
    repo.finish_schedule(item, 'dispatching')
    repo.recover_schedules()
    assert repo.list_schedules()[0]['status'] == 'completed'
    await scheduler.tick(); assert len(llm.calls) == 1
    await scheduler.close(); await manager.close()


def test_workspace_api_is_private_and_enforces_limit(settings):
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        key = client.post('/api/workspaces', json={}).json()['conversation_id']
        first = client.post(f'/api/workspaces/{key}/subagents', json={'name': 'Indicadores', 'instructions': 'Avalie os indicadores.'})
        assert first.status_code == 201
        assert client.post(f'/api/workspaces/{key}/subagents', json={'name': 'Revisor', 'instructions': 'Revise as evidências.'}).status_code == 201
        assert client.post(f'/api/workspaces/{key}/subagents', json={'name': 'Terceiro', 'instructions': 'Não deve criar.'}).status_code == 409
        item = client.post(f'/api/workspaces/{key}/schedules', json=schedule_args().model_dump(mode='json'))
        assert item.status_code == 201
        task_id = item.json()['id']
        cookie = client.cookies.get('scd-dashboard-profile')
        client.cookies.clear()
        assert client.get(f'/api/workspaces/{key}/subagents').status_code == 404
        assert client.post('/api/workspaces', json={'conversation_id': key}).status_code == 404
        assert client.get('/api/schedules').json()['schedules'] == []
        assert client.post(f'/api/schedules/{task_id}/cancel').status_code == 404
        client.cookies.clear(); client.cookies.set('scd-dashboard-profile', cookie)
        assert client.post(f'/api/schedules/{task_id}/cancel').status_code == 200
        assert client.get('/api/schedules').json()['schedules'][0]['status'] == 'cancelled'


def test_temporary_imports_cannot_be_scheduled(settings, store, owner, tmp_path):
    from repositories.temporary_store import TemporaryStore
    temporary = TemporaryStore(store, tmp_path / 'sessions', str(uuid4()))
    key = Workspaces(store).reserve()
    temporary.save_dataset([{'valor': 1}], {'kind': 'temporary_import'})
    with pytest.raises(AgentError, match='temporárias'):
        Workspaces(temporary).schedule(key, schedule_args(), None)
    profile = Workspaces(temporary).create_subagent(key, CreateSubagent(name='Auxiliar', instructions='Avalie o arquivo.'))
    assert Workspaces(store).get_subagent(key, profile['id']) is None
    temporary.close()


def test_profile_slots_are_shared_between_persistent_and_temporary_stores(store, owner, tmp_path):
    from repositories.temporary_store import TemporaryStore
    repo = Workspaces(store); key = repo.reserve()
    args = CreateSubagent(name='Auxiliar', instructions='Avalie os dados.')
    repo.create_subagent(key, args)
    temporary = TemporaryStore(store, tmp_path / 'sessions', str(uuid4()))
    Workspaces(temporary).create_subagent(key, args)
    with pytest.raises(AgentError, match='dois subagentes'):
        repo.create_subagent(key, args)
    temporary.close()
    repo.create_subagent(key, args)
    assert len(repo.list_subagents(key)) == 2
