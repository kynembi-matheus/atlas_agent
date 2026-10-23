"""API FastAPI e aplicação web servidas pela mesma origem."""
import asyncio
import csv
import io
import secrets
from contextlib import asynccontextmanager
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agents.orchestrator import Agent, RunManager, make_client
from core.config import ROOT, Settings
from integrations.pg_mcp import PgMCP
from core.models import AgentError, Run, RunRequest
from repositories.local_store import Store
from tools.data_tools import preview, rows_of


def create_app(settings: Settings | None = None, *, mcp=None, client=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.data_dir)
        store.recover()
        llm = client if client is not None else make_client(settings)
        pg = mcp if mcp is not None else PgMCP(settings)
        app.state.store, app.state.mcp = store, pg
        app.state.manager = RunManager(Agent(settings, store, pg, llm))
        yield
        await app.state.manager.close()
        if client is None:
            await llm.close()

    app = FastAPI(title="Agente SCD", version="0.1.0", lifespan=lifespan,
                  description="Análises e relatórios com ferramentas controladas e PostgreSQL via MCP.")

    async def authorize(authorization: str | None = Header(default=None)):
        expected = settings.app_api_key.get_secret_value()
        if expected and not secrets.compare_digest(authorization or "", f"Bearer {expected}"):
            raise HTTPException(401, "Chave de acesso inválida.", headers={"WWW-Authenticate": "Bearer"})

    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        # Swagger usa scripts externos; a UI principal não depende de CDN.
        if request.url.path in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
            del response.headers["Content-Security-Policy"]
        return response

    @app.get("/health", tags=["Operação"])
    async def health():
        return {"status": "ok"}

    @router.get("/status", tags=["Operação"])
    async def status():
        return {"llm_configured": settings.llm_ready, "model": settings.openai_model,
                "tls_verification": settings.openai_verify_ssl,
                "mcp_tls_verification": settings.mcp_verify_ssl,
                "auth_enabled": bool(settings.app_api_key.get_secret_value()),
                "max_upload_bytes": settings.max_upload_bytes,
                "max_query_rows": settings.max_query_rows}

    @router.get("/connections/pg-mcp", tags=["Operação"])
    async def connection():
        try:
            async with asyncio.timeout(35):
                tools = await app.state.mcp.discover()
                databases = await app.state.mcp.call("list_databases", {})
            return {"connected": True, "tools": tools, "databases": databases}
        except AgentError as exc:
            raise HTTPException(503, str(exc)) from None
        except TimeoutError:
            raise HTTPException(503, "Tempo esgotado ao conectar ao pg_mcp.") from None

    @router.post("/runs", response_model=Run, status_code=202, tags=["Execuções"])
    async def submit(request: RunRequest):
        try:
            return app.state.manager.submit(request)
        except AgentError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.get("/runs", response_model=list[Run], tags=["Execuções"])
    async def list_runs():
        return app.state.store.list_runs()

    @router.get("/runs/{run_id}", response_model=Run, tags=["Execuções"])
    async def get_run(run_id: UUID):
        run = app.state.store.get_run(str(run_id))
        if run is None:
            raise HTTPException(404, "Execução não encontrada.")
        return run

    @router.post("/runs/{run_id}/cancel", response_model=Run, tags=["Execuções"])
    async def cancel(run_id: UUID):
        run = await app.state.manager.cancel(str(run_id))
        if run is None:
            raise HTTPException(404, "Execução não encontrada.")
        return run

    @router.post("/datasets/upload", tags=["Dados"])
    async def upload(file: UploadFile = File(...)):
        try:
            content = await file.read(settings.max_upload_bytes + 1)
        finally:
            await file.close()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(413, "Arquivo excede o limite de upload.")
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(415, "Envie um arquivo CSV UTF-8; delimitador vírgula ou ponto e vírgula.")
        try:
            text = content.decode("utf-8-sig")
            try:
                delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
            frame = await asyncio.to_thread(
                pd.read_csv, io.BytesIO(content), sep=delimiter, engine="python", encoding="utf-8-sig",
                nrows=settings.max_dataset_rows + 1,
            )
        except (ValueError, UnicodeError, pd.errors.ParserError):
            raise HTTPException(422, "CSV inválido. Verifique cabeçalhos, delimitador e UTF-8.") from None
        if len(frame) > settings.max_dataset_rows or len(frame.columns) > 200:
            raise HTTPException(413, "CSV excede o limite de linhas ou de 200 colunas.")
        if frame.empty:
            raise HTTPException(422, "O CSV precisa ter pelo menos uma linha de dados.")
        dataset = app.state.store.save_dataset(rows_of(frame), {
            "kind": "csv_upload", "filename": file.filename[:200], "row_count": len(frame),
        })
        return preview(dataset)

    @router.get("/datasets/{dataset_id}", tags=["Dados"])
    async def get_dataset(dataset_id: UUID):
        dataset = app.state.store.get_dataset(str(dataset_id))
        if dataset is None:
            raise HTTPException(404, "Dataset não encontrado.")
        return preview(dataset)

    @router.get("/artifacts/{artifact_id}", tags=["Relatórios"])
    async def artifact(artifact_id: UUID):
        item = app.state.store.get_artifact(str(artifact_id))
        if item is None:
            raise HTTPException(404, "Arquivo não encontrado.")
        path = app.state.store.artifacts_dir / item["filename"]
        if not path.is_file():
            raise HTTPException(404, "Arquivo não está disponível no disco.")
        media = {"html": "text/html", "md": "text/markdown", "csv": "text/csv",
                 "json": "application/json", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        return FileResponse(path, filename=f"relatorio-{item['id'][:8]}.{item['format']}",
                            media_type=media[item["format"]])

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(ROOT / "frontend/index.html")

    return app


app = create_app()
