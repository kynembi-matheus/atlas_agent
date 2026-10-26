---
name: data-quality
description: Avalie qualidade e consistência dos dados, identificando ausências, duplicidades, tipos incompatíveis, cobertura e regras de negócio violadas sem alterar os originais.
---

# Qualidade e consistência dos dados

Use `analyze_dataset`, `inspect_dataset` e consultas de leitura para estabelecer o que pode ser analisado com confiança.

- Confirme granularidade, chave de negócio, competência, unidades e cobertura. Duplicidade depende da chave e do contexto; não presuma que linhas iguais são erros.
- Faça contagens de nulos, chaves repetidas e reconciliação de totais no SQL quando a questão se referir à população. Para arquivos e amostras, delimite o escopo às linhas armazenadas.
- Inspecione tipos, medidas textuais, identificadores com zeros, datas impossíveis e incompatibilidade de unidades. Nulo não é zero. Não elimine ou preencha valores silenciosamente.
- Transformações justificadas devem usar `transform_dataset` e gerar novo dataset. Preserve os dados originais e a origem. Não escreva correções no banco.
- Relacione cada achado à regra confirmada, contagem, denominador, impacto e ação sugerida. Diferencie bloqueadores de análise, ressalvas e hipóteses.
- Entregue diagnóstico profissional com tabelas e gráficos quando úteis, sem nomes técnicos de tabelas no relatório. Não prometa completude sobre uma fonte truncada ou documento parcialmente extraído.
