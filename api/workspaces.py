"""Rotas privadas de agendamento e subagentes da sessão."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agents.schedule_planner import plan_schedule
from core.dashboard_identity import dashboard_owner
from core.models import AgentError, RunRequest
from core.workspace_models import (
    ContextualDelegateRequest,
    CreateSubagent,
    SchedulePlanRequest,
    ScheduleTask,
    StartSubagent,
    WorkspaceRequest,
)
from repositories.task_context import capture_context
from repositories.workspaces import Workspaces
from repositories.session_views import session_groups


def workspace_router(app, authorize, import_session):
    router = APIRouter(prefix='/api', dependencies=[Depends(authorize)], tags=['Sessões'])
    session_dependency = Depends(import_session)

    def store_for(session):
        if session and (session.store.datasets or session.store.runs):
            return session.store
        return app.state.store

    def require(conversation_id, session):
        store = store_for(session)
        repo = Workspaces(store)
        if not repo.owns(conversation_id) and not store.conversation(conversation_id, 1):
            raise HTTPException(404, 'Sessão não encontrada.')
        return store, repo

    @router.post('/workspaces', status_code=201)
    async def reserve(request: WorkspaceRequest, session=session_dependency):
        if request.conversation_id:
            key = str(request.conversation_id)
            require(key, session)
        else:
            key = Workspaces(app.state.store).reserve()
        return {'conversation_id': key}

    @router.get('/workspaces/{conversation_id}/subagents')
    async def list_subagents(conversation_id: UUID, session=session_dependency):
        _, repo = require(str(conversation_id), session)
        return {'subagents': repo.list_subagents(str(conversation_id)), 'limit': 2}

    @router.get('/workspace-sessions')
    async def list_session_groups(limit: int | None = Query(default=None, ge=1, le=500), session=session_dependency):
        return session_groups(store_for(session), limit)

    @router.get('/workspaces/{conversation_id}/context')
    async def execution_context(conversation_id: UUID, source_run_id: UUID | None = None,
                                session=session_dependency):
        store, _ = require(str(conversation_id), session)
        try:
            context = capture_context(store, str(conversation_id), source_run_id)
            return {'source_run_id': context.get('source_run_id'), 'title': context.get('title'),
                    'request': context.get('request', ''), 'status': context.get('source_status'),
                    'dataset_count': len(context.get('dataset_ids', [])),
                    'query_count': len(context.get('options', {}).get('query_ids', [])),
                    'web_search_enabled': context.get('options', {}).get('web_search_enabled', False),
                    'output_format': context.get('options', {}).get('output_format', 'auto'),
                    'warnings': context.get('warnings', [])}
        except AgentError:
            raise HTTPException(404, 'Contexto da execução não encontrado nesta sessão.') from None

    @router.post('/workspaces/{conversation_id}/subagents', status_code=201)
    async def create_subagent(conversation_id: UUID, request: CreateSubagent, session=session_dependency):
        _, repo = require(str(conversation_id), session)
        try:
            return repo.create_subagent(str(conversation_id), request, created_by='user')
        except AgentError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post('/workspaces/{conversation_id}/delegate', status_code=202)
    async def delegate(conversation_id: UUID, request: ContextualDelegateRequest, web_search_enabled: bool = False,
                       session=session_dependency):
        store, repo = require(str(conversation_id), session)
        profile = repo.get_subagent(str(conversation_id), str(request.subagent_id))
        if not profile:
            raise HTTPException(404, 'Subagente não encontrado.')
        if profile.get('created_by', 'principal') == 'user':
            raise HTTPException(409, 'Use a conversa própria do subagente criado pelo usuário.')
        manager = session.manager if session and store is session.store else app.state.manager
        try:
            context = capture_context(store, str(conversation_id), request.source_run_id)
            options = context.get('options', {})
            return manager.submit(RunRequest(prompt=request.task, conversation_id=conversation_id,
                                  subagent_tasks=[request], web_search_enabled=request.web_search_enabled if request.web_search_enabled is not None else options.get('web_search_enabled', web_search_enabled),
                                  dataset_ids=context.get('dataset_ids', []), query_ids=options.get('query_ids', [])),
                                  context_snapshot=context)
        except AgentError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post('/workspaces/{conversation_id}/subagents/{subagent_id}/run', status_code=202)
    async def run_user_agent(conversation_id: UUID, subagent_id: UUID, request: ContextualDelegateRequest,
                             session=session_dependency):
        store, repo = require(str(conversation_id), session)
        profile = repo.get_subagent(str(conversation_id), str(subagent_id))
        if not profile or profile.get('created_by', 'principal') != 'user':
            raise HTTPException(404, 'Subagente do usuário não encontrado.')
        if request.subagent_id != subagent_id:
            raise HTTPException(422, 'Identificador de subagente inconsistente.')
        manager = session.manager if session and store is session.store else app.state.manager
        try:
            context = capture_context(store, str(conversation_id), request.source_run_id)
            options = context.get('options', {})
            datasets = list(dict.fromkeys([*context.get('dataset_ids', []), *(str(x) for x in request.dataset_ids)]))
            queries = list(dict.fromkeys([*options.get('query_ids', []), *(str(x) for x in request.query_ids)]))
            if len(datasets) > 10 or len(queries) > 10:
                raise AgentError('Selecione no máximo dez fontes e dez consultas para a tarefa.')
            return manager.submit(RunRequest(prompt=request.task,
                conversation_id=profile['independent_conversation_id'],
                output_format=request.output_format, dataset_ids=datasets, query_ids=queries,
                web_search_enabled=request.web_search_enabled if request.web_search_enabled is not None else options.get('web_search_enabled', False)), context_snapshot=context, profile=profile)
        except AgentError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post('/workspaces/{conversation_id}/subagents/execute', status_code=202)
    async def execute_new_subagent(conversation_id: UUID, request: StartSubagent,
                                   session=session_dependency):
        _, repo = require(str(conversation_id), session)
        profile = None
        try:
            profile = repo.create_subagent(str(conversation_id), CreateSubagent(
                name='Agente', instructions='Execute a tarefa do usuário usando o contexto e as fontes da sessão.'),
                created_by='user')
            return await run_user_agent(conversation_id, UUID(profile['id']),
                ContextualDelegateRequest(subagent_id=profile['id'], **request.model_dump()), session)
        except AgentError as exc:
            if profile:
                repo.discard_unstarted_subagent(profile)
            raise HTTPException(409, str(exc)) from None
        except HTTPException:
            if profile:
                repo.discard_unstarted_subagent(profile)
            raise

    @router.post('/workspaces/{conversation_id}/subagents/{subagent_id}/cancel')
    async def cancel_subagent(conversation_id: UUID, subagent_id: UUID, session=session_dependency):
        store, repo = require(str(conversation_id), session)
        profile = repo.get_subagent(str(conversation_id), str(subagent_id))
        if not profile:
            raise HTTPException(404, 'Subagente não encontrado.')
        manager = session.manager if session and store is session.store else app.state.manager
        if profile.get('created_by') == 'user':
            run = store.get_run(profile.get('run_id') or '')
            if not run or run.status not in {'queued', 'running'}:
                raise HTTPException(409, 'Este subagente não está executando uma tarefa.')
            await manager.cancel(run.id)
            return {'cancelled': True}
        if not manager.agent.cancel_subagent(str(conversation_id), str(subagent_id)):
            raise HTTPException(409, 'Este subagente não está executando uma tarefa.')
        return {'cancelled': True}

    @router.post('/workspaces/{conversation_id}/schedules/plan')
    async def prepare_schedule(conversation_id: UUID, request: SchedulePlanRequest, session=session_dependency):
        store, _ = require(str(conversation_id), session)
        manager = session.manager if session and store is session.store else app.state.manager
        try:
            context = capture_context(store, str(conversation_id), request.source_run_id)
            selected_sources = []
            for key in request.dataset_ids:
                dataset = store.get_dataset(str(key))
                if dataset is None:
                    raise AgentError('Uma fonte selecionada não está disponível.')
                selected_sources.append(dataset['source'])
            query_store = getattr(store, 'persistent', store)
            if any(query_store.get_query(str(key)) is None for key in request.query_ids):
                raise AgentError('Uma consulta selecionada não está disponível.')
            context['planning_options'] = request.model_dump(mode='json', exclude={'prompt', 'source_run_id'})
            context['selected_sources'] = selected_sources
            plan = await plan_schedule(manager.agent, request.prompt, context)
            return {**plan.model_dump(), 'prompt': request.prompt, 'source_run_id': context.get('source_run_id')}
        except AgentError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post('/workspaces/{conversation_id}/schedules', status_code=201)
    async def schedule(conversation_id: UUID, request: ScheduleTask, session=session_dependency):
        _, repo = require(str(conversation_id), session)
        try:
            return repo.schedule(str(conversation_id), request, dashboard_owner.get())
        except AgentError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.get('/schedules')
    async def list_schedules():
        return {'schedules': Workspaces(app.state.store).list_schedules()}

    @router.post('/schedules/{schedule_id}/cancel')
    async def cancel_schedule(schedule_id: UUID):
        if not Workspaces(app.state.store).cancel_schedule(str(schedule_id)):
            raise HTTPException(404, 'Agendamento pendente não encontrado.')
        return {'cancelled': True}

    return router
