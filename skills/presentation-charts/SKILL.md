---
name: presentation-charts
description: Prepare gráficos e tabelas contextualizados para apresentações executivas com títulos de negócio, unidades, recortes claros e narrativa visual, em PDF ou HTML.
---

# Gráficos para apresentação

Transforme a pergunta de negócio em uma sequência curta de evidências visuais. Use datasets reais e as ferramentas `create_pdf_report`, `create_report` e, para gráficos editáveis no Excel, `create_excel_report`.

- Defina público, decisão, período e mensagem de cada visual. O título deve dizer o que se compara; só afirme crescimento, concentração ou desempenho quando os valores sustentarem a conclusão.
- Para comparação entre categorias, prefira barras ordenadas; para evolução, linha cronológica. Os gráficos PDF suportam barras ou linhas, até vinte pontos. Não solicite pizza, 3D ou eixos duplos como se fossem suportados.
- Separe unidades incompatíveis. Informe `unit`, rótulos de negócio e `context`, com período, recorte e uma frase sobre a leitura. Diferencie percentuais de pontos percentuais.
- Agregue antes de desenhar. Não esconda categorias nem chame os primeiros registros de “principais” sem ordenação confirmada. Destaque cortes, ausências e limites de amostra.
- Em PDF, leia também `pdf_report/SKILL.md`, use `charts` com contexto e `tables` com indicadores selecionados. Em HTML use `chart_title`, `chart_context`, `chart_unit`, `chart_x` e `chart_y`.
- Mantenha uma mensagem por gráfico e acrescente uma tabela analítica quando ajudar a conferir os valores. A origem interna aparece como “Banco de dados interno”; nomes técnicos ficam na rastreabilidade.
- A ferramenta entrega PDF/HTML ou XLSX, não PPTX. Se o usuário pedir slides editáveis ou PNG/SVG isolados, informe a limitação e ofereça os formatos realmente disponíveis, sem declarar um arquivo inexistente.
