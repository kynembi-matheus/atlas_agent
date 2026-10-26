---
name: comparative-analysis
description: Compare períodos, unidades ou segmentos com indicadores reconciliados, variações absolutas e relativas e recortes equivalentes em relatórios profissionais.
---

# Análise comparativa

Use consultas agregadas, `transform_dataset`, `analyze_dataset` e os geradores de relatórios para explicar diferenças entre períodos ou segmentos.

- Confirme se as bases têm mesma definição, granularidade, período de exposição, moeda e população. Não compare mês parcial com mês completo sem destacar o efeito.
- Calcule totais e denominadores no SQL. Diferencie saldo em uma data de fluxo no período. Não some estoques de datas distintas como se fossem um total de produção.
- Mostre valores de cada recorte, diferença absoluta e variação relativa. Se a base de comparação for zero, marque variação relativa como não definida; não invente infinito nem crescimento percentual.
- Distinga percentuais de pontos percentuais. Ao comparar taxas, informe numerador e denominador; médias de taxas exigem ponderação adequada.
- Investigue mudanças de composição, sazonalidade e cobertura antes de atribuir diferenças a desempenho. Associação temporal não identifica causa.
- Use barras para grupos e linhas para evolução, com tabelas analíticas para conferência. Ordene categorias e datas explicitamente.
- Entregue leitura executiva, evidências, ressalvas e próximos passos, citando apenas “Banco de dados interno” para as fontes internas. Para Excel leia `excel_report/SKILL.md`; para PDF leia `pdf_report/SKILL.md`.
