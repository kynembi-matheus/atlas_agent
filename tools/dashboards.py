"""Dashboards HTML declarativos: dados escapados e consultas reproduzíveis."""
import math
from html import escape
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.dashboard_identity import dashboard_owner
from core.models import AgentError
from repositories.dashboards import Dashboards
from repositories.local_store import now
from tools.report_sources import report_source, report_warning


class Widget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    dataset_id: str
    kind: Literal['metric', 'table', 'bar', 'line', 'donut'] = 'bar'
    columns: dict[str, str] = Field(default_factory=dict, max_length=12)
    numeric_columns: list[str] = Field(default_factory=list, max_length=12,
                                      description='Medidas numéricas da tabela para notação K/Mi/Bi/Tri; nunca anos, códigos ou documentos.')
    value_column: str | None = None
    label_column: str | None = None
    unit: str = Field(default='', max_length=40)
    max_rows: int = Field(default=20, ge=1, le=100)
    aggregation: Literal['sum', 'mean', 'count', 'min', 'max'] | None = Field(
        default=None, description='Agregação após filtros; gráficos agrupam por label_column.')

    @model_validator(mode='after')
    def required_columns(self):
        if self.kind == 'table' and self.aggregation:
            raise ValueError('Tabelas não aceitam aggregation.')
        if self.aggregation and self.kind != 'metric' and self.label_column == self.value_column:
            raise ValueError('Agrupamento e medida devem usar colunas distintas.')
        if self.kind != 'table' and not self.value_column:
            raise ValueError('Informe value_column.')
        if self.kind in {'bar', 'line', 'donut'} and not self.label_column:
            raise ValueError('Informe label_column.')
        if self.kind == 'table' and not self.columns:
            raise ValueError('Informe columns com rótulos de negócio.')
        return self


class DashboardFilter(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    label: str = Field(min_length=1, max_length=100)
    dataset_id: str
    column: str = Field(min_length=1, max_length=150)
    kind: Literal['select', 'text'] = 'select'


class Dashboard(BaseModel):
    """Crie dashboard HTML na biblioteca do usuário (máximo 4).

    Use datasets reais do banco ou importados. Atualização automática repete a consulta e
    transformações; importações expiram com a sessão. metric exige exatamente uma linha:
    agregue antes no SQL ou transform_dataset. Nunca forneça HTML ou JavaScript arbitrário.
    Priorize cards metric e gráficos bar, line (evolução temporal), donut (composição).
    Use pouco texto: títulos curtos, description opcional curta e tabelas complementares.
    Em tabelas, informe numeric_columns para valores e quantidades; preserve identificadores e anos.
    Leia dashboard/SKILL.md para filtros dinâmicos. filters permite select ou text por dataset.
    Use aggregation nos widgets para recalcular indicadores após filtrar, antes de max_rows.
    """
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default='', max_length=2000)
    widgets: list[Widget] = Field(min_length=1, max_length=12)
    filters: list[DashboardFilter] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def filter_targets(self):
        if len({f.id for f in self.filters}) != len(self.filters):
            raise ValueError('IDs de filtros devem ser únicos.')
        if any(f.dataset_id not in {w.dataset_id for w in self.widgets} for f in self.filters):
            raise ValueError('Filtros devem apontar para datasets dos widgets.')
        return self


def recipe(toolbox, dataset_id, depth=0):
    if depth > 12:
        raise AgentError('Encadeamento de fontes muito longo para atualização automática.')
    dataset = toolbox.dataset(dataset_id)
    source = dataset['source']
    kind = source.get('kind')
    if kind == 'postgresql':
        return {'kind': kind, 'database': source['database'], 'sql': source['sql'],
                'max_rows': source['max_rows'], 'sample_only': source.get('sample_only', False)}
    if kind == 'transformation':
        return {'kind': kind, 'operations': source['operations'],
                'parent': recipe(toolbox, source['parent_dataset_id'], depth + 1)}
    if 'original_source' in source:
        raise AgentError('Use dados consultados ou importados, sem projeções, neste dashboard.')
    return {'kind': 'dataset', 'dataset_id': dataset_id}


def validate_widget(widget, dataset):
    columns = set(dataset.get('columns', [])) | {key for row in dataset['rows'] for key in row}
    required = set(widget.columns) | set(widget.numeric_columns) | {c for c in (widget.value_column, widget.label_column) if c}
    if dataset['rows'] and not required <= columns:
        raise AgentError('As colunas do dashboard mudaram ou não existem na fonte.')
    if widget.kind == 'metric' and not widget.aggregation and len(dataset['rows']) > 1:
        raise AgentError('Indicadores exigem uma linha agregada; agregue os dados primeiro.')
    if widget.kind != 'table':
        for row in (dataset['rows'] if widget.aggregation else dataset['rows'][:widget.max_rows]):
            try:
                value = float(row[widget.value_column])
                if not math.isfinite(value):
                    raise ValueError
                if widget.kind == 'donut' and value < 0:
                    raise AgentError('Gráfico de rosca exige valores não negativos.')
            except (ValueError, TypeError, KeyError):
                raise AgentError('Indicador ou gráfico contém valor não numérico ou ausente.') from None


async def create_dashboard(toolbox, args):
    sources = {}
    for field in args.filters:
        validate_filter(field, toolbox.dataset(field.dataset_id))
    for widget in args.widgets:
        validate_widget(widget, toolbox.dataset(widget.dataset_id))
        if widget.dataset_id not in sources:
            sources[widget.dataset_id] = recipe(toolbox, widget.dataset_id)
    library = Dashboards(toolbox.query_store)
    item = library.create(dashboard_owner.get(), {**args.model_dump(), 'sources': sources})
    result = {'id': item['id'], 'title': item['title'], 'format': 'dashboard',
              'url': f"/dashboards/{item['id']}", 'refresh_seconds': 60}
    if toolbox.run:
        toolbox.run.artifacts.append(result)
    return result


class RefreshStore:
    """Resultados de refresh não acumulam datasets persistentes ou temporários."""
    def __init__(self, store):
        self.base = store
        self.persistent = getattr(store, 'persistent', store)
        self.datasets = {}

    def get_dataset(self, key):
        return self.datasets.get(key) or self.base.get_dataset(key)

    def save_dataset(self, rows, source, run_id=None):
        item = {'id': str(uuid4()), 'rows': rows, 'source': source, 'created_at': now()}
        self.datasets[item['id']] = item
        return item


async def refresh(toolbox, item, selections=None):
    from tools.data_tools import ListDatabases, Query, Transform

    async def resolve(source):
        if source['kind'] == 'postgresql':
            if toolbox.databases is None:
                await toolbox.list_databases(ListDatabases())
            result = await toolbox._query(Query(**{k: source[k] for k in ('database', 'sql', 'max_rows')}),
                                          {'sample_only': source.get('sample_only', False)})
            return toolbox.dataset(result['dataset_id'])
        if source['kind'] == 'transformation':
            parent = await resolve(source['parent'])
            result = await toolbox.transform_dataset(Transform(dataset_id=parent['id'], operations=source['operations']))
            return toolbox.dataset(result['dataset_id'])
        return toolbox.dataset(source['dataset_id'])

    datasets = {key: await resolve(source) for key, source in item['sources'].items()}
    spec = Dashboard.model_validate({k: item[k] for k in ('title', 'description', 'widgets', 'filters') if k in item})
    return render_html(spec, datasets, selections, root_path=toolbox.settings.app_root_path)


def validate_filter(field, dataset):
    columns = set(dataset.get('columns', [])) | {key for row in dataset['rows'] for key in row}
    if columns and field.column not in columns:
        raise AgentError('A coluna do filtro não existe na fonte.')


def filtered_datasets(spec, datasets, selections):
    if not isinstance(selections, dict) or set(selections) - {f.id for f in spec.filters}:
        raise AgentError('Filtros desconhecidos ou inválidos.')
    if any(not isinstance(value, str) or len(value) > 500 for value in selections.values()):
        raise AgentError('Valores de filtros devem ser textos de até 500 caracteres.')
    result = dict(datasets)
    for field in spec.filters:
        validate_filter(field, datasets[field.dataset_id])
        value = selections.get(field.id, '')
        if not value:
            continue
        dataset = result[field.dataset_id]
        def matches(row, field=field, value=value):
            cell = row.get(field.column)
            if cell is None:
                return False
            return (str(cell) == value if field.kind == 'select'
                    else value.casefold() in str(cell).casefold())
        result[field.dataset_id] = {**dataset, 'rows': [row for row in dataset['rows'] if matches(row)]}
    return result


def aggregate_widget(widget, dataset):
    if not widget.aggregation or not dataset['rows']:
        return dataset
    groups = {}
    for row in dataset['rows']:
        label = row[widget.label_column] if widget.kind != 'metric' else None
        groups.setdefault(label, []).append(float(row[widget.value_column]))
    def reduce(values):
        return {'sum': sum, 'mean': lambda v: sum(v) / len(v), 'count': len,
                'min': min, 'max': max}[widget.aggregation](values)
    rows = [{**({widget.label_column: label} if widget.kind != 'metric' else {}),
             widget.value_column: reduce(values)} for label, values in groups.items()]
    return {**dataset, 'rows': rows}


PALETTE = ('#087e8b', '#172b4d', '#7c5cc4', '#e1ab51', '#d87575', '#5faeac')


def number(value):
    numeric = float(value)
    units = ((1, ''), (1e3, 'K'), (1e6, 'Mi'), (1e9, 'Bi'), (1e12, 'Tri'))
    index = 0
    while index + 1 < len(units) and abs(numeric) >= units[index + 1][0]:
        index += 1
    if index + 1 < len(units) and abs(round(numeric / units[index][0], 2)) >= 1000:
        index += 1
    scale, suffix = units[index]
    result = f'{numeric / scale:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    if suffix:
        result = result.rstrip('0').rstrip(',')
    return result + (f' {suffix}' if suffix else '')


def chart_html(widget, rows):
    values = [float(row[widget.value_column]) for row in rows]
    labels = [str(row[widget.label_column]) for row in rows]
    if widget.kind == 'line':
        low, high = min(0, min(values)), max(values)
        scale = (high - low) or 1
        points = [(48 + i * 460 / max(1, len(values) - 1), 208 - (value - low) / scale * 180)
                  for i, value in enumerate(values)]
        body = '<svg class="line-chart" viewBox="0 0 540 250" role="img" aria-label="' + escape(widget.title) + '">'
        for i in range(5):
            y = 208 - i * 45
            body += (f'<line x1="48" x2="508" y1="{y}" y2="{y}" class="grid-line"/>'
                     f'<text x="42" y="{y + 4}" text-anchor="end">{escape(number(low + scale * i / 4))}</text>')
        coordinates = ' '.join(f'{x:.2f},{y:.2f}' for x, y in points)
        body += f'<polyline points="{coordinates}" fill="none" stroke="{PALETTE[0]}" stroke-width="3"/>'
        for (x, y), label, value in zip(points, labels, values):
            body += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{PALETTE[0]}" tabindex="0"><title>{escape(label)}: {number(value)} {escape(widget.unit)}</title></circle>'
        body += f'<text x="48" y="238">{escape(labels[0][:25])}</text><text x="508" y="238" text-anchor="end">{escape(labels[-1][:25])}</text></svg>'
        return body
    if widget.kind == 'donut':
        total = sum(values)
        if not math.isfinite(total):
            raise AgentError('Os valores excedem a escala numérica do gráfico.')
        if total == 0:
            return '<p class="empty">Sem participação: todos os valores são zero.</p>'
        body = '<div class="donut-layout"><svg viewBox="0 0 220 220" class="donut" role="img" aria-label="' + escape(widget.title) + '">'
        offset = 0
        for i, (label, value) in enumerate(zip(labels, values)):
            fraction = value / total * 100
            body += (f'<circle cx="110" cy="110" r="80" fill="none" stroke="{PALETTE[i % len(PALETTE)]}" stroke-width="26" pathLength="100" '
                     f'stroke-dasharray="{fraction:.6f} {100 - fraction:.6f}" stroke-dashoffset="{-offset:.6f}" transform="rotate(-90 110 110)" tabindex="0">'
                     f'<title>{escape(label)}: {number(value)} {escape(widget.unit)} ({fraction:.1f}%)</title></circle>')
            offset += fraction
        body += '<text x="110" y="108" text-anchor="middle">COMPOSIÇÃO</text>'
        body += f'<text class="donut-count" x="110" y="134" text-anchor="middle">{len(values)} grupos</text></svg><ul class="legend">'
        for i, (label, value) in enumerate(zip(labels, values)):
            body += f'<li><svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="{PALETTE[i % len(PALETTE)]}"/></svg><span>{escape(label)}</span><strong>{number(value)} {escape(widget.unit)}</strong></li>'
        return body + '</ul></div>'
    low, high = min(0, min(values)), max(0, max(values))
    scale = (high - low) or 1
    zero = -low / scale * 260
    body = '<div class="bars">'
    for label, value in zip(labels, values):
        end = (value - low) / scale * 260
        body += (f'<div class="bar"><span>{escape(label)}</span><svg viewBox="0 0 260 24" role="img" aria-label="{escape(label)}: {number(value)}">'
                 f'<rect x="0" y="3" width="260" height="18" rx="5" class="bar-track"/>'
                 f'<rect x="{min(zero, end):.3f}" y="3" width="{abs(end - zero):.3f}" height="18" rx="3" fill="{PALETTE[0] if value >= 0 else PALETTE[4]}"/>'
                 f'<line x1="{zero:.3f}" x2="{zero:.3f}" y1="0" y2="24" class="zero-line"/></svg><strong>{number(value)} {escape(widget.unit)}</strong></div>')
    return body + '</div>'


def render_html(spec, datasets, selections=None, *, root_path=''):
    from tools.data_tools import coverage
    selections = selections or {}
    filtered = filtered_datasets(spec, datasets, selections)
    controls = ''
    for field in spec.filters:
        value = selections.get(field.id, '')
        controls += f'<label>{escape(field.label)}'
        attrs = f'data-dashboard-filter="{escape(field.id)}"'
        if field.kind == 'select':
            options = sorted({str(row[field.column]) for row in datasets[field.dataset_id]['rows']
                              if row.get(field.column) is not None and str(row[field.column])})
            if value and value not in options:
                options.append(value)
            controls += f'<select {attrs}><option value="">Todos</option>'
            controls += ''.join(f'<option value="{escape(option)}"' + (' selected' if option == value else '')
                                + f'>{escape(option)}</option>' for option in options)
            controls += '</select>'
        else:
            controls += f'<input type="search" maxlength="500" {attrs} value="{escape(value)}">'
        controls += '</label>'
    if controls:
        controls = ('<form class="dashboard-filters" data-dashboard-filters>' + controls
                    + '<button type="submit">Aplicar filtros</button><button type="reset">Limpar filtros</button></form>')
    sections = []
    for index, widget in enumerate(spec.widgets):
        dataset = filtered[widget.dataset_id]
        validate_widget(widget, dataset)
        dataset = aggregate_widget(widget, dataset)
        validate_widget(widget, dataset)
        rows = dataset['rows'][:widget.max_rows]
        body = '<p class="empty">Sem dados</p>'
        if rows and widget.kind == 'metric':
            body = f'<strong class="metric">{number(rows[0][widget.value_column])}<small>{escape(widget.unit)}</small></strong>'
        elif rows and widget.kind == 'table':
            body = (f'<div class="table-tools"><label for="search-{index}" class="sr-only">Buscar em {escape(widget.title)}</label>'
                    f'<input id="search-{index}" type="search" placeholder="Buscar nas linhas exibidas…" data-table-search></div>'
                    '<div class="scroll"><table><thead><tr>')
            body += ''.join(f'<th scope="col" aria-sort="none"><button type="button" data-sort="{i}">{escape(label)} ↕</button></th>' for i, label in enumerate(widget.columns.values())) + '</tr></thead><tbody>'
            for row in rows:
                body += '<tr>'
                for key in widget.columns:
                    value = row.get(key)
                    raw = '' if value is None else str(value)
                    try:
                        display = number(value) if key in widget.numeric_columns and value is not None else raw
                    except (ValueError, TypeError, OverflowError):
                        raise AgentError('Coluna numérica da tabela contém valores incompatíveis.') from None
                    body += f'<td data-value="{escape(raw)}">{escape(display)}</td>'
                body += '</tr>'
            body += ('</tbody></table></div><div class="table-pagination"><button type="button" data-prev aria-label="Página anterior">←</button>'
                     '<span data-page-status role="status"></span><button type="button" data-next aria-label="Próxima página">→</button></div>')
        elif rows:
            body = chart_html(widget, rows)
        quality = coverage(dataset['source'])
        sample = quality['possibly_truncated'] or dataset['source'].get('sample_only')
        badge = '<span class="sample">Amostra · não representa totais</span>' if sample else ''
        metadata = (f'<details class="source"><summary>Fonte e limites · {len(rows)}/{len(dataset["rows"])} linhas</summary>'
                    f'<p>{escape(report_source(dataset["source"]))}</p>')
        metadata += ''.join(f'<p>{escape(report_warning(warning))}</p>' for warning in quality['warnings']) + '</details>'
        sections.append(f'<section class="widget widget-{widget.kind}" data-widget="{index}"><div class="widget-heading"><h2>{escape(widget.title)}</h2>{badge}</div>{body}{metadata}</section>')
    ordered = sorted(zip(spec.widgets, sections), key=lambda pair: {'metric': 0, 'table': 2}.get(pair[0].kind, 1))
    return ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(spec.title)}</title><link rel="stylesheet" href="{escape(root_path, quote=True)}/static/dashboard.css">'
            f'<script src="{escape(root_path, quote=True)}/static/dashboard-runtime.js" defer></script></head><body>'
            f'<header><div><span class="eyebrow">DASHBOARD</span><h1>{escape(spec.title)}</h1>'
            + (f'<p class="description">{escape(spec.description)}</p>' if spec.description else '')
            + f'</div><small class="live">● Atualizado <time datetime="{escape(now())}">{escape(now()[11:19])} UTC</time></small></header>'
            + controls + '<main>' + ''.join(section for _, section in ordered) + '</main></body></html>')
