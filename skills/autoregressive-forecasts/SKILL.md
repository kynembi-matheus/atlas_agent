---
name: autoregressive-forecasts
description: Estime projeções VAR e VECM e volatilidade ARCH/GARCH com frequência regular, testes de pressupostos, intervalos condicionais e backtest temporal em datasets reais.
---

# Projeções autorregressivas

Use `forecast_series`, nunca cálculos inventados pelo modelo de linguagem. Defina variável de interesse, unidade, frequência, horizonte e propósito. Projeção é uma estimativa condicional, não garantia nem recomendação automática de investimento.

## Preparar as séries

- Reutilize um dataset real ou consulte um histórico agregado por período. Confirme que as séries representam a mesma população e datas. Não misture estoques e fluxos nem competências distintas.
- `date_column` deve conter datas únicas e válidas; `value_columns` aceita até cinco medidas numéricas. Confirme nomes e unidades. Faça conversões e transformações explicitamente, preservando a origem; não use identificadores como medidas.
- A ferramenta ordena o histórico e exige frequência inferível, sem lacunas, duplicatas, nulos, infinitos ou imputação automática. Aceita até 5000 observações. Séries constantes são recusadas.
- VAR/VECM exigem pelo menos duas séries e treino de no mínimo `max(60, 10*(quantidade_de_series*(lags+1)+1))` observações, além do backtest. ARCH/GARCH exigem uma série e pelo menos 120 observações de treino, além do backtest. Mínimo operacional não significa amostra estatisticamente suficiente.

## Escolher e estimar

- **VAR:** relações dinâmicas entre séries estacionárias. O ADF é verificado no treino, a 5%; o modelo precisa ser estável. `lags` define defasagens em nível.
- **VECM:** séries I(1) com relação de longo prazo. A ferramenta verifica ADF em nível e primeira diferença, estima o rank pelo teste de Johansen no treino e mantém esse rank no ajuste completo. Usa constante na relação de cointegração e `lags` como número de diferenças defasadas. Falhas nos requisitos recusam a estimação.
- **ARCH/GARCH:** variância/volatilidade de uma série estacionária, geralmente retornos ou variações confirmadas. Não use volatilidade como previsão do saldo. A média é constante; as inovações são normais. `volatility_p` e `volatility_q` definem ordens de 1 a 3; ARCH não usa q. Não interprete `lags` como ordem da média desses modelos.
- Não escolha uma família apenas pelo nome solicitado quando os pressupostos falharem. Explique a falha, proponha a preparação necessária e nunca substitua VECM por VAR ou outra família silenciosamente.
- Envie `dataset_id`, `date_column`, `value_columns`, `model`, `horizon` (1 a 24), `lags` e `backtest_steps` (1 a 24, padrão 6). Mantenha o horizonte proporcional ao histórico. As ordens são explícitas, não escolhidas automaticamente por AIC/BIC.

## Validar e comunicar

- O backtest reserva os últimos períodos sem usá-los no ajuste de treino. Compare MAE por série contra persistência para VAR/VECM e média do treino para ARCH/GARCH. Em volatilidade, confira também o erro da variância contra variância constante; resíduos ao quadrado são apenas uma proxy ruidosa da variância observada.
- O backtest é uma única janela; não declare validação robusta nem superioridade universal. Comunique desempenho pior que o baseline, avisos de estimação, autocorrelação residual e sensibilidade à especificação. VECM mantém o rank encontrado no treino; não afirma seleção ótima de defasagens ou validação completa de estabilidade estrutural.
- A saída traz dataset futuro, diagnósticos, backtest e avisos. Não confunda previsão com observação. Preserve os intervalos condicionais de 95% e explique que podem ser inadequados sob quebras estruturais ou distribuição incorreta.
- Verifique restrições de negócio: saldos negativos ou taxas fora de limites podem tornar a projeção inadequada. Não corte valores nem transforme o resultado silenciosamente; reveja a especificação e documente transformações e escala.
- Para gráficos de projeção, filtre `serie` antes de desenhar uma linha por variável; a saída longa pode conter várias séries por data. Use rótulos e unidades de negócio. Em ARCH/GARCH apresente `variancia`/`volatilidade` separadamente da média.
- Entregue relatório PDF ou Excel quando pedido, com metodologia, horizonte e limites. A origem interna é “Banco de dados interno”; mantenha histórico, parâmetros, rank e diagnósticos na rastreabilidade interna.

Referências de implementação: [VAR/VECM no statsmodels](https://www.statsmodels.org/stable/vector_ar.html) e [previsões de volatilidade no arch](https://arch.readthedocs.io/en/latest/univariate/forecasting.html).
