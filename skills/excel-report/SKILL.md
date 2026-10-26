---
name: excel-report
description: Crie relatórios profissionais em Excel com resumo executivo, abas analíticas, filtros, formatação e gráficos editáveis a partir de datasets reais.
---

# Relatórios em Excel

Use `create_excel_report` para relatórios gerenciais em XLSX. Para uma simples extração completa, use `export_dataset` e comunique que se trata de dados exportados, não de um relatório editorial.

- Confirme assunto, período, unidades e indicadores; reutilize datasets da conversa. Agregue no SQL quando precisar dos totais da população. Não trate uma amostra como base completa.
- Envie `title`, `period`, `summary`, `dataset_ids` e `sheets`. Cada aba exige `dataset_id`, `title`, `context` e `columns` com `key` interno, `label` de negócio e `unit` quando pertinente.
- Escolha até seis abas, vinte colunas por aba e até 10000 linhas por aba, com limite de 30000 linhas no conjunto. O padrão é 1000 linhas por aba. Informe o recorte; para extrato completo use uma exportação separada.
- Para um gráfico editável, use `chart=bar` para comparações ou `chart=line` para evolução, com `category_key` e `value_key` presentes nas colunas da aba. O gráfico usa até vinte registros, sem agregação implícita. Ordene e agregue antes; séries cronológicas precisam de ordem temporal.
- Medidas do gráfico devem ser números reais no dataset. Quando estiverem em texto, confirme o significado e faça `to_numeric` explicitamente. Preserve documentos, códigos e identificadores como texto.
- Use rótulos como “Saldo da carteira (R$)” e “Participação (%)”. A unidade `%` apenas rotula os valores; uma razão 0,12 não vira 12 automaticamente.
- O relatório inclui resumo, filtros e congelamento de cabeçalhos. Não crie fórmulas arbitrárias; a ferramenta neutraliza textos que poderiam virar fórmulas.
- Descreva a origem interna apenas como “Banco de dados interno”. Não inclua SQL, nomes de tabelas ou IDs no texto editorial. Preserve os metadados internamente e identifique anexos corretamente.
- Só anuncie a entrega depois de receber o artefato XLSX. Não declare que houve inspeção no Excel se o arquivo não foi aberto.
