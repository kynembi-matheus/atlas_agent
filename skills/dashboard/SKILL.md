---
name: dashboard
description: Crie dashboards HTML com indicadores, gráficos, tabelas e filtros dinâmicos sobre datasets reais usando create_dashboard.
---

# Criação de dashboard

Use `create_dashboard` para salvar na biblioteca do usuário. Forneça apenas a especificação declarativa, sem HTML ou JavaScript. Priorize indicadores e gráficos com títulos curtos e unidades explícitas.

## Filtros dinâmicos

- Declare `filters` com `id` único (letras minúsculas, números e sublinhado; comece por letra), `label`, `dataset_id`, `column` e `kind`: `select` para categorias exatas ou `text` para busca parcial sem distinguir maiúsculas. O valor vazio significa Todos.
- As opções são extraídas do dataset atualizado, antes do limite visual `max_rows`. Filtros do mesmo dataset são combinados com E e afetam todos os widgets que o utilizam. Datasets diferentes não são cruzados automaticamente.
- Preserve no dataset as dimensões que o usuário precisa filtrar. Evite agregar no SQL ou em transformações de forma que essas dimensões desapareçam. A filtragem acontece depois da consulta e das transformações existentes, antes da agregação dos widgets e de `max_rows`.
- Declare `aggregation` (`sum`, `mean`, `count`, `min`, `max`) nos indicadores e gráficos que precisam recalcular medidas. Cards `metric` agregam as linhas filtradas; gráficos agrupam por `label_column`. `count` conta linhas e ainda exige uma `value_column` numérica válida; use uma coluna constante numérica quando necessário. Tabelas não aceitam `aggregation`. Sem agregação, cards continuam exigindo no máximo uma linha.
- Não calcule médias de médias nem some percentuais ou saldos de datas diferentes sem uma definição de negócio válida. Para razões ponderadas e métricas não suportadas, prepare uma fonte adequada ou informe a limitação.
- Seleções são mantidas durante o refresh automático da página aberta; Limpar filtros restaura o recorte completo disponível. Busca textual usa Aplicar filtros ou Enter; seletores aplicam ao mudar. Nenhum resultado mostra Sem dados.
- Filtros operam sobre o dataset retornado, sem alterar SQL. Não recuperam linhas excluídas pela consulta nem ampliam uma amostra. Preserve origem e avisos de limites; nunca apresente uma amostra filtrada como total do banco.

Exemplo de especificação (substitua `dataset-real` pelo ID retornado pela consulta):

```json
{
  "title": "Carteira por PA",
  "filters": [{"id": "pa", "label": "PA", "dataset_id": "dataset-real", "column": "pa", "kind": "select"}],
  "widgets": [
    {"title": "Saldo", "dataset_id": "dataset-real", "kind": "metric", "value_column": "saldo", "aggregation": "sum", "unit": "R$"},
    {"title": "Saldo por produto", "dataset_id": "dataset-real", "kind": "bar", "label_column": "produto", "value_column": "saldo", "aggregation": "sum", "unit": "R$"}
  ]
}
```

A biblioteca aceita até quatro dashboards por perfil. Fontes importadas dependem da sessão ativa; fontes do banco repetem a consulta e transformações a cada atualização. Nunca afirme que verificou dados ou interações que não executou.
