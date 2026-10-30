"""Agendamentos persistentes; recupera disparos interrompidos sem duplicar o run."""
import asyncio
from contextlib import suppress

from core.dashboard_identity import dashboard_owner
from core.history_identity import history_owner
from core.models import AgentError, RunRequest
from repositories.token_usage import QuotaError
from repositories.workspaces import Workspaces


class Scheduler:
    def __init__(self, manager):
        self.manager = manager
        self.repo = Workspaces(manager.store)
        self.waiters = set()

    async def tick(self):
        for owner, profile, item in self.repo.due():
            user_token = history_owner.set(owner)
            dashboard_token = dashboard_owner.set(profile)
            try:
                run = self.manager.store.get_run(item['run_id'])
                if run is None:
                    context = item.get('context_snapshot', {})
                    ids = context.get('dataset_ids', [])
                    if any(self.manager.store.get_dataset(key) is None for key in ids):
                        self.repo.finish_schedule(item, 'failed', 'Uma fonte do contexto agendado não está mais disponível.')
                        continue
                    if any(self.manager.store.get_query(str(key)) is None for key in item['query_ids']):
                        self.repo.finish_schedule(item, 'failed', 'Uma consulta do contexto agendado não está mais disponível.')
                        continue
                    prompt = item['prompt']
                    if item.get('plan_steps'):
                        context = {**context, 'approved_plan': item['plan_steps']}
                    request = RunRequest(prompt=prompt, conversation_id=item['conversation_id'],
                                         query_ids=item['query_ids'], dataset_ids=ids,
                                         output_format=item.get('output_format', 'auto'),
                                         web_search_enabled=item['web_search_enabled'])
                    profile = self.repo.user_agent_for(item['conversation_id'])
                    run = self.manager.submit(request, run_id=item['run_id'], context_snapshot=context, profile=profile)
                self.repo.finish_schedule(item, run.status if run.status not in {'queued', 'running'} else 'running')
                job = self.manager.tasks.get(run.id)
                if job:
                    waiter = asyncio.create_task(self.finish(item, job))
                    self.waiters.add(waiter)
                    waiter.add_done_callback(self.waiters.discard)
            except QuotaError as exc:
                self.repo.finish_schedule(item, 'failed', str(exc))
            except AgentError:
                self.repo.finish_schedule(item, 'pending', 'Aguardando disponibilidade da fila ou configuração da IA.')
            finally:
                dashboard_owner.reset(dashboard_token)
                history_owner.reset(user_token)

    async def finish(self, item, job):
        with suppress(asyncio.CancelledError):
            await asyncio.shield(job)
        run = self.manager.store.get_run(item['run_id'])
        if run:
            self.repo.finish_schedule(item, run.status, run.error)

    async def serve(self):
        self.repo.recover_schedules()
        while True:
            await self.tick()
            await asyncio.sleep(5)

    async def close(self):
        for task in list(self.waiters):
            task.cancel()
        await asyncio.gather(*self.waiters, return_exceptions=True)
