# Primitives
Vanilla HTML, JS, CSS. Buttons, suggestions, composer, side panels, cards. Shared markup lives in the single page.
```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Agente SCD · Seu espaço de análise</title>
  <link rel="stylesheet" href="/static/style.css?v=2">
  <script src="/static/markdown.js" defer></script>
  <script src="/static/app.js?v=2" defer></script>
  <script src="/static/catalog.js?v=4" defer></script>
  <script src="/static/skills.js?v=2" defer></script>
  <script src="/static/imports.js" defer></script>
</head>
<body>
<a class="skip" href="#prompt">Pular para o pedido</a>
<div class="shell">
  <aside class="sidebar" aria-label="Navegação e histórico">
    <a class="brand" href="/" aria-label="Agente SCD, início"><span class="brand-mark">s</span><span>agente<span class="brand-light">scd</span><small>INTELIGÊNCIA PARA SEUS DADOS</small></span></a>
    <button id="new-run" class="new-button" type="button"><span aria-hidden="true">＋</span> Nova conversa</button>
    <div class="history-heading"><span class="side-label">CONVERSAS RECENTES</span><button id="refresh-history" class="icon-button" aria-label="Atualizar histórico">↻</button></div>
    <nav id="history" aria-label="Conversas recentes"><p class="muted">Seu histórico aparecerá aqui.</p></nav>
    <div class="sidebar-bottom"><div class="local-badge"><span class="dot"></span><span id="model-label">Carregando modelo…</span></div><p>Da pergunta à informação.<br>Da informação à decisão.</p><a href="/docs" target="_blank" rel="noopener">Documentação da API ↗</a></div>
  </aside>
  <main>
    <div class="workspace">
      <section class="workspace-head">
        <div><span class="eyebrow">SEU ASSISTENTE DE DADOS</span><h1>O que vamos descobrir hoje?</h1><p>Explore seus dados, encontre respostas e transforme análises em relatórios.</p></div>
        <nav class="workspace-choices" aria-label="Dados e skills">
          <button id="toggle-preview" class="choice-button" type="button" aria-controls="data-preview" aria-expanded="false"><span aria-hidden="true">▥</span> Escolher seus dados</button>
          <button id="toggle-imports" class="choice-button" type="button" aria-controls="imports-panel" aria-expanded="false"><span aria-hidden="true">↑</span> Importe seus dados</button>
          <button id="toggle-skills" class="choice-button" type="button" aria-controls="skills-panel" aria-expanded="false"><span aria-hidden="true">✳</span> Escolher suas skills</button>
        </nav>
      </section>
      <div id="notice" class="notice" role="status" hidden></div>
      <section id="welcome" class="welcome">
        <div class="welcome-symbol" aria-hidden="true">✳</div><h2>Uma boa análise começa<br>com uma boa pergunta.</h2><p>Descreva o que precisa. Eu busco as fontes, organizo os dados<br class="desktop-break"> e preparo uma resposta que você pode usar.</p>
        <div class="suggestions">
          <button class="suggestion" type="button" data-prompt="Use a skill Relatórios em Excel para criar um relatório profissional com resumo executivo, indicadores, tabelas e gráficos editáveis. Reutilize os dados disponíveis e confirme o período e o objetivo necessários. Use títulos e rótulos de negócio, preserve as limitações dos dados e informe apenas Banco de dados interno para fontes internas."><span class="card-icon mint" aria-hidden="true">▤</span><strong>Relatórios em Excel</strong><span>Transforme seus dados em planilhas com indicadores e gráficos.</span><span class="card-arrow" aria-hidden="true">↗</span></button>
          <button class="suggestion" type="button" data-prompt="Use a skill Encontrar padrões ocultos para investigar os dados disponíveis. Identifique associações, concentrações e valores atípicos com evidências quantitativas, gráficos e tabelas contextualizados. Diferencie hipóteses de fatos, explique os limites da amostra e não trate correlação como causalidade."><span class="card-icon peach" aria-hidden="true">⌕</span><strong>Encontrar padrões ocultos</strong><span>Investigue relações e comportamentos que merecem atenção.</span><span class="card-arrow" aria-hidden="true">↗</span></button>
          <button class="suggestion" type="button" data-prompt="Use a skill Projeções autorregressivas para avaliar uma projeção com os dados disponíveis. Confirme a variável de interesse, a frequência e o horizonte. Avalie os requisitos de VAR, VECM ou ARCH/GARCH conforme o objetivo, estime apenas um modelo compatível e apresente gráficos, tabelas, intervalos condicionais e backtest contra baseline. Não invente previsões nem substitua silenciosamente um modelo cujos requisitos falharem."><span class="card-icon lavender" aria-hidden="true">▥</span><strong>Projeções autorregressivas</strong><span>Explore cenários futuros com modelos e intervalos de previsão.</span><span class="card-arrow" aria-hidden="true">↗</span></button>
        </div>
        <div class="capabilities"><span>Dados Contextuais da Secovicred</span><span>Skills prontas para uso</span><span>Suporte a PDF, XLSX, CSV, DOCX e PPT</span></div>
      </section>
      <section id="conversation" class="conversation" aria-label="Conversa" hidden>
        <div class="message-user"><span class="message-label">VOCÊ</span><p id="user-message"></p></div>
        <div class="agent-message"><div class="agent-heading"><span class="mini-mark" aria-hidden="true">✳</span><strong>Agente SCD</strong><span id="run-status" class="status-pill"></span><button id="cancel-run" class="text-button danger" type="button" hidden>Cancelar execução</button></div>
          <div id="run-events" class="events" aria-live="polite" aria-label="Andamento da execução"></div>
          <div id="answer" class="answer"></div><div id="run-error" class="run-error" role="alert" hidden></div>
          <div id="artifacts" class="artifacts" aria-label="Arquivos gerados"></div>
          <p id="run-reference" class="run-reference"></p>
        </div>
      </section>
      <section class="composer-area" aria-label="Enviar um pedido">
        <div id="attachments" class="attachments"></div>
        <form id="prompt-form" class="composer">
          <label class="sr-only" for="prompt">O que você precisa analisar?</label>
          <textarea id="prompt" rows="3" maxlength="16000" placeholder="Ex.: Compare os resultados dos últimos meses e gere um relatório com os principais indicadores…" required></textarea>
          <div class="composer-toolbar"><div class="composer-left"><label class="attach-button" for="data-files"><span aria-hidden="true">＋</span> Anexar arquivos</label><input id="data-files" class="sr-only" type="file" accept=".pdf,.xlsx,.csv,.docx,.pptx" multiple aria-label="Anexar PDF, XLSX, CSV, DOCX ou PPTX"><span class="composer-context">Até 10 arquivos para análise</span></div><button id="send" class="send-button" type="submit">Enviar pedido <span aria-hidden="true">↑</span></button></div>
        </form>
        <div class="composer-footer"><span>As análises usam as fontes acessíveis. Confira os critérios antes de tomar decisões.</span><span>Ctrl + Enter para enviar</span></div>
      </section>
    </div>
  </main>
  <aside id="data-preview" class="data-preview" aria-label="Escolher seus dados" hidden>
    <div class="preview-heading"><h2>Escolher seus dados</h2><button id="close-preview" class="icon-button" type="button" aria-label="Fechar seletor de dados">×</button></div>
    <p class="muted">Escolha um database. Arraste uma tabela para o chat ou use Adicionar ao chat.</p>
    <label for="preview-database">Base de Dados</label><select id="preview-database"></select>
    <form id="schema-form"><label for="preview-schema">Schema</label><div class="schema-row"><input id="preview-schema" value="public" required aria-label="Schema"><button type="submit" class="secondary">Carregar</button></div></form>
    <p id="catalog-status" role="status" aria-live="polite"></p>
    <button id="retry-catalog" class="text-button" type="button" hidden>Tentar novamente</button>
    <div id="preview-tables" class="preview-tables" aria-label="Tabelas do database"></div>
    <section id="table-preview" hidden aria-label="Amostra da tabela"><h3 id="preview-title"></h3><p id="preview-scope" class="muted"></p><div id="preview-content" class="preview-content" tabindex="0" aria-label="Conteúdo da amostra"></div></section>
  </aside>
  <aside id="imports-panel" class="data-preview" aria-label="Importe seus dados" hidden>
    <div class="preview-heading"><h2>Importe seus dados</h2><button id="close-imports" class="icon-button" type="button" aria-label="Fechar importação de dados">×</button></div>
    <p class="muted">Importe XLSX, XLS ou CSV. A IA recebe uma amostra de até 20 linhas por aba, limitada a 20 mil caracteres no conjunto, para identificar os cabeçalhos e os tipos.</p>
    <label class="secondary import-file-button" for="temporary-files">Selecionar arquivos</label>
    <p id="import-limit" class="muted">Até 500 MB por arquivo.</p>
    <input id="temporary-files" class="sr-only" type="file" accept=".xlsx,.xls,.csv" multiple aria-label="Importar arquivos XLSX, XLS ou CSV temporários">
    <p class="muted">Os dados ficam disponíveis somente nesta sessão, em Parquet temporário. Nova conversa ou fechar a página encerra a sessão e remove os dados e os relatórios temporários. Baixe os arquivos que quiser guardar.</p>
    <p id="import-status" role="status" aria-live="polite"></p>
    <div id="import-results" class="import-results"></div>
  </aside>
  <aside id="skills-panel" class="data-preview" aria-label="Escolher suas skills" hidden>
    <div class="preview-heading"><h2>Escolher suas skills</h2><button id="close-skills" class="icon-button" type="button" aria-label="Fechar seletor de skills">×</button></div>
    <p class="muted">Veja as skills disponíveis e escolha qual usar no seu pedido.</p>
    <p id="skills-status" role="status" aria-live="polite"></p>
    <button id="retry-skills" class="text-button" type="button" hidden>Tentar novamente</button>
    <div id="skills-list" class="skills-list"></div>
  </aside>
</div>
</body>
</html>

```