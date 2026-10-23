'use strict';
const $ = id => document.getElementById(id);
const state = {key: '', runId: null, conversationId: null, files: [], timer: null, polling: false, run: null};
const statuses = {queued: 'Na fila', running: 'Em andamento', completed: 'Concluída', failed: 'Falhou', cancelled: 'Cancelada'};

function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.key) headers.set('Authorization', `Bearer ${state.key}`);
  const response = await fetch(path, {...options, headers});
  if (!response.ok) {
    let message = `Falha HTTP ${response.status}.`;
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : 'Verifique os campos enviados.'; } catch (_) { /* Resposta sem JSON. */ }
    if (response.status === 401) message = 'Informe a chave da aplicação em “Configurar acesso”.';
    throw new Error(message);
  }
  return response;
}
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function refreshStatus() {
  try {
    const data = await (await api('/api/status')).json();
    $('connection-label').textContent = data.llm_configured ? `IA configurada · ${data.model}` : 'IA aguardando configuração';
    $('connection-dot').className = `dot ${data.llm_configured ? '' : 'neutral'}`;
    if (!data.llm_configured) notice('Para começar, configure OPENAI_API_KEY ou OPENAI_KEY no arquivo .config/.env ou .env e reinicie o serviço.');
    else if (!data.tls_verification) notice('A configuração existente desativa a verificação TLS da conexão com a IA. Consulte a documentação para configurar o certificado.');
  } catch (error) { notice(error.message); }
}
async function history() {
  try {
    const runs = await (await api('/api/runs')).json();
    $('history').replaceChildren();
    if (!runs.length) $('history').append(el('p', 'muted', 'Seu histórico aparecerá aqui.'));
    for (const run of runs) {
      const button = el('button', `history-item${run.id === state.runId ? ' selected' : ''}`, run.prompt);
      button.type = 'button'; button.title = run.prompt; button.append(el('small', '', statuses[run.status]));
      button.addEventListener('click', () => selectRun(run));
      $('history').append(button);
    }
  } catch (error) { notice(error.message); }
}
function renderAttachments() {
  $('attachments').replaceChildren();
  for (const file of state.files) {
    const chip = el('span', 'attachment', `${file.filename} · ${file.row_count} linhas`);
    const remove = el('button', '', '×'); remove.type = 'button';
    remove.setAttribute('aria-label', `Remover ${file.filename}`);
    remove.addEventListener('click', () => {state.files = state.files.filter(item => item.id !== file.id); renderAttachments();});
    chip.append(remove); $('attachments').append(chip);
  }
}
function render(run) {
  state.run = run;
  $('welcome').hidden = true; $('conversation').hidden = false;
  $('user-message').textContent = run.prompt;
  $('run-status').textContent = statuses[run.status];
  const busy = ['queued', 'running'].includes(run.status);
  $('cancel-run').hidden = !busy; $('send').disabled = busy;
  $('answer').textContent = run.answer;
  $('run-error').hidden = !run.error; $('run-error').textContent = run.error || '';
  $('run-reference').textContent = `Execução ${run.id} · ${new Date(run.created_at).toLocaleString('pt-BR')}`;
  // Mantém os detalhes abertos durante o polling.
  const openDetails = new Set([...$('run-events').querySelectorAll('details[open]')].map(node => node.dataset.index));
  $('run-events').replaceChildren();
  run.events.forEach((event, index) => {
    if (event.kind === 'progress' && !busy) return;
    if (event.kind === 'tool_result' && event.tool === 'update_plan' && event.result.steps) {
      const plan = el('ol', 'plan-list');
      event.result.steps.forEach(step => plan.append(el('li', '', step)));
      $('run-events').append(plan); return;
    }
    if (event.kind === 'tool_result') {
      const details = el('details', 'event'); details.dataset.index = String(index); details.open = openDetails.has(String(index));
      details.append(el('summary', '', event.message), el('pre', '', JSON.stringify(event.result, null, 2)));
      $('run-events').append(details);
    } else if (event.kind !== 'tool_start') {
      $('run-events').append(el('div', `event${event.kind === 'tool_error' ? ' error' : ''}`, event.message));
    }
  });
  $('artifacts').replaceChildren();
  for (const artifact of run.artifacts) {
    const button = el('button', 'artifact'); button.type = 'button';
    button.append(el('span', 'file-type', artifact.format.toUpperCase()));
    const label = el('span'); label.append(el('strong', '', artifact.title), el('small', '', 'Baixar arquivo ↓'));
    button.append(label);
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const blob = await (await api(artifact.url)).blob();
        const url = URL.createObjectURL(blob);
        const a = el('a'); a.href = url; a.download = `relatorio-${artifact.id.slice(0, 8)}.${artifact.format}`;
        document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      } catch (error) { notice(error.message); }
      finally { button.disabled = false; }
    });
    $('artifacts').append(button);
  }
}
function stopPolling() { clearInterval(state.timer); state.timer = null; }
async function poll() {
  if (!state.runId || state.polling) return;
  const id = state.runId; state.polling = true;
  try {
    const run = await (await api(`/api/runs/${id}`)).json();
    if (state.runId !== id) return;
    render(run);
    if (!['queued', 'running'].includes(run.status)) { stopPolling(); await history(); }
  } catch (error) { if (state.runId === id) notice(error.message); }
  finally { state.polling = false; }
}
function selectRun(run) {
  stopPolling(); state.runId = run.id; state.conversationId = run.conversation_id;
  render(run); history();
  if (['queued', 'running'].includes(run.status)) state.timer = setInterval(poll, 1500);
}
$('new-run').addEventListener('click', () => {
  stopPolling(); state.runId = null; state.conversationId = null; state.run = null;
  state.files = []; renderAttachments(); $('welcome').hidden = false; $('conversation').hidden = true;
  $('send').disabled = false; $('prompt').value = ''; $('prompt').focus(); notice(); history();
});
$('refresh-history').addEventListener('click', history);
$('save-key').addEventListener('click', async () => {
  state.key = $('access-key').value.trim(); $('access-key').value = ''; notice(); await refreshStatus(); await history();
});
$('check-mcp').addEventListener('click', async () => {
  $('check-mcp').disabled = true; $('connection-label').textContent = 'Conectando ao pg_mcp…'; notice();
  try {
    const data = await (await api('/api/connections/pg-mcp')).json();
    $('connection-label').textContent = `pg_mcp conectado · ${data.tools.length} ferramentas`;
    $('connection-dot').className = 'dot';
  } catch (error) { $('connection-dot').className = 'dot bad'; $('connection-label').textContent = 'pg_mcp indisponível'; notice(error.message); }
  finally { $('check-mcp').disabled = false; }
});
$('csv-file').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  if (state.files.length >= 10) { notice('Anexe no máximo 10 arquivos por pedido.'); return; }
  event.target.disabled = true; notice('Importando o CSV…');
  try {
    const body = new FormData(); body.append('file', file);
    const data = await (await api('/api/datasets/upload', {method: 'POST', body})).json();
    state.files.push({id: data.dataset_id, filename: file.name, row_count: data.row_count});
    renderAttachments(); notice();
  } catch (error) { notice(error.message); }
  finally { event.target.value = ''; event.target.disabled = false; }
});
$('prompt-form').addEventListener('submit', async event => {
  event.preventDefault(); const prompt = $('prompt').value.trim(); if (!prompt) return;
  $('send').disabled = true; notice();
  try {
    const run = await (await api('/api/runs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({prompt, conversation_id: state.conversationId, dataset_ids: state.files.map(file => file.id)})})).json();
    selectRun(run); $('prompt').value = ''; state.files = []; renderAttachments();
  } catch (error) { notice(error.message); $('send').disabled = false; }
});
$('prompt').addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !$('send').disabled) $('prompt-form').requestSubmit();
});
$('cancel-run').addEventListener('click', async () => {
  const id = state.runId; $('cancel-run').disabled = true;
  try {
    const run = await (await api(`/api/runs/${id}/cancel`, {method: 'POST'})).json();
    if (state.runId === id) { render(run); stopPolling(); }
    await history();
  } catch (error) { notice(error.message); }
  finally { $('cancel-run').disabled = false; }
});
document.querySelectorAll('.suggestion').forEach(button => button.addEventListener('click', () => {
  $('prompt').value = button.dataset.prompt; $('prompt').focus();
}));
refreshStatus(); history();
