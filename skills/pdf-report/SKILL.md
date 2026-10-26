---
name: pdf-report
description: Gere relatórios profissionais em PDF no Atlas Agent com contexto de negócio, resumo executivo, gráficos, tabelas analíticas e conclusões apoiadas em dados reais. Use para pedidos de relatório em PDF ou análise pronta para compartilhar.
---

# Relatórios em PDF

Produza um arquivo legível, com hierarquia visual consistente, gráficos que respondem à pergunta e conclusões apoiadas nos dados. Use `create_pdf_report`, registrada na Toolbox. Não execute scripts ou shell pelo agente; os desenhos e a paginação são implementados pela ferramenta.

## Perfil profissional e apresentação das fontes

- Escreva para o público de negócio, com tom profissional, objetivo e natural. Explique o contexto dos dados, o significado dos indicadores e suas implicações para a decisão; evite descrever a implementação da análise.
- Use títulos como “Evolução da carteira de crédito” ou “Indicadores de cobrança”, conforme o contexto confirmado. Não cite nomes técnicos de tabelas, schemas, databases, colunas, SQL ou IDs de datasets no título, narrativa, metodologia, legendas ou conclusões. Traduza nomes de campos para termos de negócio sem inventar seu significado; se faltar uma definição essencial, confirme-a.
- Para dados consultados no PostgreSQL interno, informe apenas **“Fonte: Banco de dados interno”**. Não inclua lista de tabelas-fontes, consultas, metadados ou apêndice técnico. A rastreabilidade completa permanece armazenada internamente nos datasets e eventos.
- Inclua gráficos e tabelas analíticas que expliquem os dados disponíveis. Gráficos evidenciam comparações ou evolução; tabelas apresentam os valores e recortes relevantes. Ambos precisam de título, contexto, rótulos de negócio e unidades confirmadas. Se os dados não sustentarem um gráfico, explique o motivo sem inventar valores ou relações.
- Não exiba prévias das tabelas-fontes: mantenha `table_rows=0` e use `tables` para selecionar explicitamente os indicadores da análise. Dados completos podem ser entregues em CSV/Excel quando pedidos.
- Preserve período, critérios, unidades, denominadores e avisos sobre amostras ou limitações. Descreva-os em linguagem de negócio; simplificar a fonte não autoriza omitir ressalvas.
- A indicação “Banco de dados interno” exige origem real nesse banco. Para anexos ou fontes mistas, identifique os arquivos fornecidos quando pertinente; não os atribua ao banco interno.

## Preparar o conteúdo

- Reutilize datasets da conversa. Inspecione suas colunas e origem somente quando necessário. Faça agregações no PostgreSQL quando precisar de totais da população; transformações locais continuam limitadas às linhas armazenadas.
- Confirme período, unidade, significado da medida e denominador de percentuais. Se o período não puder ser determinado, informe explicitamente "Período não confirmado". Não confunda a data da consulta com a competência dos dados.
- Números com ponto decimal serializados como texto podem ser desenhados diretamente. Só faça conversão explícita se precisar calcular novas métricas. Preserve códigos e identificadores.
- Organize o dataset na ordem de apresentação antes de desenhar: ranking decrescente para comparação; sequência cronológica para evolução. Categorias duplicadas precisam de agregação ou de uma chave que as diferencie. Nulos e valores inválidos exigem tratamento justificado; não os substitua silenciosamente por zero.

## Construir a narrativa

Adapte a extensão à pergunta; prefira um relatório curto e útil a páginas sem informação.

1. **Título, subtítulo e período:** identifique assunto, recorte e data de referência.
2. **Resumo executivo:** apresente os principais achados, sua relevância e ressalvas. Separe observações, hipóteses e recomendações. Sem meta ou série histórica confirmada, não classifique um percentual como bom, ruim ou tendência.
3. **Seções analíticas:** explique os indicadores, os recortes e o que cada comparação permite concluir. Use os campos `sections[].title` e `sections[].body`; o conteúdo é texto simples, não Markdown ou HTML.
4. **Gráficos:** selecione apenas os que acrescentam evidência. Informe um título informativo e unidade; a legenda de origem e o recorte de linhas são inseridos automaticamente.
   Use `charts[].context` para explicar a pergunta respondida, o período e o recorte, sem repetir apenas o título.
   Inclua tabelas em `tables`, com `title`, `context`, `dataset_id`, `columns` e `max_rows`. Cada coluna usa `key` para apontar o campo interno, `label` para o nome de negócio e `unit` para a unidade. Exemplo: título “Saldo da carteira por mês”; contexto “Saldos mensais no período analisado, em reais”; colunas “Mês” e “Saldo da carteira (R$)”. Não use nomes de tabelas do banco como título ou contexto.
5. **Conclusões e próximos passos:** priorize recomendações justificadas; explicite o que falta para sustentá-las.
6. **Metodologia e limites:** registre filtros, critérios, período, denominadores, qualidade dos dados e escopo da amostra em linguagem de negócio, sem identificadores técnicos. A origem é apresentada de forma resumida, mantendo os detalhes na rastreabilidade interna.

## Escolher os gráficos

| Pergunta | `kind` | Preparação |
| --- | --- | --- |
| Quais categorias concentram maior valor? | `bar` | Uma linha por categoria, ordenada pelo indicador; até 12 barras como padrão |
| Como o indicador evoluiu? | `line` | Uma linha por período, em ordem cronológica; mesma unidade em toda a série |

- `x` identifica a coluna de categoria/período e `y` a medida. Use `unit` para `R$`, `%`, `contratos` etc. A ferramenta não converte razões em percentuais: 0,0877 continua 0,0877 até que uma transformação explícita calcule 8,77.
- Evite comparar valores monetários e percentuais no mesmo gráfico. Para métricas de saldo em um único registro, produza um dataset longo com colunas `indicador` e `percentual` por meio de SQL, em vez de pedir uma consulta por indicador.
- Gráficos mostram as primeiras `max_points` linhas (1 a 20, padrão 12), sem calcular "Outros" nem totais ocultos. A fonte informa o recorte. Para séries maiores, agregue por um período adequado ou escolha explicitamente a janela; não apresente o trecho como série completa.
- Não há gráficos 3D, eixos duplos, pizza ou rosca nesta ferramenta. Barras têm referência em zero e preservam o sinal. Cores e fontes são consistentes; gráficos vetoriais permanecem nítidos no PDF.

## Gerar e entregar

Chame `create_pdf_report` com `title`, `period`, `summary`, `methodology` e `dataset_ids`. Inclua `charts` e `tables` contextualizados conforme os dados sustentarem a análise; acrescente `subtitle`, `sections` e `conclusions`. Cada gráfico e tabela referencia internamente um dos IDs em `dataset_ids`. Tabelas permitem até seis colunas escolhidas, com rótulos e unidades de negócio, e de 1 a 30 linhas (`max_rows`, padrão 12). Mantenha o campo legado `table_rows=0` para não acrescentar prévias técnicas. Para dados completos, gere CSV/Excel com `export_dataset` quando solicitado.

Em `create_report` (HTML/Markdown), use a mesma estrutura `tables`. Para o gráfico HTML, informe `chart_x`, `chart_y`, `chart_title`, `chart_context` e `chart_unit`. O Markdown contém as tabelas analíticas; para gráficos incorporados ao documento, prefira PDF ou HTML.

Confira se a ferramenta retornou um artefato PDF antes de anunciar a entrega. Preserve e comunique os avisos de amostra. Se houver erro de coluna, tipo ou categoria duplicada, corrija o dataset e repita a geração, sem declarar o arquivo pronto antes do sucesso.

A ferramenta aplica paginação A4, fontes incorporadas, cabeçalhos de tabela repetidos, rodapé e numeração. Ela não faz inspeção visual automática após gerar cada relatório. Na manutenção do gerador, renderize PDFs de exemplo e confira títulos, acentos, gráficos, tabelas e quebras de página antes de liberar mudanças; não alegue revisão visual de um arquivo que não foi inspecionado.
