'use strict';

function setImportsOpen(open) {
  if (open) {
    $('data-preview').hidden = true; $('toggle-preview').setAttribute('aria-expanded', 'false');
    $('skills-panel').hidden = true; $('toggle-skills').setAttribute('aria-expanded', 'false');
  }
  $('imports-panel').hidden = !open;
  $('toggle-imports').setAttribute('aria-expanded', String(open));
  document.body.classList.toggle('preview-open', open);
  if (open) $('close-imports').focus();
  else $('toggle-imports').focus();
}
function showImportedDataset(data) {
  const card = el('article', 'skill-card');
  const label = `${data.source.filename} · ${data.source.sheet}`;
  const sessionId = state.sessionId;
  registerChatDrag(card, 'import', data.dataset_id, label, () => attachImportedDataset(data),
    () => state.sessionId === sessionId);
  card.append(el('h3', '', label), el('p', 'muted', `${data.row_count} linha(s) · uso temporário nesta sessão`));
  const types = el('ul', 'import-types');
  const labels = {string: 'Texto', integer: 'Inteiro', decimal: 'Decimal', boolean: 'Sim/Não', date: 'Data'};
  Object.entries(data.source.inferred_types).forEach(([column, type]) => types.append(el('li', '', `${column}: ${labels[type] || type}`)));
  card.append(types);
  if (data.preview.length) {
    const wrap = el('div', 'preview-content');
    const grid = el('table'); const head = el('tr');
    data.columns.forEach(column => head.append(el('th', '', column)));
    const thead = el('thead'); thead.append(head); grid.append(thead);
    const body = el('tbody');
    data.preview.forEach(row => {
      const tr = el('tr');
      data.columns.forEach(column => tr.append(el('td', '', row[column] === null ? 'NULL' : String(row[column]))));
      body.append(tr);
    });
    grid.append(body); wrap.append(grid); card.append(el('p', 'muted', 'Amostra de até 10 linhas dos dados importados.'), wrap);
  }
  for (const warning of data.source.extraction_warnings || []) card.append(el('p', 'muted', warning));
  const add = el('button', 'secondary', 'Usar no chat'); add.type = 'button';
  add.addEventListener('click', () => attachImportedDataset(data));
  card.append(add); $('import-results').append(card);
  $('import-summary').textContent = `${$('import-results').children.length} dataset(s) importado(s) nesta sessão.`;
}
function openImportDialog() {
  if (state.uploading) return;
  $('import-status').textContent = '';
  if (!$('import-dialog').open) $('import-dialog').showModal();
  $('temporary-files').focus();
}
function closeImportDialog() {
  if (!state.uploading) $('import-dialog').close();
}
$('new-import').addEventListener('click', openImportDialog);
$('close-import-dialog').addEventListener('click', closeImportDialog);
$('cancel-import').addEventListener('click', closeImportDialog);
$('import-dialog').addEventListener('cancel', event => { if (state.uploading) event.preventDefault(); });
function attachImportedDataset(data) {
  if (state.files.some(file => file.id === data.dataset_id)) return;
  if (state.files.length >= 10) { notice('Anexe no máximo 10 datasets por pedido.'); return; }
  state.files.push({id: data.dataset_id, filename: `${data.source.filename} · ${data.source.sheet} (temporário)`,
    row_count: data.row_count, format: data.source.format});
  renderAttachments();
}
$('toggle-imports').addEventListener('click', () => setImportsOpen($('imports-panel').hidden));
$('close-imports').addEventListener('click', () => setImportsOpen(false));
$('imports-panel').addEventListener('keydown', event => { if (event.key === 'Escape') setImportsOpen(false); });
$('temporary-files').addEventListener('change', async event => {
  const input = event.target;
  const files = [...input.files];
  if (!files.length || state.uploading) return;
  state.uploading = true; input.disabled = true;
  $('new-import').disabled = true; $('cancel-import').disabled = true; $('close-import-dialog').disabled = true;
  $('send').disabled = true; $('new-run').disabled = true; $('data-files').disabled = true;
  const errors = [];
  try {
    for (const file of files) {
      const limit = state.importMaxBytes || 500 * 1024 * 1024;
      if (file.size > limit) { errors.push(`${file.name}: excede o limite de ${(limit / 1024 / 1024).toLocaleString('pt-BR')} MB por arquivo.`); continue; }
      if (state.files.length >= 10) { errors.push(`${file.name}: limite de 10 datasets no pedido.`); break; }
      $('import-status').textContent = `Importando ${file.name}: identificando cabeçalhos e tipos com IA…`;
      try {
        const body = new FormData(); body.append('file', file);
        const result = await (await api(`/api/imports?max_datasets=${10 - state.files.length}`, {method: 'POST', body})).json();
        result.datasets.forEach(data => { showImportedDataset(data); attachImportedDataset(data); });
      } catch (error) { errors.push(`${file.name}: ${error.message}`); }
    }
    $('import-status').textContent = errors.length ? errors.join('\n') : 'Dados importados e adicionados ao pedido. Confira a amostra e os tipos antes de analisar.';
    if (!errors.length) {
      $('import-dialog').close();
      setImportsOpen(true);
    }
  } finally {
    state.uploading = false; input.value = ''; input.disabled = false;
    $('new-import').disabled = false; $('cancel-import').disabled = false; $('close-import-dialog').disabled = false;
    $('new-run').disabled = false; $('data-files').disabled = false;
    $('send').disabled = ['queued', 'running'].includes(state.run?.status);
  }
});
window.addEventListener('pagehide', () => {
  if (state.sessionId) fetch('/api/import-sessions/current', {method: 'DELETE',
    headers: {'X-Data-Session': state.sessionId}, keepalive: true}).catch(() => {});
});
window.addEventListener('pageshow', event => {
  if (event.persisted) window.location.reload();
});
