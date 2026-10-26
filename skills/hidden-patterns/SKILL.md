---
name: hidden-patterns
description: Investigue padrões pouco evidentes nos dados com correlações de Spearman, valores atípicos, concentração e hipóteses verificáveis, sem confundir associação com causalidade.
---

# Encontrar padrões ocultos

Use `find_patterns` para evidências quantitativas reproduzíveis, complementando `analyze_dataset`, consultas agregadas e contexto de negócio. Não prometa encontrar padrões se os dados não os sustentarem.

- Defina primeiro a unidade de análise, período e pergunta. Linhas de uma mesma pessoa ou contrato podem não ser independentes; não trate repetição como nova evidência.
- Escolha de uma a oito medidas numéricas em `columns`, excluindo identificadores e códigos. São necessárias ao menos vinte observações; o limite é 50000. Converta números textuais explicitamente, sem alterar o original.
- A ferramenta calcula correlações de Spearman apenas para pares com ao menos vinte valores completos e variabilidade. `correlation_threshold` tem padrão 0,6. Reporte coeficiente, sinal, quantidade de observações e pares investigados; não apresente o resultado como teste causal ou significância confirmada.
- Valores atípicos são identificados por cercas de 1,5 vezes o intervalo interquartil; verifique se refletem erro, evento legítimo ou mistura de populações. IQR zero não autoriza diagnosticar ausência de anomalias.
- Para concentração, recorrência e diferenças por segmento, faça consultas agregadas no SQL e confronte tamanho dos grupos, denominadores e cobertura. Não calcule totais da população sobre uma amostra truncada.
- Tendências comuns, sazonalidade, seleção de variáveis e múltiplas comparações podem produzir associações espúrias. Proponha confirmação em período ou amostra independente e hipóteses alternativas.
- Entregue achado, evidência, possível explicação, limite e próximo teste. Se não houver evidência, diga isso. Não rotule casos como fraude ou risco confirmado sem validação específica.
- Apresente gráficos e tabelas analíticas contextualizados, com origem “Banco de dados interno” quando aplicável; preserve a rastreabilidade técnica internamente.
