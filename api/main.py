"""API FastAPI e aplicação web servidas pela mesma origem."""
import asyncio
import json
import logging
import re
import secrets
from contextlib import asynccontextmanager, suppress
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from agents.orchestrator import Agent, RunManager, make_client
from agents.scheduler import Scheduler
from api.auth import auth_router
from api.workspaces import workspace_router
from core.config import ROOT, Settings
from core.dashboard_identity import dashboard_owner
from core.history_identity import history_owner, identity_owner
from core.import_sessions import ImportSession, ImportSessions
from core.models import AgentError, LocalProfile, Run, RunRequest
from core.skill_catalog import available_skills
from integrations.file_imports import ImportFailure, import_file
from integrations.pg_mcp import PgMCP
from integrations.sso import SSO, Identity
from integrations.temporary_imports import infer_schema, normalize_tables, read_tables
from repositories.auth_sessions import COOKIE, AuthSessions
from repositories.dashboards import LIMIT, Dashboards
from repositories.local_store import Store
from repositories.workspaces import Workspaces
from tools.dashboards import Dashboard, RefreshStore, refresh
from tools.data_tools import (
    CATALOG_DATABASES,
    FavoriteQuery,
    PreviewTable,
    Toolbox,
    preview,
    table_entries,
    validate_sql,
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, mcp=None, client=None,
               development: bool = False) -> FastAPI:
    settings = settings or Settings()
    development_bypass = development and settings.environment.strip().lower() == 'development'
    sso = SSO(settings) if settings.sso_enabled else None
    auth_sessions = AuthSessions(settings.data_dir) if sso or development_bypass else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.data_dir)
        store.recover()
        llm = client if client is not None else make_client(settings)
        pg = mcp if mcp is not None else PgMCP(settings)
        app.state.store, app.state.mcp = store, pg
        app.state.manager = RunManager(Agent(settings, store, pg, llm))
        app.state.imports = ImportSessions(settings, store, pg, llm)
        app.state.llm = llm
        app.state.scheduler = Scheduler(app.state.manager)
        scheduler_task = asyncio.create_task(app.state.scheduler.serve())
        sweep = asyncio.create_task(app.state.imports.sweep())
        try:
            yield
        finally:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
            sweep.cancel()
            with suppress(asyncio.CancelledError):
                await sweep
            await app.state.imports.close()
            await app.state.manager.close()
            await app.state.scheduler.close()
            if client is None:
                await llm.close()

    app = FastAPI(title="Atlas Agent", version="0.1.0", lifespan=lifespan,
                  description="Análises e relatórios com ferramentas controladas e PostgreSQL via MCP.")

    app.include_router(auth_router(settings, sso, auth_sessions, development=development_bypass))

    async def authorize(request: Request, authorization: str | None = Header(default=None)):
        if auth_sessions:
            if not request.state.identity:
                raise HTTPException(401, 'Entre pelo ScdAuth para acessar a aplicação.')
            return
        expected = settings.app_api_key.get_secret_value()
        if expected and not secrets.compare_digest(authorization or "", f"Bearer {expected}"):
            raise HTTPException(401, "Chave de acesso inválida.", headers={"WWW-Authenticate": "Bearer"})

    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    async def import_session(x_data_session: Annotated[UUID | None, Header()] = None):
        if x_data_session is None:
            return None
        try:
            return app.state.imports.get(str(x_data_session))
        except AgentError as exc:
            raise HTTPException(410, str(exc)) from None

    Session = Annotated[ImportSession | None, Depends(import_session)]

    def scoped_store(session):
        return session.store if session else app.state.store

    def dashboard_library():
        return Dashboards(app.state.store)

    def owned_dashboard(key):
        item = dashboard_library().get(dashboard_owner.get(), str(key))
        if item is None:
            raise HTTPException(404, 'Dashboard não encontrado neste perfil.')
        return item

    @router.get('/dashboards', tags=['Dashboards'])
    async def list_dashboards():
        items = dashboard_library().list(dashboard_owner.get())
        return {'dashboards': [{k: item[k] for k in ('id', 'title', 'description', 'created_at')}
                               for item in items], 'limit': LIMIT, 'refresh_seconds': 60}

    @router.post('/dashboards', status_code=201, tags=['Dashboards'])
    async def create_dashboard(request: Dashboard, session: Session):
        try:
            return await Toolbox(settings, scoped_store(session), app.state.mcp, None).create_dashboard(request)
        except AgentError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.delete('/dashboards/{dashboard_id}', status_code=204, tags=['Dashboards'])
    async def delete_dashboard(dashboard_id: UUID):
        if not dashboard_library().delete(dashboard_owner.get(), str(dashboard_id)):
            raise HTTPException(404, 'Dashboard não encontrado neste perfil.')

    @router.get('/dashboards/{dashboard_id}', tags=['Dashboards'])
    async def dashboard_details(dashboard_id: UUID):
        item = owned_dashboard(dashboard_id)
        return {k: item[k] for k in ('id', 'title', 'description', 'created_at')}

    @router.get('/dashboards/{dashboard_id}/html', tags=['Dashboards'])
    async def dashboard_html(dashboard_id: UUID, session: Session,
                             filters: str = Query(default='{}', max_length=8000)):
        item = owned_dashboard(dashboard_id)
        try:
            selections = json.loads(filters)
        except ValueError:
            raise HTTPException(422, 'Filtros devem ser um objeto JSON.') from None
        if not isinstance(selections, dict):
            raise HTTPException(422, 'Filtros devem ser um objeto JSON.')
        toolbox = Toolbox(settings, RefreshStore(scoped_store(session)), app.state.mcp, None)
        try:
            async with asyncio.timeout(35):
                html = await refresh(toolbox, item, selections)
            return HTMLResponse(html)
        except AgentError as exc:
            raise HTTPException(422, 'Não foi possível atualizar o dashboard: ' + str(exc)
                                + ' Importações expiradas precisam ser importadas e o dashboard recriado.') from None
        except TimeoutError:
            raise HTTPException(504, 'Tempo esgotado ao atualizar o dashboard.') from None

    @router.get('/profile', response_model=LocalProfile, tags=['Perfil'])
    async def local_profile(request: Request, session: Session):
        identity = getattr(request.state, 'identity', None)
        return LocalProfile(usage=scoped_store(session).usage_statistics(), **(
            {'name': identity.name, 'identity': identity.email,
             'profile': identity.perfil, 'role': identity.cargo, 'function': identity.funcao,
             'department': identity.departamento, 'unit_number': identity.numero_pa,
             'unit_name': identity.nome_pa, 'photo_url': identity.foto_url,
             'auth_mode': 'development' if identity.uid == 'development' else 'sso'}
            if identity else {}))

    def query_values(request: FavoriteQuery):
        values = request.model_dump()
        values["name"] = request.name.strip()
        if not values["name"]:
            raise HTTPException(422, "Informe um nome para a consulta.")
        if request.database not in CATALOG_DATABASES or (
                settings.allowed_databases and request.database not in settings.allowed_databases):
            raise HTTPException(422, "Base de dados não permitida.")
        try:
            validate_sql(request.sql)
        except AgentError as exc:
            raise HTTPException(422, str(exc)) from None
        return values

    @router.get('/queries', tags=['Consultas favoritas'])
    async def list_queries():
        return {'queries': app.state.store.list_queries()}

    @router.post('/queries', status_code=201, tags=['Consultas favoritas'])
    async def create_query(request: FavoriteQuery):
        return app.state.store.save_query(query_values(request))

    @router.put('/queries/{query_id}', tags=['Consultas favoritas'])
    async def update_query(query_id: UUID, request: FavoriteQuery):
        result = app.state.store.save_query(query_values(request), str(query_id))
        if result is None:
            raise HTTPException(404, 'Consulta favorita não encontrada.')
        return result

    @router.delete('/queries/{query_id}', status_code=204, tags=['Consultas favoritas'])
    async def delete_query(query_id: UUID):
        if not app.state.store.delete_query(str(query_id)):
            raise HTTPException(404, 'Consulta favorita não encontrada.')

    @router.post('/queries/{query_id}/execute', tags=['Consultas favoritas'])
    async def execute_query(query_id: UUID, session: Session):
        if app.state.store.get_query(str(query_id)) is None:
            raise HTTPException(404, 'Consulta favorita não encontrada.')
        toolbox = Toolbox(settings, scoped_store(session), app.state.mcp, None)
        try:
            async with asyncio.timeout(35):
                return await toolbox.call('run_favorite_query', {'query_id': str(query_id)})
        except AgentError as exc:
            raise HTTPException(422, str(exc)) from None
        except TimeoutError:
            raise HTTPException(504, 'Tempo esgotado ao executar a consulta.') from None

    @router.post('/import-sessions', tags=['Importação temporária'], status_code=201)
    async def new_import_session(x_data_session: Annotated[UUID | None, Header()] = None):
        if x_data_session:
            try:
                await app.state.imports.remove(str(x_data_session))
            except AgentError:
                raise HTTPException(410, 'Sessão temporária não encontrada.') from None
        try:
            session = app.state.imports.create()
        except AgentError as exc:
            raise HTTPException(429, str(exc)) from None
        return {'session_id': session.id, 'expires_after_idle_seconds': app.state.imports.ttl}

    @router.delete('/import-sessions/current', tags=['Importação temporária'], status_code=204)
    async def close_import_session(x_data_session: Annotated[UUID | None, Header()] = None):
        if x_data_session:
            try:
                await app.state.imports.remove(str(x_data_session))
            except AgentError:
                raise HTTPException(410, 'Sessão temporária não encontrada.') from None

    @router.post('/imports', tags=['Importação temporária'])
    async def temporary_upload(file: Annotated[UploadFile, File()], session: Session,
                               max_datasets: int = Query(default=10, ge=1, le=10)):
        if session is None:
            await file.close()
            raise HTTPException(409, 'Inicie uma sessão temporária antes de importar os dados.')
        if session.importing:
            await file.close()
            raise HTTPException(409, 'Uma importação já está em andamento nesta sessão.')
        if not settings.llm_ready:
            await file.close()
            raise HTTPException(409, 'Configure a chave de IA para inferir os cabeçalhos e os tipos.')
        session.importing = True
        saved = []
        stage = 'upload'
        try:
            filename = file.filename or ''
            if file.size is not None and file.size > settings.max_temporary_upload_bytes:
                raise ImportFailure('Arquivo excede o limite de upload temporário.', 413)
            content = await file.read(settings.max_temporary_upload_bytes + 1)
            await file.close()
            if len(content) > settings.max_temporary_upload_bytes:
                raise ImportFailure('Arquivo excede o limite de upload.', 413)
            stage = 'read'
            tables, notes = await asyncio.to_thread(
                read_tables, filename, content, settings.max_temporary_rows, max_datasets,
                max_expanded_bytes=settings.max_temporary_expanded_bytes,
                max_characters=settings.max_temporary_characters,
            )
            stage = 'inference'
            async with asyncio.timeout(150):
                schema = await infer_schema(tables, app.state.llm, settings.openai_model)
            stage = 'validation'
            normalized = await asyncio.to_thread(normalize_tables, filename, content, tables, schema, notes, settings.max_temporary_rows)
            if session.id not in app.state.imports.sessions:
                raise HTTPException(410, 'A sessão foi encerrada durante a importação. Importe novamente.')
            for rows, source in normalized:
                stage = 'parquet'
                saved.append(session.store.save_dataset(rows, source))
            return {'temporary': True, 'datasets': [preview(dataset) for dataset in saved]}
        except ImportFailure as exc:
            logger.warning('temporary_import_failed stage=%s status=%s', stage, exc.status)
            raise HTTPException(exc.status, str(exc), headers={'X-Import-Stage': stage}) from None
        except TimeoutError:
            raise HTTPException(504, 'Tempo esgotado na inferência por IA; nenhum dado foi importado.') from None
        except AgentError as exc:
            status = 410 if session.store.closed else 422
            logger.warning('temporary_import_failed stage=%s status=%s', stage, status)
            raise HTTPException(status, str(exc), headers={'X-Import-Stage': stage}) from None
        finally:
            session.importing = False
            await file.close()
            # Só há datasets retornados em sucesso; falhas parciais devem ser removidas.
            if saved and len(saved) != len(locals().get('normalized', [])):
                for dataset in saved:
                    session.store.remove_dataset(dataset['id'])

    @app.middleware("http")
    async def response_headers(request, call_next):
        request.state.identity = (await asyncio.to_thread(
            auth_sessions.get, request.cookies.get(COOKIE, '')) if auth_sessions else None)
        if request.state.identity and request.state.identity.uid == 'development':
            request.state.identity = Identity.for_development(settings) if development_bypass else None
        blocked = None
        if auth_sessions:
            origin = request.headers.get('origin')
            target = settings.sso_expected_target or request.url.netloc
            if (request.method not in {'GET', 'HEAD', 'OPTIONS'}
                    and request.url.path != '/login' and origin
                    and origin != 'https://' + target
                    and not ((not settings.sso_cookie_secure or development_bypass)
                             and origin == 'http://' + target)):
                blocked = JSONResponse({'detail': 'Origem não permitida.'}, status_code=403)
            public = (request.url.path in {'/login', '/health', '/favicon.ico'}
                      or request.url.path.startswith('/static/'))
            if not public and not request.state.identity:
                blocked = JSONResponse({'detail': 'Entre pelo ScdAuth para acessar a aplicação.'},
                                       status_code=401)
        owner = request.cookies.get('scd-dashboard-profile', '')
        new_owner = not re.fullmatch(r'[a-f0-9]{64}', owner)
        if new_owner:
            owner = secrets.token_hex(32)
        token = dashboard_owner.set(owner)
        history_token = history_owner.set(identity_owner(
            request.state.identity, owner, settings.sso_expected_issuer))
        try:
            response = blocked if blocked is not None else await call_next(request)
        finally:
            dashboard_owner.reset(token)
            history_owner.reset(history_token)
        if new_owner:
            response.set_cookie('scd-dashboard-profile', owner, max_age=31536000,
                                httponly=True, samesite='strict', secure=request.url.scheme == 'https')
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        if auth_sessions or request.url.path in {'/login', '/logout'} or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        # Swagger usa scripts externos; a UI principal não depende de CDN.
        if request.url.path in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
            del response.headers["Content-Security-Policy"]
        return response

    @app.get("/health", tags=["Operação"])
    async def health():
        return {"status": "ok"}

    @app.get('/favicon.ico', include_in_schema=False, status_code=204)
    async def favicon():
        return Response(status_code=204)

    @router.get("/status", tags=["Operação"])
    async def status():
        return {"llm_configured": settings.llm_ready, "model": settings.openai_model,
                "internet_enabled": settings.internet_enabled,
                "internet_search_provider": settings.internet_search_provider,
                "internet_search_model": settings.internet_search_model or settings.openai_model,
                "tls_verification": settings.openai_verify_ssl,
                "mcp_tls_verification": settings.mcp_verify_ssl,
                "auth_enabled": bool(auth_sessions or settings.app_api_key.get_secret_value()),
                "max_upload_bytes": settings.max_upload_bytes,
                "max_temporary_upload_bytes": settings.max_temporary_upload_bytes,
                "max_query_rows": settings.max_query_rows}

    @router.get("/connections/pg-mcp", tags=["Operação"])
    async def connection():
        try:
            async with asyncio.timeout(35):
                tools = await app.state.mcp.discover()
                toolbox = Toolbox(settings, app.state.store, app.state.mcp, None)
                databases = await toolbox.call("list_databases", {})
            return {"connected": True, "tools": tools, "databases": databases}
        except AgentError as exc:
            raise HTTPException(503, str(exc)) from None
        except TimeoutError:
            raise HTTPException(503, "Tempo esgotado ao conectar ao pg_mcp.") from None

    async def catalog_call(name: str, arguments: dict):
        toolbox = Toolbox(settings, app.state.store, app.state.mcp, None)
        try:
            async with asyncio.timeout(35):
                if name == "list_public_databases":
                    return await toolbox.call(name, {})
                if arguments["database"] not in CATALOG_DATABASES:
                    raise AgentError("Base de dados indisponível no seletor de dados.")
                await toolbox.call("list_databases", {})
                if not await toolbox.has_public_access(arguments["database"]):
                    raise AgentError("O usuário pg_mcp não tem acesso ao schema public deste database.")
                return await toolbox.call(name, arguments)
        except AgentError as exc:
            raise HTTPException(503, str(exc)) from None
        except TimeoutError:
            raise HTTPException(503, "Tempo esgotado ao carregar o catálogo PostgreSQL.") from None

    @router.get("/catalog/databases", tags=["Dados"])
    async def catalog_databases():
        return await catalog_call("list_public_databases", {})

    @router.get("/skills", tags=["Skills"])
    async def list_skills():
        return {"skills": available_skills()}

    @router.get("/catalog/tables", tags=["Dados"])
    async def catalog_tables(database: str, schema: str = "public"):
        result = await catalog_call("list_tables", {"database": database, "schema": schema})
        try:
            return {"database": database, "tables": table_entries(result, schema)}
        except AgentError as exc:
            raise HTTPException(503, str(exc)) from None

    @router.post("/catalog/preview", tags=["Dados"])
    async def catalog_preview(request: PreviewTable):
        return await catalog_call("preview_table", request.model_dump(by_alias=True))

    @router.post("/runs", response_model=Run, status_code=202, tags=["Execuções"])
    async def submit(request: RunRequest, session: Session):
        if request.conversation_id and not scoped_store(session).conversation(str(request.conversation_id), 1) and not Workspaces(scoped_store(session)).owns(str(request.conversation_id)):
            raise HTTPException(404, 'Conversa não encontrada.')
        try:
            manager = app.state.manager
            if session and (session.store.datasets
                            or session.store.has_conversation(str(request.conversation_id))):
                manager = session.manager
            profile = Workspaces(manager.store).user_agent_for(str(request.conversation_id)) if request.conversation_id else None
            return manager.submit(request, profile=profile)
        except AgentError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.get("/runs", response_model=list[Run], tags=["Execuções"])
    async def list_runs(session: Session):
        return scoped_store(session).list_runs()

    @router.get("/conversations", response_model=list[Run], tags=["Execuções"])
    async def list_conversations(session: Session, limit: Annotated[int | None, Query(ge=1)] = None):
        return scoped_store(session).list_conversations(limit)

    @router.get("/runs/{run_id}", response_model=Run, tags=["Execuções"])
    async def get_run(run_id: UUID, session: Session):
        run = scoped_store(session).get_run(str(run_id))
        if run is None:
            raise HTTPException(404, "Execução não encontrada.")
        return run

    @router.post("/runs/{run_id}/cancel", response_model=Run, tags=["Execuções"])
    async def cancel(run_id: UUID, session: Session):
        if scoped_store(session).get_run(str(run_id)) is None:
            raise HTTPException(404, 'Execução não encontrada.')
        manager = session.manager if session and str(run_id) in session.store.runs else app.state.manager
        run = await manager.cancel(str(run_id))
        if run is None:
            raise HTTPException(404, "Execução não encontrada.")
        return run

    @router.post("/datasets/upload", tags=["Dados"])
    async def upload(file: Annotated[UploadFile, File()]):
        try:
            content = await file.read(settings.max_upload_bytes + 1)
        finally:
            await file.close()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(413, "Arquivo excede o limite de upload.")
        try:
            rows, source = await asyncio.to_thread(import_file, file.filename or "", content, settings.max_dataset_rows)
        except ImportFailure as exc:
            raise HTTPException(exc.status, str(exc)) from None
        dataset = app.state.store.save_dataset(rows, source)
        return preview(dataset)

    @router.get("/datasets/{dataset_id}", tags=["Dados"])
    async def get_dataset(dataset_id: UUID, session: Session):
        dataset = scoped_store(session).get_dataset(str(dataset_id))
        if dataset is None:
            raise HTTPException(404, "Dataset não encontrado.")
        return preview(dataset)

    @router.get("/artifacts/{artifact_id}", tags=["Relatórios"])
    async def artifact(artifact_id: UUID, session: Session):
        store = scoped_store(session)
        item = store.get_artifact(str(artifact_id))
        if item is None:
            raise HTTPException(404, "Arquivo não encontrado.")
        path = store.artifact_path(item) if session else store.artifacts_dir / item['filename']
        if not path.is_file():
            raise HTTPException(404, "Arquivo não está disponível no disco.")
        media = {"pdf": "application/pdf", "html": "text/html", "md": "text/markdown", "csv": "text/csv",
                 "json": "application/json", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        return FileResponse(path, filename=f"relatorio-{item['id'][:8]}.{item['format']}",
                            media_type=media[item["format"]])

    app.include_router(router)
    app.include_router(workspace_router(app, authorize, import_session))
    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/historico", include_in_schema=False)
    @app.get("/sessoes", include_in_schema=False)
    @app.get("/agendamentos", include_in_schema=False)
    @app.get("/dashboards", include_in_schema=False)
    async def index():
        html = (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
        html = html.replace('<head>', f'<head><meta name="app-root-path" content="{settings.app_root_path}">')
        html = html.replace('href="/', f'href="{settings.app_root_path}/')
        html = html.replace('src="/', f'src="{settings.app_root_path}/')
        return HTMLResponse(html)

    @app.get('/dashboards/{dashboard_id}', include_in_schema=False)
    async def dashboard_page(dashboard_id: UUID):
        return await index()

    return app


def create_development_app() -> FastAPI:
    """Factory do launcher --development, compatível com o processo de reload."""
    return create_app(development=True)


app = create_app()
