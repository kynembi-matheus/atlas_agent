"""Ferramentas declarativas: o modelo nunca executa Python ou shell arbitrário."""
import io
import json
import math
from html import escape
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import sqlglot
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlglot import exp

from core.config import ROOT, Settings
from integrations.pg_mcp import PgMCP
from core.models import AgentError, Run
from repositories.local_store import Store, encode, now


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(Arguments):
    """Publique um plano curto de ações verificáveis antes de iniciar a análise."""
    steps: list[str] = Field(min_length=1, max_length=8)


class SearchDocs(Arguments):
    """Busque regras de negócio e fontes na documentação local. Consulta vazia lista arquivos."""
    query: str = Field(default="", max_length=300)


class ReadDoc(Arguments):
    """Leia um documento pelo caminho retornado por search_docs, em trechos de até 12000 caracteres."""
    path: str
    offset: int = Field(default=0, ge=0)


class ListDatabases(Arguments):
    """Descubra os databases permitidos antes de fazer qualquer chamada ao banco."""


class ListTables(Arguments):
    """Liste tabelas e views de um database previamente descoberto."""
    database: str
    schema_name: str = Field(default="public", alias="schema")


class DescribeTable(ListTables):
    """Inspecione colunas e tipos reais antes de escrever SQL."""
    table: str


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


class Analyze(Arguments):
    """Calcule estatísticas, tipos e valores ausentes de um dataset, sem inventar métricas."""
    dataset_id: str


class Operation(Arguments):
    op: Literal["select", "drop_duplicates", "drop_nulls", "fill_nulls", "sort", "filter", "group"]
    columns: list[str] = Field(default_factory=list, max_length=100)
    column: str | None = None
    value: str | int | float | bool | None = None
    comparison: Literal["eq", "ne", "gt", "ge", "lt", "le", "contains"] = "eq"
    ascending: bool = True
    aggregations: dict[str, Literal["sum", "mean", "min", "max", "count", "nunique", "median"]] = Field(default_factory=dict)


class Transform(Arguments):
    """Organize dados com operações sequenciais. Cria novo dataset, preservando o original.

    group usa columns como chaves e aggregations como {coluna: função}. Sem chaves, agrega o total.
    """
    dataset_id: str
    operations: list[Operation] = Field(min_length=1, max_length=12)


class Export(Arguments):
    """Exporte um dataset real para CSV, Excel ou JSON com link para download."""
    dataset_id: str
    format: Literal["csv", "xlsx", "json"]
    title: str = Field(default="Dados", max_length=150)


class Report(Arguments):
    """Gere relatório Markdown e HTML com fontes, tabelas e gráfico opcional.

    Descreva metodologia, período, conclusões e limitações no body. HTML pode ser impresso em PDF.
    chart_x e chart_y devem ser colunas do primeiro dataset; barras mostram até 20 linhas.
    """
    title: str = Field(max_length=150)
    body: str = Field(max_length=30000)
    dataset_ids: list[str] = Field(default_factory=list, max_length=8)
    chart_x: str | None = None
    chart_y: str | None = None


SCHEMAS = {
    "update_plan": Plan, "search_docs": SearchDocs, "read_doc": ReadDoc,
    "list_databases": ListDatabases, "list_tables": ListTables,
    "describe_table": DescribeTable, "query": Query, "inspect_dataset": Dataset,
    "analyze_dataset": Analyze, "transform_dataset": Transform,
    "export_dataset": Export, "create_report": Report,
}


def definitions() -> list[dict]:
    return [{"type": "function", "name": name, "description": schema.__doc__ or name,
             "parameters": schema.model_json_schema(), "strict": False}
            for name, schema in SCHEMAS.items()]


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
            "preview_only": len(frame) > limit}


def safe_spreadsheet(frame: pd.DataFrame) -> pd.DataFrame:
    # Protege valores e cabeçalhos sem alterar valores numéricos.
    def neutralize(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    return frame.map(neutralize).rename(columns=neutralize)


class Toolbox:
    def __init__(self, settings: Settings, store: Store, mcp: PgMCP, run: Run):
        self.settings, self.store, self.mcp, self.run = settings, store, mcp, run
        self.databases: set[str] | None = None

    async def call(self, name: str, arguments: dict) -> Any:
        if name not in SCHEMAS:
            raise AgentError("Ferramenta desconhecida.")
        try:
            args = SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            raise AgentError("Argumentos inválidos. Confira o schema da ferramenta.") from None
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
        for prefix, root in {"docs": self.settings.docs_dir, "pg_mcp": ROOT / "skills/pg_mcp"}.items():
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
        self.databases = {name for name in names if name}
        if self.settings.allowed_databases:
            self.databases &= set(self.settings.allowed_databases)
        return {"databases": sorted(self.databases)}

    def require_database(self, database: str):
        if self.databases is None or database not in self.databases:
            raise AgentError("Primeiro execute list_databases e escolha um database permitido.")

    async def list_tables(self, args: ListTables):
        self.require_database(args.database)
        return await self.mcp.call("list_tables", args.model_dump(by_alias=True))

    async def describe_table(self, args: DescribeTable):
        self.require_database(args.database)
        return await self.mcp.call("describe_table", args.model_dump(by_alias=True))

    async def query(self, args: Query):
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
            "max_rows": limit, "possibly_truncated": truncated, "queried_at": now(),
        }, self.run.id)
        return preview(dataset)

    async def inspect_dataset(self, args: Dataset):
        return preview(self.dataset(args.dataset_id), args.offset, args.limit)

    async def analyze_dataset(self, args: Analyze):
        dataset = self.dataset(args.dataset_id)
        frame = pd.DataFrame(dataset["rows"])
        statistics = json.loads(frame.describe(include="all").to_json()) if not frame.empty else {}
        return {"dataset_id": args.dataset_id, "row_count": len(frame),
                "null_counts": frame.isna().sum().to_dict(),
                "dtypes": frame.dtypes.astype(str).to_dict(), "statistics": statistics,
                "source": dataset["source"]}

    async def transform_dataset(self, args: Transform):
        original = self.dataset(args.dataset_id)
        frame = pd.DataFrame(original["rows"])
        for op in args.operations:
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
                    mask = series.astype(str).str.contains(str(op.value), regex=False, na=False)
                else:
                    mask = getattr(series, op.comparison)(op.value)
                frame = frame[mask]
            elif op.op == "group":
                if not op.aggregations:
                    raise AgentError("Informe aggregations para agrupar.")
                if op.columns:
                    frame = frame.groupby(op.columns, dropna=False).agg(op.aggregations).reset_index()
                else:
                    frame = pd.DataFrame([{column: frame[column].agg(function)
                                           for column, function in op.aggregations.items()}])
        dataset = self.store.save_dataset(rows_of(frame), {
            "kind": "transformation", "parent_dataset_id": args.dataset_id,
            "operations": [op.model_dump() for op in args.operations],
            "original_source": original["source"],
        }, self.run.id)
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
            chart = '<section><h2>Gráfico (magnitude; sinal no rótulo)</h2>' + ''.join(bars) + '</section>'
        text = f"# {args.title}\n\n{args.body}\n\n## Fontes e metodologia\n"
        tables = []
        for dataset in datasets:
            frame = pd.DataFrame(dataset["rows"])
            source = encode(dataset["source"])
            text += f"\nDataset: {dataset['id']} — {len(frame)} linhas\n\n```json\n{source}\n```\n"
            tables.append(f'<h2>Dados · {len(frame)} linhas (prévia de até 100)</h2>'
                          + frame.head(100).to_html(index=False, escape=True)
                          + '<h3>Origem</h3><pre>' + escape(source) + '</pre>')
        html = ('<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{escape(args.title)}</title><style>'
                'body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px;color:#17352f}'
                'pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;display:block;overflow:auto}'
                'td,th{padding:8px;border:1px solid #ddd}section{margin:30px 0}.bar{display:flex;gap:12px;margin:10px 0}'
                '.bar span{width:220px;overflow-wrap:anywhere}meter{flex:1}h1{font-size:32px}'
                '@media print{body{margin:0}table{font-size:10px}}</style>'
                f'<body><h1>{escape(args.title)}</h1><pre>{escape(args.body)}</pre>'
                + chart + ''.join(tables) + f'<footer>Gerado em {now()}</footer></body></html>')
        artifacts = [self.store.save_artifact(self.run.id, args.title, extension, content.encode("utf-8"))
                     for extension, content in (("md", text), ("html", html))]
        self.run.artifacts.extend(artifacts)
        return {"artifacts": artifacts}
