"""Descrições editoriais de origem; os metadados completos permanecem nos datasets."""


def report_source(source: dict) -> str:
    while isinstance(source.get('original_source'), dict):
        source = source['original_source']
    if source.get('kind') == 'postgresql':
        return 'Banco de dados interno'
    if source.get('filename'):
        return f"Arquivo enviado: {source['filename']}"
    return 'Dados fornecidos para análise'


def report_warning(warning: str) -> str:
    if warning.startswith('Origem possivelmente truncada:'):
        return ('A análise considera uma amostra limitada. Os indicadores calculados sobre essa '
                'amostra não representam totais da população. Confirme os resultados na base completa.')
    return warning
