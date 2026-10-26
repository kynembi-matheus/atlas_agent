"""Tabelas analíticas com seleção explícita de campos e rótulos de negócio."""
import json

from pydantic import BaseModel, ConfigDict, Field

from core.models import AgentError


class ReportColumn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=100)
    unit: str = Field(default='', max_length=30)


class ReportTable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_id: str
    title: str = Field(min_length=1, max_length=150)
    context: str = Field(min_length=1, max_length=1000)
    columns: list[ReportColumn] = Field(min_length=1, max_length=6)
    max_rows: int = Field(default=12, ge=1, le=30)


def table_data(spec: ReportTable, datasets: dict) -> tuple[list[str], list[list[str]], str]:
    dataset = datasets.get(spec.dataset_id)
    if dataset is None:
        raise AgentError('A tabela analítica deve referenciar um dataset de dataset_ids.')
    selected = dataset['rows'][:spec.max_rows]
    headers = [column.label + (f' ({column.unit})' if column.unit else '') for column in spec.columns]
    rows = []
    for row in selected:
        values = []
        for column in spec.columns:
            if column.key not in row:
                raise AgentError('Coluna da tabela analítica não encontrada. Use inspect_dataset.')
            value = row[column.key]
            if value is None:
                formatted = 'Não informado'
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                formatted = (f'{value:,.2f}' if isinstance(value, float) else f'{value:,}')
                formatted = formatted.replace(',', '_').replace('.', ',').replace('_', '.')
            else:
                formatted = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            values.append(formatted)
        rows.append(values)
    caption = f'Exibidos {len(selected)} de {len(dataset["rows"])} registros analisados; o recorte não indica o total da base.'
    return headers, rows, caption
