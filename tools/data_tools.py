"""Ferramentas declarativas: o modelo nunca executa Python ou shell arbitrário."""
import asyncio
import io
import json
import math
from html import escape
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pandas as pd
import sqlglot
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlglot import exp

from core.config import ROOT, Settings
from core.models import AgentError, Run
from core.skill_catalog import available_skills
from core.workspace_models import (
    CreateSubagent,
    DelegateBatch,
    DelegateTask,
    ListSubagents,
    ProposeSchedule,
    ScheduleTask,
    SubagentId,
)
from integrations.internet import Internet
from integrations.pg_mcp import PgMCP
from integrations.web_search import search_web
from repositories.local_store import Store, encode, now
from tools.dashboards import Dashboard, create_dashboard
from tools.excel_reports import ExcelReport, build_excel
from tools.forecasting import ForecastRequest, estimate_forecast
from tools.internet import ReadWebPage, SearchWeb
from tools.patterns import PatternRequest, investigate_patterns
from tools.pdf_reports import PDFReport, build_pdf
from tools.report_sources import report_source, report_warning
from tools.report_tables import ReportTable, table_data

CATALOG_DATABASES = ("synap", "deskflow", "cora", "crm_cob", "hub", "starcoop")


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(Arguments):
    """Publique um plano curto de ações verificáveis antes de iniciar a análise."""
    steps: list[str] = Field(min_length=1, max_length=8)


class ConversationTitle(Arguments):
    """Defina um título curto da sessão a partir do assunto da conversa, em texto simples."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=80)


class SearchDocs(Arguments):
    """Busque regras de negócio e fontes na documentação local. Consulta vazia lista arquivos."""
    query: str = Field(default="", max_length=300)


class ReadDoc(Arguments):
    """Leia um documento pelo caminho retornado por search_docs, em trechos de até 12000 caracteres."""
    path: str
    offset: int = Field(default=0, ge=0)


class ListDatabases(Arguments):
    """Descubra os databases permitidos antes de fazer qualquer chamada ao banco."""


class ListImportedDatasets(Arguments):
    """Liste os datasets importados temporários disponíveis somente na sessão atual."""


class ListPublicDatabases(Arguments):
    """Liste as bases do seletor permitidas e com acesso ao schema public pelo usuário MCP."""


class ListTables(Arguments):
    """Liste tabelas e views de um database previamente descoberto."""
    database: str
    schema_name: str = Field(default="public", alias="schema")


class DescribeTable(ListTables):
    """Inspecione colunas e tipos reais antes de escrever SQL."""
    table: str


class PreviewTable(DescribeTable):
    """Veja uma amostra de até 10 linhas de uma tabela descoberta, nunca o total da tabela."""


def table_entries(result, schema: str) -> list[dict]:
    """Normalize as respostas tabulares do catálogo MCP, preservando o schema."""
    if isinstance(result, dict):
        result = result.get("tables", result.get("rows", []))
    if not isinstance(result, list):
        raise AgentError("O pg_mcp não retornou uma lista de tabelas compatível.")
    entries = []
    for item in result:
        if isinstance(item, str):
            name, owner = item, schema
        elif isinstance(item, dict):
            name = item.get("table_name", item.get("table", item.get("tablename")))
            owner = item.get("table_schema", item.get("schema", schema))
        else:
            continue
        if isinstance(name, str) and name and isinstance(owner, str) and owner:
            entries.append({"table": name, "schema": owner})
    return entries


class Query(Arguments):
    """Execute um único SELECT PostgreSQL. Retorna dataset_id e prévia, não todas as linhas.

    Faça agregações no SQL para totais corretos. Um resultado limitado é uma amostra.
    """
    database: str
    sql: str = Field(min_length=1, max_length=20000)
    max_rows: int = Field(default=1000, ge=1)


class Dataset(Arguments):
    """Inspecione uma página de um dataset existente e sua origem."""
    dataset_id: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=100)


class FavoriteQuery(Query):
    """Definição de uma consulta favorita somente leitura."""
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=2000)


class ListFavoriteQueries(Arguments):
    """Liste as consultas favoritas salvas pelo usuário, com SQL e base de origem."""


class RunFavoriteQuery(Arguments):
    """Execute uma favorita pelo ID salvo, preservando SQL, base, limites e origem."""
    query_id: UUID


class Analyze(Arguments):
    """Calcule estatísticas, tipos e valores ausentes de um dataset, sem inventar métricas."""
    dataset_id: str


class Operation(Arguments):
    """select/sort/to_numeric exigem columns; filter exige column; fill_nulls exige value
    não nulo; group exige aggregations. to_numeric aceita ponto decimal, sem coerção de erros.
    """
    op: Literal["select", "drop_duplicates", "drop_nulls", "fill_nulls", "sort", "filter", "group", "to_numeric"]
    columns: list[str] = Field(default_factory=list, max_length=100)
    column: str | None = None
    value: str | int | float | bool | None = None
    comparison: Literal["eq", "ne", "gt", "ge", "lt", "le", "contains"] = "eq"
    ascending: bool = True
    aggregations: dict[str, Literal["sum", "mean", "min", "max", "count", "nunique", "median"]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_operation(self):
        if self.op in {"select", "sort", "to_numeric"} and not self.columns:
            raise ValueError("Informe columns para select, sort ou to_numeric.")
        if self.op == "filter" and not self.column:
            raise ValueError("Informe column para filter.")
        if self.op == "fill_nulls" and self.value is None:
            raise ValueError("Informe value não nulo para fill_nulls.")
        if self.op == "group" and not self.aggregations:
            raise ValueError("Informe aggregations para group.")
        return self


class Transform(Arguments):
    """Organize dados com operações sequenciais. Cria novo dataset, preservando o original.

    group usa columns como chaves e aggregations como {coluna: função}. Sem chaves, agrega o total.
    to_numeric converte columns com números em texto (ponto decimal); falha se houver texto
    inválido, sem descartá-lo. Não converta identificadores. Agregações numéricas exigem números.
    """
    dataset_id: str
    operations: list[Operation] = Field(min_length=1, max_length=12)


class Export(Arguments):
    """Exporte um dataset real para CSV, Excel ou JSON com link para download."""
    dataset_id: str
    format: Literal["csv", "xlsx", "json"]
    title: str = Field(default="Dados", max_length=150)


class Report(Arguments):
    """Gere relatório profissional Markdown e HTML com tabelas analíticas e gráfico HTML.

    Descreva metodologia, período, conclusões e limitações no body. HTML pode ser impresso em PDF.
    chart_x e chart_y devem ser colunas do primeiro dataset; barras mostram até 20 linhas.
    Use contexto de negócio; não inclua nomes de tabelas, SQL ou IDs no texto.
    Inclua tables com título, contexto e colunas selecionadas com rótulos e unidades de negócio.
    Para o gráfico, informe chart_title, chart_context e chart_unit.
    """
    title: str = Field(max_length=150)
    body: str = Field(max_length=30000)
    dataset_ids: list[str] = Field(default_factory=list, max_length=8)
    chart_x: str | None = None
    chart_y: str | None = None
    chart_title: str = Field(default='Comparação dos indicadores', max_length=150)
    chart_context: str = Field(default='', max_length=1000)
    chart_unit: str = Field(default='', max_length=30)
    tables: list[ReportTable] = Field(default_factory=list, max_length=6)


SCHEMAS = {
    'propose_schedule': ProposeSchedule,
    'create_subagent': CreateSubagent, 'list_subagents': ListSubagents,
    'delegate_to_subagent': DelegateTask, 'cancel_subagent': SubagentId, 'schedule_task': ScheduleTask,
    'delegate_to_subagents': DelegateBatch,
    "set_conversation_title": ConversationTitle,
    "search_web": SearchWeb, "read_web_page": ReadWebPage,
    "create_dashboard": Dashboard,
    "list_favorite_queries": ListFavoriteQueries, "run_favorite_query": RunFavoriteQuery,
    "update_plan": Plan, "search_docs": SearchDocs, "read_doc": ReadDoc,
    "list_databases": ListDatabases, "list_public_databases": ListPublicDatabases,
    "list_imported_datasets": ListImportedDatasets,
    "list_tables": ListTables, "preview_table": PreviewTable,
    "describe_table": DescribeTable, "query": Query, "inspect_dataset": Dataset,
    "analyze_dataset": Analyze, "transform_dataset": Transform,
    "export_dataset": Export, "create_report": Report, "create_pdf_report": PDFReport,
    "create_excel_report": ExcelReport, "forecast_series": ForecastRequest, "find_patterns": PatternRequest,
}


def definitions(*, internet_enabled: bool = True) -> list[dict]:
    return [{"type": "function", "name": name, "description": schema.__doc__ or name,
             "parameters": schema.model_json_schema(), "strict": False}
            for name, schema in SCHEMAS.items()
            if internet_enabled or name not in {"search_web", "read_web_page"}]


def validate_sql(sql: str) -> str:
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.SqlglotError:
        raise AgentError("SQL inválido para PostgreSQL.") from None
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise AgentError("Use apenas uma consulta SELECT, opcionalmente com CTEs.")
    tree = statements[0]
    forbidden = (exp.DDL, exp.DML, exp.Command, exp.Into, exp.Lock)
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise AgentError("Operações de escrita, SELECT INTO e locks não são permitidos.")
    for node in tree.find_all(exp.Func):
        name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
        if name.startswith(("pg_", "dblink", "lo_")) or name in {"set_config", "nextval", "setval"}:
            raise AgentError("Função administrativa ou com efeitos colaterais não permitida.")
    return tree.sql(dialect="postgres")


def rows_of(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))


def preview(dataset: dict, offset: int = 0, limit: int = 10) -> dict:
    frame = pd.DataFrame(dataset["rows"])
    return {"dataset_id": dataset["id"], "row_count": len(frame),
            "columns": list(frame.columns), "source": dataset["source"],
            "preview": dataset["rows"][offset:offset + limit],
            "preview_only": offset > 0 or len(frame) > limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(frame) else None,
            **coverage(dataset["source"])}


def coverage(source: dict) -> dict:
    """Propaga limites da origem mesmo depois de filtrar ou agregar uma amostra."""
    current = source
    truncated = False
    extraction_warnings = []
    while isinstance(current, dict):
        truncated |= bool(current.get("possibly_truncated"))
        for warning in current.get("extraction_warnings", []):
            if warning not in extraction_warnings:
                extraction_warnings.append(warning)
        for warning in current.get("analysis_warnings", []):
            if warning not in extraction_warnings:
                extraction_warnings.append(warning)
        current = current.get("original_source")
    return {"possibly_truncated": truncated,
            "scope": "stored_rows_only",
            "warnings": ([("Origem possivelmente truncada: métricas e agregações locais não "
                          "representam totais da população. Consulte a fonte integral ou calcule totais no SQL.")]
                         if truncated else []) + extraction_warnings}


def safe_spreadsheet(frame: pd.DataFrame) -> pd.DataFrame:
    # Protege valores e cabeçalhos sem alterar valores numéricos.
    def neutralize(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    return frame.map(neutralize).rename(columns=neutralize)


class Toolbox:
    def workspace(self):
        if self.is_subagent or self.workspace_control is None:
            raise AgentError('Esta capacidade é controlada exclusivamente pelo agente principal.')
        return self.workspace_control

    async def create_subagent(self, args):
        return self.workspace().create(args)

    async def list_subagents(self, args):
        return self.workspace().list()

    async def delegate_to_subagent(self, args):
        return await self.workspace().delegate(args)

    async def delegate_to_subagents(self, args):
        return await self.workspace().delegate_many(args)

    async def cancel_subagent(self, args):
        return await self.workspace().cancel(args)

    async def schedule_task(self, args):
        return self.workspace().schedule(args)

    async def propose_schedule(self, args):
        return self.workspace().propose_schedule(args)
    async def search_web(self, args: SearchWeb):
        if not self.settings.internet_enabled:
            raise AgentError('Plugin de internet desativado nesta instalação.')
        if self.web_search_error:
            raise AgentError(self.web_search_error)
        try:
            if self.settings.internet_search_provider == 'openai':
                return await search_web(self.search_client, self.settings, args.query, args.max_results)
            return await Internet(self.settings).search(args.query, args.max_results)
        except AgentError:
            self.web_search_error = (
                "Pesquisa web indisponível nesta execução. Não repita a busca. "
                "Informe a limitação ou leia uma URL pública conhecida se necessário."
            )
            raise

    async def read_web_page(self, args: ReadWebPage):
        return await Internet(self.settings).read(args.url, args.offset)

    async def create_dashboard(self, args: Dashboard):
        return await create_dashboard(self, args)

    def __init__(self, settings: Settings, store: Store, mcp: PgMCP, run: Run | None,
                 *, web_enabled: bool | None = None, search_client=None, workspace_control=None,
                 is_subagent=False):
        self.settings, self.store, self.mcp, self.run = settings, store, mcp, run
        self.web_enabled = settings.internet_enabled and web_enabled is not False
        self.web_search_error: str | None = None
        self.search_client = search_client
        self.workspace_control, self.is_subagent = workspace_control, is_subagent
        self.databases: set[str] | None = None

    @property
    def query_store(self):
        return getattr(self.store, "persistent", self.store)

    async def list_favorite_queries(self, args: ListFavoriteQueries):
        return {"queries": self.query_store.list_queries()}

    async def run_favorite_query(self, args: RunFavoriteQuery):
        item = self.query_store.get_query(str(args.query_id))
        if item is None:
            raise AgentError("Consulta favorita não encontrada.")
        if self.databases is None:
            await self.list_databases(ListDatabases())
        return await self._query(Query.model_validate({key: item[key] for key in
                                 ("database", "sql", "max_rows")}), {
            "favorite_query_id": item["id"], "favorite_query_name": item["name"],
            "favorite_query_updated_at": item["updated_at"],
        })

    async def call(self, name: str, arguments: dict) -> Any:
        if name in {"search_web", "read_web_page"} and not self.web_enabled:
            raise AgentError("Pesquisa web desativada para este pedido.")
        if name not in SCHEMAS:
            raise AgentError("Ferramenta desconhecida.")
        try:
            args = SCHEMAS[name].model_validate(arguments)
        except ValidationError as exc:
            # Retorna somente locais/tipos, nunca os valores recebidos ou contexto de exceção.
            issues = [f"{'.'.join(map(str, error['loc'])) or 'arguments'}: {error['type']}"
                      + (" (" + error["msg"] + ")" if error["type"] == "value_error" else "")
                      for error in exc.errors(include_input=False, include_context=False)[:8]]
            raise AgentError("Argumentos inválidos em " + name + ": " + "; ".join(issues)
                             + ". Confira os campos e requisitos no schema da ferramenta.") from None
        try:
            return await getattr(self, name)(args)
        except AgentError:
            raise
        except (KeyError, ValueError, TypeError):
            raise AgentError("Operação inválida. Confira colunas, tipos e parâmetros do dataset.") from None

    def dataset(self, dataset_id: str) -> dict:
        dataset = self.store.get_dataset(dataset_id)
        if dataset is None:
            raise AgentError("Dataset não encontrado. Use um identificador retornado por ferramenta.")
        return dataset

    def documents(self) -> dict[str, Path]:
        files = {}
        roots = {"docs": self.settings.docs_dir}
        for skill in available_skills():
            alias = skill['document_path'].split('/')[0]
            roots[alias] = ROOT / 'skills' / skill['id']
        for prefix, root in roots.items():
            root = root.resolve()
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root)
                if (path.is_file() and path.suffix.lower() in {".md", ".txt", ".rst", ".sql"}
                        and not any(part.startswith(".") for part in relative.parts)
                        and path.resolve().is_relative_to(root) and path.stat().st_size <= 1024 * 1024):
                    files[f"{prefix}/{relative.as_posix()}"] = path
                if len(files) >= 300:
                    return files
        return files

    async def update_plan(self, args: Plan):
        return {"steps": args.steps}

    async def set_conversation_title(self, args: ConversationTitle):
        if self.is_subagent:
            raise AgentError('Somente o principal define o título da sessão.')
        if self.run is None:
            raise AgentError('Inicie uma conversa para definir o título da sessão.')
        self.run.title = args.title
        self.store.save_run(self.run)
        return {'title': self.run.title}

    async def list_imported_datasets(self, args: ListImportedDatasets):
        return {'datasets': [{'dataset_id': item['id'], 'row_count': item['row_count'],
                              'columns': item['columns'], 'source': item['source']}
                             for item in getattr(self.store, 'datasets', {}).values()
                             if item['source'].get('kind') == 'temporary_import'], 'temporary': True}

    async def search_docs(self, args: SearchDocs):
        terms = args.query.lower().split()
        matches = []
        for name, path in self.documents().items():
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            lower = text.lower()
            score = sum(lower.count(term) + name.lower().count(term) * 3 for term in terms)
            if not terms or score:
                positions = [lower.find(term) for term in terms if term in lower]
                start = max(0, min(positions, default=0) - 150)
                matches.append({"path": name, "score": score, "excerpt": text[start:start + 1200]})
        return sorted(matches, key=lambda item: item["score"], reverse=True)[:8]

    async def read_doc(self, args: ReadDoc):
        path = self.documents().get(args.path)
        if path is None:
            raise AgentError("Documento não encontrado. Use o caminho retornado por search_docs.")
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        return {"path": args.path, "text": text[args.offset:args.offset + 12000],
                "next_offset": args.offset + 12000 if len(text) > args.offset + 12000 else None}

    async def list_databases(self, args: ListDatabases):
        result = await self.mcp.call("list_databases", {})
        if isinstance(result, dict):
            result = result.get("databases", result.get("rows", []))
        names = {item if isinstance(item, str) else item.get("database", item.get("datname"))
                 for item in result}
        self.databases = {name for name in names if name} & set(CATALOG_DATABASES)
        if self.settings.allowed_databases:
            self.databases &= set(self.settings.allowed_databases)
        return {"databases": [name for name in CATALOG_DATABASES if name in self.databases]}

    def require_database(self, database: str):
        if self.databases is None or database not in self.databases:
            raise AgentError("Primeiro execute list_databases e escolha um database permitido.")

    async def has_public_access(self, database: str) -> bool:
        self.require_database(database)
        sql = ("SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
               "WHERE nspname = 'public' AND "
               "pg_catalog.has_schema_privilege(oid, 'USAGE')) AS public_access")
        result = await self.mcp.call("query", {"database": database, "sql": sql, "max_rows": 1})
        rows = result.get("rows") if isinstance(result, dict) else result
        return bool(isinstance(rows, list) and rows and isinstance(rows[0], dict)
                    and rows[0].get("public_access") is True)

    async def list_public_databases(self, args: ListPublicDatabases):
        discovered = await self.list_databases(ListDatabases())
        semaphore = asyncio.Semaphore(4)

        async def accessible(database):
            async with semaphore:
                try:
                    return database if await self.has_public_access(database) else None
                except AgentError:
                    # CONNECT descoberto não garante acesso ao schema ou disponibilidade.
                    return None

        candidates = [name for name in CATALOG_DATABASES if name in discovered["databases"]]
        names = await asyncio.gather(*(accessible(name) for name in candidates))
        self.databases = {name for name in names if name is not None}
        return {"databases": [name for name in CATALOG_DATABASES if name in self.databases]}

    async def list_tables(self, args: ListTables):
        self.require_database(args.database)
        return await self.mcp.call("list_tables", args.model_dump(by_alias=True))

    async def describe_table(self, args: DescribeTable):
        self.require_database(args.database)
        return await self.mcp.call("describe_table", args.model_dump(by_alias=True))

    async def preview_table(self, args: PreviewTable):
        tables = table_entries(await self.list_tables(ListTables(
            database=args.database, schema=args.schema_name)), args.schema_name)
        if {"table": args.table, "schema": args.schema_name} not in tables:
            raise AgentError("Tabela não encontrada no schema e database selecionados.")
        # Identificadores são delimitados individualmente; nunca interpolar SQL do cliente.
        def quote(value):
            return '"' + value.replace('"', '""') + '"'
        limit = min(10, self.settings.max_query_rows, self.settings.max_dataset_rows)
        sql = validate_sql(f"SELECT * FROM {quote(args.schema_name)}.{quote(args.table)} LIMIT {limit}")
        result = await self.mcp.call("query", {"database": args.database, "sql": sql, "max_rows": limit})
        rows = result.get("rows") if isinstance(result, dict) else result
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise AgentError("O pg_mcp não retornou uma lista de linhas compatível.")
        dataset = self.store.save_dataset(rows[:limit], {
            "kind": "postgresql", "database": args.database, "schema": args.schema_name,
            "table": args.table, "sql": sql, "max_rows": limit, "sample_only": True,
            "possibly_truncated": len(rows) >= limit or bool(isinstance(result, dict) and result.get("truncated")),
            "queried_at": now(),
        }, self.run.id if self.run else None)
        return {**preview(dataset), "sample_only": True}

    async def query(self, args: Query):
        return await self._query(args)

    async def _query(self, args: Query, source: dict | None = None):
        self.require_database(args.database)
        sql = validate_sql(args.sql)
        limit = min(args.max_rows, self.settings.max_query_rows, self.settings.max_dataset_rows)
        result = await self.mcp.call("query", {"database": args.database, "sql": sql, "max_rows": limit})
        rows = result.get("rows") if isinstance(result, dict) else result
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise AgentError("O pg_mcp não retornou uma lista de linhas compatível.")
        truncated = len(rows) >= limit or bool(isinstance(result, dict) and result.get("truncated"))
        dataset = self.store.save_dataset(rows[:limit], {
            "kind": "postgresql", "database": args.database, "sql": sql,
            **(source or {}),
            "max_rows": limit, "possibly_truncated": truncated, "queried_at": now(),
        }, self.run.id if self.run else None)
        return preview(dataset)

    async def inspect_dataset(self, args: Dataset):
        return preview(self.dataset(args.dataset_id), args.offset, args.limit)

    async def analyze_dataset(self, args: Analyze):
        dataset = self.dataset(args.dataset_id)
        frame = pd.DataFrame(dataset["rows"])
        statistics = json.loads(frame.describe(include="all").to_json()) if not frame.empty else {}
        numeric_text_columns = [column for column in frame.columns
                                if not pd.api.types.is_numeric_dtype(frame[column])
                                and not frame[column].dropna().empty
                                and pd.to_numeric(frame[column].dropna(), errors="coerce").notna().all()]
        quality = coverage(dataset["source"])
        if numeric_text_columns:
            quality["warnings"].append("Colunas com números em texto: confirme o significado e use "
                                       "to_numeric antes de calcular métricas; preserve identificadores.")
        return {"dataset_id": args.dataset_id, "row_count": len(frame),
                "null_counts": frame.isna().sum().to_dict(),
                "dtypes": frame.dtypes.astype(str).to_dict(), "statistics": statistics,
                "numeric_text_columns": numeric_text_columns,
                "source": dataset["source"], **quality}

    async def transform_dataset(self, args: Transform):
        original = self.dataset(args.dataset_id)
        frame = pd.DataFrame(original["rows"])
        for op in args.operations:
            required = set(op.columns) | set(op.aggregations)
            if op.column:
                required.add(op.column)
            missing = required - set(frame.columns)
            if missing:
                raise AgentError("Colunas não encontradas: " + ", ".join(sorted(missing))
                                 + ". Use inspect_dataset para conferir as colunas disponíveis.")
            if op.op == "select":
                frame = frame[op.columns]
            elif op.op == "drop_duplicates":
                frame = frame.drop_duplicates(subset=op.columns or None)
            elif op.op == "drop_nulls":
                frame = frame.dropna(subset=op.columns or None)
            elif op.op == "fill_nulls":
                columns = op.columns or list(frame.columns)
                frame[columns] = frame[columns].fillna(op.value)
            elif op.op == "sort":
                frame = frame.sort_values(op.columns, ascending=op.ascending)
            elif op.op == "filter":
                series = frame[op.column]
                if op.comparison == "contains":
                    mask = series.astype("string").str.contains(str(op.value), regex=False, na=False)
                else:
                    mask = getattr(series, op.comparison)(op.value)
                frame = frame[mask]
            elif op.op == "to_numeric":
                for column in op.columns:
                    try:
                        converted = pd.to_numeric(frame[column], errors="raise")
                        if (converted.isna() & frame[column].notna()).any():
                            raise ValueError("conversion lost a value")
                        if any(not math.isfinite(value) for value in converted.dropna()):
                            raise ValueError("non-finite")
                        frame[column] = converted
                    except (ValueError, TypeError):
                        raise AgentError("Conversão numérica recusada na coluna " + column
                                         + ". Há valores incompatíveis; confira os dados e o separador "
                                         "decimal. Nenhum dataset foi salvo.") from None
            elif op.op == "group":
                for column, function in op.aggregations.items():
                    if function in {"sum", "mean", "median"} and not pd.api.types.is_numeric_dtype(frame[column]):
                        raise AgentError("A agregação " + function + " exige números na coluna "
                                         + column + ". Confirme o tipo e use to_numeric ou CAST no SQL.")
                if op.columns:
                    frame = frame.groupby(op.columns, dropna=False).agg(op.aggregations).reset_index()
                else:
                    frame = pd.DataFrame([{column: frame[column].agg(function)
                                           for column, function in op.aggregations.items()}])
        dataset = self.store.save_dataset(rows_of(frame), {
            "kind": "transformation", "parent_dataset_id": args.dataset_id,
            "operations": [op.model_dump() for op in args.operations],
            "original_source": original["source"],
            "possibly_truncated": coverage(original["source"])["possibly_truncated"],
        }, self.run.id if self.run else None)
        return preview(dataset)

    async def export_dataset(self, args: Export):
        dataset = self.dataset(args.dataset_id)
        frame = pd.DataFrame(dataset["rows"])
        if args.format == "csv":
            content = safe_spreadsheet(frame).to_csv(index=False).encode("utf-8-sig")
        elif args.format == "json":
            content = encode(dataset).encode("utf-8")
        else:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                safe_spreadsheet(frame).to_excel(writer, index=False, sheet_name="Dados")
                # Também neutraliza títulos/SQL no registro de origem.
                safe_spreadsheet(pd.DataFrame([{"origem": encode(dataset["source"])}])).to_excel(
                    writer, index=False, sheet_name="Origem")
            content = buffer.getvalue()
        artifact = self.store.save_artifact(self.run.id, args.title, args.format, content)
        self.run.artifacts.append(artifact)
        return artifact

    async def create_excel_report(self, args: ExcelReport):
        datasets = [self.dataset(key) for key in args.dataset_ids]
        warnings = {dataset['id']: coverage(dataset['source'])['warnings'] for dataset in datasets}
        content = await asyncio.to_thread(build_excel, args, datasets, warnings)
        artifact = self.store.save_artifact(self.run.id, args.title, 'xlsx', content)
        self.run.artifacts.append(artifact)
        return {'artifacts': [artifact], 'warnings': [warning for values in warnings.values() for warning in values]}

    async def forecast_series(self, args: ForecastRequest):
        original = self.dataset(args.dataset_id)
        result = await asyncio.to_thread(estimate_forecast, args, original)
        dataset = self.store.save_dataset(result.pop('rows'), {
            'kind': 'forecast', 'parent_dataset_id': original['id'], 'original_source': original['source'],
            'model': args.model, 'parameters': args.model_dump(), 'diagnostics': result['diagnostics'],
            'backtest': result['backtest'], 'forecast_only': True, 'queried_at': now(),
            'analysis_warnings': result['warnings'],
            'possibly_truncated': coverage(original['source'])['possibly_truncated'],
        }, self.run.id)
        return {**preview(dataset), **result, 'warnings': coverage(original['source'])['warnings'] + result['warnings']}

    async def find_patterns(self, args: PatternRequest):
        dataset = self.dataset(args.dataset_id)
        result = await asyncio.to_thread(investigate_patterns, args, dataset)
        quality = coverage(dataset['source'])
        return {**result, 'dataset_id': dataset['id'], 'source': dataset['source'],
                'scope': quality['scope'], 'possibly_truncated': quality['possibly_truncated'],
                'warnings': quality['warnings'] + result['warnings']}

    async def create_report(self, args: Report):
        datasets = [self.dataset(key) for key in args.dataset_ids]
        chart = ""
        if args.chart_x and args.chart_y and datasets:
            frame = pd.DataFrame(datasets[0]["rows"])
            values = pd.to_numeric(frame[args.chart_y], errors="coerce")
            bars = []
            max_value = max((abs(v) for v in values if pd.notna(v) and math.isfinite(v)), default=1) or 1
            for label, value in zip(frame[args.chart_x].head(20), values.head(20)):
                if pd.notna(value) and math.isfinite(value):
                    bars.append(f'<div class="bar"><span>{escape(str(label))}</span>'
                                f'<meter min="0" max="{max_value}" value="{abs(value)}"></meter>'
                                f'<strong>{value:,.2f}</strong></div>')
            chart = ('<section><h2>' + escape(args.chart_title) + '</h2><p>' + escape(args.chart_context)
                     + '</p><p>Unidade: ' + escape(args.chart_unit or 'Não informada')
                     + '. Barras representam a magnitude; o rótulo preserva o sinal.</p>'
                     + ''.join(bars) + '</section>')
        analytical_md, analytical_html = '', ''
        by_id = {dataset['id']: dataset for dataset in datasets}
        for spec in args.tables:
            headers, values, caption = table_data(spec, by_id)
            # Escape delimitadores Markdown sem alterar o conteúdo do HTML.
            def md_cell(value):
                return value.replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ')

            analytical_md += f'\n\n## {spec.title}\n\n{spec.context}\n\n'
            analytical_md += '| ' + ' | '.join(map(md_cell, headers)) + ' |\n'
            analytical_md += '| ' + ' | '.join('---' for _ in headers) + ' |\n'
            analytical_md += ''.join('| ' + ' | '.join(map(md_cell, row)) + ' |\n' for row in values)
            analytical_md += f'\n{caption}\n\nFonte: {report_source(by_id[spec.dataset_id]["source"])}\n'
            analytical_html += ('<section><h2>' + escape(spec.title) + '</h2><p>' + escape(spec.context)
                                + '</p><table><thead><tr>' + ''.join('<th>' + escape(h) + '</th>' for h in headers)
                                + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + escape(v) + '</td>' for v in row)
                                + '</tr>' for row in values) + '</tbody></table><p>' + escape(caption) + '</p><p>Fonte: '
                                + escape(report_source(by_id[spec.dataset_id]['source'])) + '</p></section>')
        text = f"# {args.title}\n\n{args.body}\n\n## Fontes e limites\n"
        sources = list(dict.fromkeys(report_source(dataset['source']) for dataset in datasets))
        text += ''.join(f"\nFonte: {source}\n" for source in sources)
        notes = ['<p>Fonte: ' + escape(source) + '</p>' for source in sources]
        for dataset in datasets:
            warnings = coverage(dataset["source"])["warnings"]
            for warning in warnings:
                text += f"\nLimitação: {report_warning(warning)}\n"
                notes.append('<p><strong>Limitação:</strong> ' + escape(report_warning(warning)) + '</p>')
        text += analytical_md
        html = ('<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{escape(args.title)}</title><style>'
                'body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px;color:#17352f}'
                'pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;display:block;overflow:auto}'
                'td,th{padding:8px;border:1px solid #ddd}section{margin:30px 0}.bar{display:flex;gap:12px;margin:10px 0}'
                '.bar span{width:220px;overflow-wrap:anywhere}meter{flex:1}h1{font-size:32px}'
                '@media print{body{margin:0}table{font-size:10px}}</style>'
                f'<body><h1>{escape(args.title)}</h1><pre>{escape(args.body)}</pre>'
                + chart + analytical_html + ''.join(notes) + f'<footer>Gerado em {now()}</footer></body></html>')
        artifacts = [self.store.save_artifact(self.run.id, args.title, extension, content.encode("utf-8"))
                     for extension, content in (("md", text), ("html", html))]
        self.run.artifacts.extend(artifacts)
        return {"artifacts": artifacts}

    async def create_pdf_report(self, args: PDFReport):
        datasets = [self.dataset(key) for key in args.dataset_ids]
        warnings = {dataset['id']: coverage(dataset['source'])['warnings'] for dataset in datasets}
        content = build_pdf(args, datasets, warnings, now())
        artifact = self.store.save_artifact(self.run.id, args.title, 'pdf', content)
        self.run.artifacts.append(artifact)
        return {'artifacts': [artifact], 'dataset_ids': args.dataset_ids,
                'warnings': [warning for items in warnings.values() for warning in items]}
