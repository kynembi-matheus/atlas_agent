"""PDFs locais com layout paginado e gráficos vetoriais a partir de datasets reais."""
import io
import math
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from core.models import AgentError
from tools.report_sources import report_source, report_warning
from tools.report_tables import ReportTable, table_data

INK = colors.HexColor('#172b4d')
GREEN = colors.HexColor('#087e8b')
MUTED = colors.HexColor('#64748b')
PALE = colors.HexColor('#eef3fa')
ORANGE = colors.HexColor('#b85d36')


class PDFSection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=8000)


class PDFChart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_id: str
    title: str = Field(min_length=1, max_length=150)
    kind: Literal['bar', 'line'] = 'bar'
    x: str = Field(min_length=1)
    y: str = Field(min_length=1)
    unit: str = Field(default='', max_length=30)
    max_points: int = Field(default=12, ge=1, le=20)
    context: str = Field(default='', max_length=1000)


class PDFReport(BaseModel):
    """Gere PDF profissional com resumo executivo, gráficos e tabelas contextualizados.

    Antes de chamar, leia pdf_report/SKILL.md com read_doc. Dados vêm de dataset_ids reais.
    Gráficos bar/line usam colunas x/y; ordene/agregue o dataset antes. Números textuais com
    ponto decimal são aceitos nos gráficos; nulos, infinitos e valores inválidos são recusados.
    Informe período, unidade, metodologia e limitações. Não invente benchmarks ou conclusões.
    Descreva o contexto de negócio, sem nomes técnicos de tabelas ou IDs no texto.
    A origem interna é apresentada como Banco de dados interno; não há apêndice técnico.
    Use charts com context e tables com title/context/columns (key,label,unit) de negócio.
    """
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    subtitle: str = Field(default='', max_length=250)
    period: str = Field(min_length=1, max_length=150)
    summary: str = Field(min_length=1, max_length=6000)
    sections: list[PDFSection] = Field(default_factory=list, max_length=10)
    charts: list[PDFChart] = Field(default_factory=list, max_length=6)
    tables: list[ReportTable] = Field(default_factory=list, max_length=6)
    dataset_ids: list[str] = Field(min_length=1, max_length=8)
    methodology: str = Field(min_length=1, max_length=6000)
    conclusions: str = Field(default='', max_length=6000)
    table_rows: int = Field(default=0, ge=0, le=30,
                            description='Mantenha 0; inclua quadro de indicadores apenas quando solicitado.')

    @model_validator(mode='after')
    def chart_sources(self):
        if len(set(self.dataset_ids)) != len(self.dataset_ids):
            raise ValueError('dataset_ids não pode conter duplicatas.')
        if any(chart.dataset_id not in self.dataset_ids for chart in self.charts):
            raise ValueError('Cada gráfico deve referenciar um dataset de dataset_ids.')
        if any(table.dataset_id not in self.dataset_ids for table in self.tables):
            raise ValueError('Cada tabela analítica deve referenciar um dataset de dataset_ids.')
        return self


def text(value) -> str:
    return escape(str(value)).replace('\n', '<br/>')


def number(value: float) -> str:
    formatted = f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return formatted if len(formatted) <= 16 else f'{value:.2e}'.replace('.', ',')


def chart_data(chart: PDFChart, dataset: dict):
    rows = dataset['rows']
    if not rows:
        raise AgentError('Gráfico sem dados. Consulte ou selecione um dataset não vazio.')
    selected = rows[:chart.max_points]
    values, labels = [], []
    for row in selected:
        if chart.x not in row or chart.y not in row:
            raise AgentError('Colunas do gráfico não encontradas. Use inspect_dataset.')
        raw = row[chart.y]
        if raw is None or isinstance(raw, bool):
            raise AgentError('Gráfico com medida nula ou booleana. Corrija explicitamente na origem.')
        try:
            value = float(raw)
        except (ValueError, TypeError, OverflowError):
            raise AgentError('Medida do gráfico não numérica. Confirme os tipos e o separador decimal.') from None
        if not math.isfinite(value):
            raise AgentError('Gráfico com medida não finita. Corrija explicitamente na origem.')
        if row[chart.x] is None:
            raise AgentError('Gráfico com categoria nula. Defina explicitamente seu significado.')
        values.append(value)
        labels.append(str(row[chart.x]))
    if len(set(labels)) != len(labels):
        raise AgentError('Categorias repetidas no gráfico. Agregue os dados ou use chaves distintas.')
    return labels, values


def draw_chart(chart: PDFChart, dataset: dict, width: float) -> Drawing:
    labels, values = chart_data(chart, dataset)
    height = 50 + 25 * len(values) if chart.kind == 'bar' else 250
    drawing = Drawing(width, height)
    low, high = min(0, min(values)), max(0, max(values))
    if low == high:
        high = low + 1
    span = high - low
    if not math.isfinite(span):
        raise AgentError('Escala do gráfico excede o intervalo numérico suportado.')
    if chart.kind == 'bar':
        left, right = 150, width - 95
        scale = lambda value: left + (value - low) / span * (right - left)
        zero = scale(0)
        drawing.add(Line(zero, 24, zero, height - 12, strokeColor=colors.HexColor('#cbd5e1')))
        for index, (label, value) in enumerate(zip(labels, values)):
            y = height - 28 - index * 25
            short = label if len(label) <= 28 else label[:25] + '...'
            drawing.add(String(0, y, short, fontName='SCD', fontSize=8, fillColor=INK))
            end = scale(value)
            drawing.add(Rect(min(zero, end), y - 4, abs(end - zero), 14,
                             fillColor=GREEN if value >= 0 else ORANGE, strokeColor=None))
            drawing.add(String(right + 10, y, number(value), fontName='SCDBold', fontSize=8, fillColor=INK))
        drawing.add(String(left, 8, f'Escala desde zero | {chart.unit or chart.y}',
                           fontName='SCD', fontSize=8, fillColor=MUTED))
    else:
        left, bottom, right, top = 65, 88, width - 25, height - 25
        point = lambda i, value: (left + i * (right - left) / max(1, len(values) - 1),
                                 bottom + (value - low) / span * (top - bottom))
        for tick in range(5):
            value = low + span * tick / 4
            y = bottom + tick * (top - bottom) / 4
            drawing.add(Line(left, y, right, y, strokeColor=colors.HexColor('#e0e6ef')))
            drawing.add(String(left - 8, y - 3, number(value), textAnchor='end',
                               fontName='SCD', fontSize=7, fillColor=MUTED))
        previous = None
        for index, (label, value) in enumerate(zip(labels, values)):
            x, y = point(index, value)
            if previous:
                drawing.add(Line(*previous, x, y, strokeColor=GREEN, strokeWidth=2))
            drawing.add(Circle(x, y, 3, fillColor=GREEN, strokeColor=None))
            # Quatro rótulos no máximo evitam colisão.
            if index in {0, len(values) - 1, len(values) // 3, 2 * len(values) // 3}:
                short = label if len(label) <= 14 else label[:11] + '...'
                drawing.add(String(x, bottom - 20, short, textAnchor='middle',
                                   fontName='SCD', fontSize=7, fillColor=INK))
            previous = (x, y)
        drawing.add(String(left, 22, chart.unit or chart.y, fontName='SCD', fontSize=8, fillColor=MUTED))
    return drawing


def build_pdf(args: PDFReport, datasets: list[dict], warnings: dict[str, list[str]], generated_at: str) -> bytes:
    # Vera acompanha o ReportLab; independe de fontes instaladas no Windows.
    import reportlab
    font_dir = Path(reportlab.__file__).parent / 'fonts'
    for name, filename in [('SCD', 'Vera.ttf'), ('SCDBold', 'VeraBd.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    body = ParagraphStyle('SCDBody', fontName='SCD', fontSize=9, leading=14,
                          textColor=INK, spaceAfter=9, splitLongWords=True)
    small = ParagraphStyle('SCDSmall', parent=body, fontSize=7, leading=10, textColor=MUTED)
    h1 = ParagraphStyle('SCDTitle', parent=body, fontName='SCDBold', fontSize=25, leading=31, spaceAfter=14)
    h2 = ParagraphStyle('SCDHeading', parent=body, fontName='SCDBold', fontSize=13, leading=18,
                        spaceBefore=16, spaceAfter=8, keepWithNext=True)
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=45, leftMargin=45,
                                 topMargin=48, bottomMargin=48, title=args.title, author='Atlas Agent')
    story = [Paragraph('ATLAS AGENT / RELATÓRIO ANALÍTICO', small),
             Paragraph(text(args.title), h1)]
    if args.subtitle:
        story.append(Paragraph(text(args.subtitle), body))
    story.extend([Paragraph('Período: ' + text(args.period), small),
                  Paragraph('Resumo executivo', h2), Paragraph(text(args.summary), body)])
    for dataset in datasets:
        for warning in warnings[dataset['id']]:
            story.append(Paragraph('Limitação da análise: ' + text(report_warning(warning)), body))
    for section in args.sections:
        story.extend([Paragraph(text(section.title), h2), Paragraph(text(section.body), body)])
    by_id = {dataset['id']: dataset for dataset in datasets}
    for chart in args.charts:
        dataset = by_id[chart.dataset_id]
        drawing = draw_chart(chart, dataset, document.width)
        caption = (f"Fonte: {report_source(dataset['source'])}. Exibidos {min(len(dataset['rows']), chart.max_points)} "
                   f"de {len(dataset['rows'])} registros analisados, na ordem selecionada. "
                   'Rótulos longos podem estar abreviados.')
        chart_story = [Paragraph(text(chart.title), h2)]
        if chart.context:
            chart_story.append(Paragraph(text(chart.context), body))
        story.append(KeepTogether([*chart_story, drawing, Paragraph(text(caption), small)]))
    for spec in args.tables:
        headers, values, caption = table_data(spec, by_id)
        story.extend([Paragraph(text(spec.title), h2), Paragraph(text(spec.context), body)])
        rows = [[Paragraph(text(header), small) for header in headers]]
        rows.extend([[Paragraph(text(value), small) for value in row] for row in values])
        table = Table(rows, colWidths=[document.width / len(headers)] * len(headers), repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PALE),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f9fc')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7), ('LINEBELOW', (0, 0), (-1, 0), .6, GREEN),
        ]))
        story.append(table)
        if not values:
            story.append(Paragraph('Nenhum registro disponível para este recorte.', body))
        story.append(Paragraph(text(caption), small))
        story.append(Paragraph('Fonte: ' + text(report_source(by_id[spec.dataset_id]['source'])), small))
    if args.conclusions:
        story.extend([Paragraph('Conclusões e próximos passos', h2), Paragraph(text(args.conclusions), body)])
    story.extend([Paragraph('Metodologia e limites', h2), Paragraph(text(args.methodology), body)])
    for source in dict.fromkeys(report_source(dataset['source']) for dataset in datasets):
        story.append(Paragraph('Fonte: ' + text(source), small))
    for dataset in datasets:
        if args.table_rows and dataset['rows']:
            story.append(Paragraph('Detalhamento dos indicadores', h2))
            frame = pd.DataFrame(dataset['rows'])
            columns = list(frame.columns)[:6]
            rows = [[Paragraph(text(column), small) for column in columns]]
            for row in dataset['rows'][:args.table_rows]:
                cells = []
                for column in columns:
                    value = 'Ausente' if row.get(column) is None else str(row[column])
                    cells.append(Paragraph(text(value[:200] + ('...' if len(value) > 200 else '')), small))
                rows.append(cells)
            table = Table(rows, colWidths=[document.width / len(columns)] * len(columns), repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), PALE), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f9fc')]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7), ('LINEBELOW', (0, 0), (-1, 0), .6, GREEN),
            ]))
            story.append(Paragraph(f'Prévia: até {args.table_rows} linhas e 6 colunas; células longas abreviadas. '
                                   'Use CSV/Excel para os dados completos armazenados.', small))
            story.append(table)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#e0e6ef'))
        canvas.line(45, 35, A4[0] - 45, 35)
        canvas.setFont('SCD', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(45, 23, 'Atlas Agent | ' + generated_at[:10])
        canvas.drawRightString(A4[0] - 45, 23, f'Página {doc.page}')
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
