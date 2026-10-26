"""Exploração quantitativa limitada, com evidências e sem atribuição causal automática."""
from itertools import combinations

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from core.models import AgentError


class PatternRequest(BaseModel):
    """Investigue correlações de Spearman, valores atípicos por IQR e dados ausentes.

    Leia hidden_patterns/SKILL.md. Use de 1 a 8 medidas numéricas reais, não identificadores.
    Correlação não implica causalidade; outliers não são automaticamente erros ou fraude.
    Resultados descrevem somente o dataset fornecido e precisam de confirmação em outra amostra.
    """
    model_config = ConfigDict(extra='forbid')
    dataset_id: str
    columns: list[str] = Field(min_length=1, max_length=8)
    correlation_threshold: float = Field(default=.6, ge=0, le=1)


def investigate_patterns(args: PatternRequest, dataset: dict):
    frame = pd.DataFrame(dataset['rows'])
    if len(frame) < 20:
        raise AgentError('A busca de padrões exige pelo menos 20 observações; use análise descritiva para bases menores.')
    if len(frame) > 50000:
        raise AgentError('A busca de padrões aceita até 50000 observações.')
    if len(set(args.columns)) != len(args.columns) or not set(args.columns).issubset(frame.columns):
        raise AgentError('Selecione colunas existentes e distintas para investigar padrões.')
    selected = frame[args.columns]
    for column in args.columns:
        if not pd.api.types.is_numeric_dtype(selected[column]) or pd.api.types.is_bool_dtype(selected[column]):
            raise AgentError('A busca de padrões exige medidas numéricas; confirme o significado e converta números textuais explicitamente.')
        if not np.isfinite(selected[column].dropna().to_numpy(dtype=float)).all():
            raise AgentError('A busca de padrões recusa medidas infinitas.')
    correlations = []
    for left, right in combinations(args.columns, 2):
        pair = selected[[left, right]].dropna()
        if len(pair) < 20 or pair.nunique().min() < 2:
            continue
        value = float(pair.corr(method='spearman').iloc[0, 1])
        if np.isfinite(value) and abs(value) >= args.correlation_threshold:
            correlations.append({'left': left, 'right': right, 'spearman': value, 'observations': len(pair)})
    outliers = []
    for column in args.columns:
        series = selected[column].dropna()
        if len(series) < 20:
            continue
        q1, q3 = series.quantile([.25, .75])
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        unusual = series[(series < low) | (series > high)]
        outliers.append({'column': column, 'count': len(unusual), 'lower_fence': float(low),
                         'upper_fence': float(high), 'examples': [
                             {'row_number': int(index) + 1, 'value': float(value)}
                             for index, value in unusual.head(10).items()]})
    return {'row_count': len(frame), 'correlations': sorted(correlations, key=lambda row: -abs(row['spearman'])),
            'outliers': outliers, 'missing_counts': selected.isna().sum().to_dict(),
            'tested_pairs': len(list(combinations(args.columns, 2))),
            'warnings': ['Análise exploratória: associações não demonstram causalidade.',
                         'Valores atípicos exigem verificação de contexto; não significam erro, fraude ou risco confirmado.',
                         'Múltiplas comparações e tendências comuns podem produzir associações espúrias; valide em outra amostra.']}
