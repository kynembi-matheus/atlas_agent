'use strict';
const queriesState = {editing: null, selected: [], result: null, revision: 0, executing: false};
function selectedQueryIds() { return queriesState.selected.map(item => item.id); }
function clearQueryAttachments() { queriesState.selected = []; queriesState.result = null; $('query-result').hidden = true; renderQueryAttachments(); }
function renderQueryAttachments() {
  $('query-attachments').replaceChildren();
  for (const item of queriesState.selected) {
    const chip = el('span', 'attachment'); chip.append(historyIcon('star'), el('span', '', item.name));
    const remove = el('button'); remove.type = 'button'; remove.append(historyIcon('close'));
    remove.setAttribute('aria-label', `Remover consulta ${item.name}`);
    remove.addEventListener('click', () => { queriesState.selected = queriesState.selected.filter(query => query.id !== item.id); renderQueryAttachments(); });
    chip.append(remove); $('query-attachments').append(chip);
  }
}
function chooseQuery(item) {
  if (!selectedQueryIds().includes(item.id)) {
    if (queriesState.selected.length >= 10) { notice('Selecione no máximo 10 consultas por pedido.'); return; }
    queriesState.selected.push(item); renderQueryAttachments();
  }
  if (!$('prompt').value.trim()) $('prompt').value = 'Analise os dados das consultas favoritas selecionadas.';
  $('prompt').focus();
}
function editQuery(item = null) {
  if ($('save-query').disabled) return;
  queriesState.editing = item?.id || null;
  $('query-dialog-title').textContent = item ? 'Editar query' : 'Nova query';
  $('query-form-status').textContent = '';
  $('query-name').value = item?.name || '';
  $('query-description').value = item?.description || '';
  $('query-sql').value = item?.sql || '';
  $('query-max-rows').value = item?.max_rows || 1000;
  if (item) {
    if (![...$('query-database').options].some(option => option.value === item.database)) {
      const option = el('option', '', item.database); option.value = item.database; $('query-database').append(option);
    }
    $('query-database').value = item.database;
  }
  $('save-query').textContent = item ? 'Salvar alterações' : 'Salvar favorita';
  if (!$('query-dialog').open) $('query-dialog').showModal();
  $('query-name').focus();
  loadQueryDatabases();
}
async function loadQueries() {
  const revision = ++queriesState.revision;
  $('queries-status').textContent = 'Carregando favoritas…';
  try {
    const data = await (await api('/api/queries')).json();
    if (revision !== queriesState.revision) return;
    $('queries-list').replaceChildren();
    for (const item of data.queries) {
      const card = el('article', 'skill-card');
      registerChatDrag(card, 'query', item.id, item.name, () => chooseQuery(item));
      card.append(el('h3', '', item.name), el('p', 'muted', `${item.database} · até ${item.max_rows} linhas`));
      if (item.description) card.append(el('p', '', item.description));
      const sql = el('details'); sql.append(el('summary', '', 'Ver SQL'), el('pre', 'query-code', item.sql)); card.append(sql);
      const actions = el('div', 'query-actions');
      for (const [label, handler] of [['Usar no agente', () => chooseQuery(item)], ['Executar', () => executeFavorite(item)], ['Editar', () => editQuery(item)], ['Excluir', async () => {
        if (!window.confirm(`Excluir a consulta "${item.name}"?`)) return;
        try {
          await api(`/api/queries/${item.id}`, {method: 'DELETE'});
          if (typeof mentionRequests !== 'undefined') mentionRequests.delete('/api/queries');
          queriesState.selected = queriesState.selected.filter(query => query.id !== item.id); renderQueryAttachments();
          await loadQueries();
        } catch (error) { $('queries-status').textContent = error.message; }
      }]]) {
        const button = el('button', 'secondary', label); button.type = 'button'; button.addEventListener('click', handler); actions.append(button);
      }
      card.append(actions); $('queries-list').append(card);
    }
    $('queries-status').textContent = data.queries.length ? `${data.queries.length} consulta(s) favorita(s).` : 'Nenhuma favorita salva. Clique em Nova query para criar a primeira.';
  } catch (error) { if (revision === queriesState.revision) $('queries-status').textContent = error.message; }
}
async function executeFavorite(item) {
  if (queriesState.executing) return;
  queriesState.executing = true; queriesState.result = null;
  const sessionId = state.sessionId;
  $('query-result').hidden = false; $('query-result-title').textContent = item.name;
  $('query-result-scope').textContent = 'Executando consulta…'; $('query-result-content').replaceChildren(); $('query-result-use').disabled = true;
  try {
    const data = await (await api(`/api/queries/${item.id}/execute`, {method: 'POST'})).json();
    if (sessionId !== state.sessionId) return;
    queriesState.result = data;
    $('query-result-scope').textContent = `${data.row_count} linha(s) retornada(s). Prévia de ${data.preview.length}. ${data.possibly_truncated ? 'O limite foi atingido ou a origem indicou truncamento; trate como amostra, não como total.' : 'Respeite os filtros da consulta.'}`;
    $('query-result-use').disabled = false;
    const grid = el('table'); const head = el('tr');
    data.columns.forEach(column => head.append(el('th', '', column))); grid.append(head);
    for (const row of data.preview) {
      const tr = el('tr'); data.columns.forEach(column => tr.append(el('td', '', row[column] == null ? 'NULL' : typeof row[column] === 'object' ? JSON.stringify(row[column]) : String(row[column])))); grid.append(tr);
    }
    $('query-result-content').append(grid);
  } catch (error) { $('query-result-scope').textContent = error.message; }
  finally { queriesState.executing = false; }
}
async function loadQueryDatabases() {
  try {
    const data = await (await api('/api/connections/pg-mcp')).json();
    const current = $('query-database').value; $('query-database').replaceChildren();
    data.databases.databases.forEach(database => { const option = el('option', '', database); option.value = database; $('query-database').append(option); });
    if ([...$('query-database').options].some(option => option.value === current)) $('query-database').value = current;
  } catch (error) { $('query-form-status').textContent = `Não foi possível carregar as bases: ${error.message}`; }
}
function setQueriesOpen(open) {
  if (open) for (const [panel, toggle] of [['data-preview', 'toggle-preview'], ['skills-panel', 'toggle-skills'], ['imports-panel', 'toggle-imports']]) {
    $(panel).hidden = true; $(toggle).setAttribute('aria-expanded', 'false');
  }
  $('queries-panel').hidden = !open; $('toggle-queries').setAttribute('aria-expanded', String(open));
  document.body.classList.toggle('preview-open', open);
  if (open) { $('close-queries').focus(); loadQueries(); } else $('toggle-queries').focus();
}
function closeQueryEditor() {
  if (!$('save-query').disabled) $('query-dialog').close();
}
$('close-query-dialog').addEventListener('click', closeQueryEditor);
$('cancel-query').addEventListener('click', closeQueryEditor);
$('query-dialog').addEventListener('cancel', event => {
  if ($('save-query').disabled) event.preventDefault();
});
$('query-dialog').addEventListener('close', () => { queriesState.editing = null; });
$('toggle-queries').addEventListener('click', () => setQueriesOpen($('queries-panel').hidden));
$('close-queries').addEventListener('click', () => setQueriesOpen(false));
$('queries-panel').addEventListener('keydown', event => { if (event.key === 'Escape') setQueriesOpen(false); });
for (const id of ['toggle-preview', 'toggle-skills', 'toggle-imports']) $(id).addEventListener('click', () => {
  $('queries-panel').hidden = true; $('toggle-queries').setAttribute('aria-expanded', 'false');
});
$('new-query').addEventListener('click', () => editQuery());
$('refresh-queries').addEventListener('click', loadQueries);
$('query-form').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('save-query').disabled) return;
  $('save-query').disabled = true; $('query-form-status').textContent = 'Salvando…';
  const id = queriesState.editing;
  try {
    const item = await (await api(`/api/queries${id ? `/${id}` : ''}`, {method: id ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: $('query-name').value, database: $('query-database').value, description: $('query-description').value, sql: $('query-sql').value, max_rows: Number($('query-max-rows').value)})})).json();
    if (typeof mentionRequests !== 'undefined') mentionRequests.delete('/api/queries');
    queriesState.selected = queriesState.selected.map(query => query.id === item.id ? item : query); renderQueryAttachments();
    $('query-dialog').close(); await loadQueries();
  } catch (error) { $('query-form-status').textContent = error.message; }
  finally { $('save-query').disabled = false; }
});
$('query-result-use').addEventListener('click', () => {
  const data = queriesState.result; if (!data) return;
  if (state.files.some(file => file.id === data.dataset_id)) return;
  if (state.files.length >= 10) { notice('Anexe no máximo 10 datasets por pedido.'); return; }
  state.files.push({id: data.dataset_id, filename: $('query-result-title').textContent, row_count: data.row_count, format: 'query'}); renderAttachments();
  if (!$('prompt').value.trim()) $('prompt').value = 'Analise o resultado da consulta anexada.';
  $('prompt').focus();
});
