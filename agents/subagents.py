"""Subagentes só executam sob controle do principal e compartilham seu orçamento."""
import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from openai import APIError

from core.dashboard_identity import dashboard_owner
from core.history_identity import history_owner
from core.models import AgentError, Run, RunRequest
from repositories.local_store import now
from repositories.task_context import capture_context
from repositories.workspaces import Workspaces

CONTROL_TOOLS = {'create_subagent', 'list_subagents', 'delegate_to_subagent',
                 'delegate_to_subagents', 'cancel_subagent', 'schedule_task', 'propose_schedule', 'set_conversation_title'}


@dataclass
class StepBudget:
    remaining: int

    def take(self, child=False):
        if self.remaining <= (1 if child else 0):
            raise AgentError('Orçamento de etapas esgotado; a síntese do principal foi preservada.')
        self.remaining -= 1


class SubagentControl:
    def __init__(self, agent, run, request, budget):
        self.agent, self.run, self.request, self.budget = agent, run, request, budget
        self.repo = Workspaces(agent.store)

    def list(self):
        fields = ('id', 'name', 'instructions', 'status', 'task', 'run_id')
        return {'subagents': [{key: item[key] for key in fields}
                             for item in self.repo.list_subagents(self.run.conversation_id)
                             if item.get('created_by', 'principal') == 'principal'], 'limit': 2}

    def create(self, args):
        return self.repo.create_subagent(self.run.conversation_id, args)

    def schedule(self, args):
        return self.repo.schedule(self.run.conversation_id,
                                  args.model_copy(update={'source_run_id': UUID(self.run.id)}), dashboard_owner.get())

    def propose_schedule(self, args):
        return {**args.model_dump(mode='json'), 'kind': 'schedule_proposal',
                'source_run_id': self.run.id, 'conversation_id': self.run.conversation_id,
                'status': 'proposed', 'requires_confirmation': True}

    async def cancel(self, args):
        return {'cancelled': self.agent.cancel_subagent(self.run.conversation_id, str(args.subagent_id))}

    async def delegate_many(self, args):
        if len({item.subagent_id for item in args.assignments}) != len(args.assignments):
            raise AgentError('Escolha subagentes diferentes para as tarefas em paralelo.')
        results = await asyncio.gather(*(self.delegate(item) for item in args.assignments), return_exceptions=True)
        return {'results': [result if isinstance(result, dict) else
                            {'error': str(result) if isinstance(result, AgentError) else 'Falha no subagente.'}
                            for result in results]}

    async def delegate(self, args):
        profile = self.repo.get_subagent(self.run.conversation_id, str(args.subagent_id))
        if not profile:
            raise AgentError('Subagente não encontrado nesta sessão.')
        if profile.get('created_by', 'principal') == 'user':
            raise AgentError('Este subagente foi criado pelo usuário e tem conversa própria. Use um auxiliar do principal.')
        key = (history_owner.get(), self.run.conversation_id, profile['id'])
        if key in self.agent.active_subagents:
            raise AgentError('Este subagente já está executando uma tarefa.')
        if self.budget.remaining <= 1:
            raise AgentError('Não há etapas disponíveis para delegar; finalize a síntese.')
        child = Run(id=str(uuid4()), parent_run_id=self.run.id,
                    conversation_id=self.run.conversation_id, title=self.run.title, prompt=args.task,
                    status='running', created_at=now(), updated_at=now())
        child.context_snapshot = capture_context(self.agent.store, self.run.conversation_id, current_run=self.run)
        child.execution_options = self.run.execution_options.model_copy(deep=True)
        profile = {**profile, 'status': 'running', 'task': args.task, 'answer': '', 'error': None,
                   'run_id': child.id}
        self.repo.save_subagent(profile)
        self.agent.store.save_run(child)
        self.agent.event(self.run, 'subagent_start', f"{profile['name']}: tarefa iniciada.",
                         subagent_id=profile['id'])

        async def work():
            await self.agent.execute(child, RunRequest(prompt=args.task,
                web_search_enabled=self.request.web_search_enabled,
                dataset_ids=child.context_snapshot.get('dataset_ids', []), query_ids=self.request.query_ids),
                budget=self.budget, role_instructions=profile['instructions'])

        task = asyncio.create_task(work())
        self.agent.active_subagents[key] = task
        try:
            await task
            child.status = 'completed'
        except asyncio.CancelledError:
            child.status = 'cancelled'
            if asyncio.current_task().cancelling():
                raise
        except (AgentError, APIError) as exc:
            child.status = 'failed'
            child.error = str(exc) if isinstance(exc, AgentError) else 'Falha no provedor de IA do subagente.'
        except Exception:
            child.status = 'failed'
            child.error = 'Falha interna no subagente; o principal pode continuar com as evidências disponíveis.'
        finally:
            self.agent.active_subagents.pop(key, None)
            self.agent.store.save_run(child)
            known = {item['id'] for item in self.run.artifacts}
            self.run.artifacts.extend(item for item in child.artifacts if item['id'] not in known)
            profile.update(status=child.status, answer=child.answer, error=child.error)
            self.repo.save_subagent(profile)
            self.agent.event(self.run, 'subagent_result', f"{profile['name']}: {child.status}.",
                             subagent_id=profile['id'], run_id=child.id)
        return {'subagent_id': profile['id'], 'status': child.status, 'answer': child.answer,
                'error': child.error, 'artifacts': child.artifacts,
                'evidence': [event.get('result') for event in child.events if event['kind'] == 'tool_result'][-8:]}
