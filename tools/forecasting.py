"""Projeções limitadas e reproduzíveis, sem execução de código fornecido pelo modelo."""
import warnings
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.models import AgentError


class ForecastRequest(BaseModel):
    """Estime VAR, VECM, ARCH ou GARCH em histórico regular de um dataset real.

    Leia autoregressive_forecasts/SKILL.md. VAR exige séries estacionárias; VECM exige
    séries I(1) cointegradas; ARCH/GARCH estimam volatilidade de uma série estacionária.
    Datas únicas, números finitos, até 5000 observações, sem imputação automática.
    Retorna dataset de projeções, intervalos condicionais e backtest temporal contra baseline.
    """
    model_config = ConfigDict(extra='forbid')
    dataset_id: str
    date_column: str
    value_columns: list[str] = Field(min_length=1, max_length=5)
    model: Literal['VAR', 'VECM', 'ARCH', 'GARCH']
    horizon: int = Field(default=6, ge=1, le=24)
    lags: int = Field(default=1, ge=1, le=6)
    volatility_p: int = Field(default=1, ge=1, le=3)
    volatility_q: int = Field(default=1, ge=1, le=3)
    backtest_steps: int = Field(default=6, ge=1, le=24)

    @model_validator(mode='after')
    def validate_columns(self):
        if len(set(self.value_columns)) != len(self.value_columns) or self.date_column in self.value_columns:
            raise ValueError('Selecione medidas distintas da coluna de datas.')
        if self.model in {'VAR', 'VECM'} and len(self.value_columns) < 2:
            raise ValueError('VAR/VECM exigem pelo menos duas séries.')
        if self.model in {'ARCH', 'GARCH'} and len(self.value_columns) != 1:
            raise ValueError('ARCH/GARCH exigem exatamente uma série de medidas ou retornos estacionários.')
        return self


def prepare_history(args: ForecastRequest, dataset: dict):
    frame = pd.DataFrame(dataset['rows'])
    required = [args.date_column, *args.value_columns]
    if not set(required).issubset(frame.columns):
        raise AgentError('Colunas da projeção não encontradas. Use inspect_dataset.')
    if len(frame) > 5000:
        raise AgentError('A projeção aceita até 5000 observações. Agregue a frequência explicitamente.')
    if pd.api.types.is_numeric_dtype(frame[args.date_column]):
        raise AgentError('Informe datas explícitas, não códigos ou números na coluna temporal.')
    dates = pd.to_datetime(frame[args.date_column], errors='coerce', utc=True)
    if dates.isna().any() or dates.duplicated().any():
        raise AgentError('Datas ausentes, inválidas ou repetidas. Agregue e confirme o calendário da série.')
    for column in args.value_columns:
        if not pd.api.types.is_numeric_dtype(frame[column]) or pd.api.types.is_bool_dtype(frame[column]):
            raise AgentError('A projeção exige medidas numéricas. Confirme os campos e use to_numeric explicitamente.')
    values = frame[args.value_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise AgentError('A projeção recusa medidas ausentes ou não finitas; trate os dados explicitamente.')
    order = np.argsort(dates.to_numpy())
    dates = pd.DatetimeIndex(dates.iloc[order])
    values = values[order]
    minimum = max(60, 10 * (len(args.value_columns) * (args.lags + 1) + 1))
    if args.model in {'ARCH', 'GARCH'}:
        minimum = 120
    if len(values) - args.backtest_steps < minimum:
        raise AgentError(f'Histórico insuficiente: são necessárias {minimum} observações de treino, além do backtest.')
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='A future version of pandas will return a BaseOffset.*')
        frequency = pd.infer_freq(dates)
    if frequency is None:
        raise AgentError('A série não tem frequência regular. Resolva lacunas e confirme a periodicidade antes de projetar.')
    if np.any(np.std(values, axis=0) == 0):
        raise AgentError('Séries constantes não permitem estimar este modelo.')
    return dates, values, getattr(frequency, 'freqstr', frequency)


def estimate_forecast(args: ForecastRequest, dataset: dict) -> dict:
    from arch import arch_model
    from statsmodels.tsa.api import VAR
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.tsa.vector_ar.vecm import VECM, select_coint_rank

    dates, values, frequency = prepare_history(args, dataset)
    train, actual = values[:-args.backtest_steps], values[-args.backtest_steps:]
    diagnostics = {'observations': len(values), 'training_observations': len(train),
                   'frequency': frequency, 'lags': args.lags, 'adf_training_pvalues': {}}
    notes = ['Projeções condicionais ao histórico fornecido; não são garantias nem relações causais.',
             'Intervalos de 95% dependem dos pressupostos do modelo; não incorporam todos os riscos.',
             'Backtest de uma única janela temporal; não substitui validação em múltiplas janelas.']
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always')
            for index, column in enumerate(args.value_columns):
                pvalue = float(adfuller(train[:, index], autolag='AIC', result_object=False)[1])
                diagnostics['adf_training_pvalues'][column] = pvalue
                if args.model != 'VECM' and pvalue >= .05:
                    raise AgentError('O teste ADF não sustenta estacionariedade. Prepare a série explicitamente ou avalie VECM; nenhum modelo foi substituído.')
                if args.model == 'VECM':
                    difference_p = float(adfuller(np.diff(train[:, index]), autolag='AIC', result_object=False)[1])
                    diagnostics.setdefault('adf_difference_pvalues', {})[column] = difference_p
                    if pvalue < .05 or difference_p >= .05:
                        raise AgentError('Os testes não sustentam séries I(1) para VECM. Revise a especificação; não há fallback automático.')
            rank = None
            if args.model == 'VECM':
                rank = int(select_coint_rank(train, det_order=0, k_ar_diff=args.lags, signif=.05).rank)
                if not 0 < rank < len(args.value_columns):
                    raise AgentError('O teste de Johansen não sustenta um rank de cointegração válido para VECM.')
                diagnostics['cointegration_rank_training'] = rank

            def fit_forecast(history, horizon):
                if args.model == 'VAR':
                    fitted = VAR(history).fit(args.lags, trend='c')
                    if not fitted.is_stable():
                        raise AgentError('O VAR estimado não é estável; projeção recusada.')
                    predicted, low, high = fitted.forecast_interval(history[-args.lags:], steps=horizon, alpha=.05)
                    return predicted, low, high, None, fitted
                if args.model == 'VECM':
                    fitted = VECM(history, k_ar_diff=args.lags, coint_rank=rank, deterministic='ci').fit()
                    predicted, low, high = fitted.predict(steps=horizon, alpha=.05)
                    return predicted, low, high, None, fitted
                model = arch_model(history[:, 0], mean='Constant', vol=args.model,
                                   p=args.volatility_p, q=args.volatility_q if args.model == 'GARCH' else 0,
                                   dist='normal', rescale=False)
                fitted = model.fit(disp='off', show_warning=False, options={'maxiter': 500})
                if fitted.convergence_flag != 0:
                    raise AgentError('O modelo de volatilidade não convergiu. Revise escala e especificação.')
                prediction = fitted.forecast(horizon=horizon, reindex=False, method='analytic')
                mean = prediction.mean.iloc[-1].to_numpy().reshape(-1, 1)
                variance = prediction.variance.iloc[-1].to_numpy().reshape(-1, 1)
                std = np.sqrt(variance)
                return mean, mean - 1.95996398454 * std, mean + 1.95996398454 * std, variance, fitted

            tested, _, _, tested_variance, _ = fit_forecast(train, args.backtest_steps)
            baseline = np.repeat(train[-1:], len(actual), axis=0)
            if args.model in {'ARCH', 'GARCH'}:
                baseline[:] = train.mean(axis=0)
            backtest = {'steps': len(actual), 'baseline': 'média do treino' if tested_variance is not None else 'último valor observado',
                        'mae_by_series': {}, 'baseline_mae_by_series': {}}
            for index, column in enumerate(args.value_columns):
                error = float(np.mean(np.abs(actual[:, index] - tested[:, index])))
                reference = float(np.mean(np.abs(actual[:, index] - baseline[:, index])))
                backtest['mae_by_series'][column] = error
                backtest['baseline_mae_by_series'][column] = reference
                if error >= reference:
                    notes.append('O modelo não superou o baseline no erro absoluto em uma das séries nesta janela.')
            if tested_variance is not None:
                squared_residuals = (actual - train.mean(axis=0)) ** 2
                backtest['variance_mse'] = float(np.mean((squared_residuals - tested_variance) ** 2))
                backtest['constant_variance_baseline_mse'] = float(np.mean((squared_residuals - train.var(axis=0)) ** 2))
                notes.append('ARCH/GARCH projetam variância e volatilidade; a média constante não é uma tendência de nível. Intervalos assumem inovações normais.')
            predicted, low, high, variance, fitted = fit_forecast(values, args.horizon)
            if not all(np.isfinite(array).all() for array in [predicted, low, high]):
                raise AgentError('A estimação produziu valores não finitos. Nenhuma projeção foi salva.')
            if variance is not None and (not np.isfinite(variance).all() or (variance < 0).any()):
                raise AgentError('A estimação produziu variância inválida.')
            if hasattr(fitted, 'test_whiteness'):
                residual_lags = max(args.lags + 2, 10)
                diagnostics['residual_whiteness_pvalue'] = float(fitted.test_whiteness(nlags=residual_lags).pvalue)
                if diagnostics['residual_whiteness_pvalue'] < .05:
                    notes.append('Resíduos apresentam autocorrelação; a especificação precisa ser revisada.')
            if captured:
                diagnostics['estimation_warning_types'] = sorted({type(item.message).__name__ for item in captured})
                notes.append('A biblioteca emitiu avisos de estimação; revise os diagnósticos antes de utilizar a projeção.')
    except AgentError:
        raise
    except (ValueError, np.linalg.LinAlgError, OverflowError, ZeroDivisionError, RuntimeError):
        raise AgentError('Não foi possível estimar o modelo com esta especificação. Revise histórico, escala, colinearidade e defasagens.') from None
    future = pd.date_range(start=dates[-1], periods=args.horizon + 1, freq=frequency)[1:]
    rows = []
    for step, date in enumerate(future):
        for index, column in enumerate(args.value_columns):
            row = {'data': date.isoformat(), 'serie': column, 'projecao': float(predicted[step, index]),
                   'limite_inferior_95': float(low[step, index]), 'limite_superior_95': float(high[step, index])}
            if variance is not None:
                row.update(variancia=float(variance[step, index]), volatilidade=float(np.sqrt(variance[step, index])))
            rows.append(row)
    return {'rows': rows, 'model': args.model, 'diagnostics': diagnostics, 'backtest': backtest,
            'warnings': list(dict.fromkeys(notes))}
