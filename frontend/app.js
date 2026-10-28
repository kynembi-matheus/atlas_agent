'use strict';
const $ = id => document.getElementById(id);
const appRoot = document.querySelector?.('meta[name="app-root-path"]')?.content || '';
function appUrl(path) { return appRoot + path; }
function appPath() { const path = window.location.pathname; return appRoot && (path === appRoot || path.startsWith(appRoot + '/')) ? path.slice(appRoot.length) || '/' : path; }
const state = {runId: null, conversationId: null, files: [], timer: null, polling: false, run: null, uploading: false, sessionId: null, sessionPromise: null};
const statuses = {idle: 'Sem execução', queued: 'Na fila', running: 'Em andamento', completed: 'Concluída', failed: 'Com falha', cancelled: 'Cancelada'};

function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  await ensureDataSession();
  headers.set('X-Data-Session', state.sessionId);
  const response = await fetch(appUrl(path), {...options, headers});
  if (!response.ok) {
    let message = `Falha HTTP ${response.status}.`;
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : 'Verifique os campos enviados.'; } catch (_) { /* Resposta sem JSON. */ }
    if (response.status === 401) message = 'Acesso não autorizado. Contate o administrador da aplicação.';
    throw new Error(message);
  }
  return response;
}
async function ensureDataSession() {
  if (state.sessionId) return;
  if (!state.sessionPromise) state.sessionPromise = rotateDataSession();
  try { await state.sessionPromise; }
  finally { state.sessionPromise = null; }
}
async function rotateDataSession() {
  const headers = new Headers();
  let previous = state.sessionId;
  try { previous = previous || sessionStorage.getItem('scd-import-session'); } catch (_) { /* Armazenamento do navegador indisponível. */ }
  if (previous) headers.set('X-Data-Session', previous);
  let response = await fetch(appUrl('/api/import-sessions'), {method: 'POST', headers});
  // Após troca de conta, o token anterior pode pertencer a outro usuário.
  if (previous && response.status === 410) response = await fetch(appUrl('/api/import-sessions'), {method: 'POST'});
  if (!response.ok) throw new Error('Não foi possível iniciar a sessão temporária. Atualize a página.');
  state.sessionId = (await response.json()).session_id;
  try { sessionStorage.setItem('scd-import-session', state.sessionId); } catch (_) { /* Somente o identificador, nunca dados importados. */ }
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
    $('model-label').textContent = data.model || 'Modelo não configurado';
    const webToggle = $('web-search-enabled');
    if (webToggle) {
      webToggle.disabled = data.internet_enabled === false;
      if (webToggle.disabled) webToggle.setAttribute('aria-pressed', 'false');
      webToggle.title = webToggle.disabled ? 'Pesquisa web desativada nesta instalação.' : 'Permitir pesquisa e leitura de páginas públicas neste pedido.';
    }
    if (typeof data.max_temporary_upload_bytes === 'number') {
      state.importMaxBytes = data.max_temporary_upload_bytes;
      $('import-limit').textContent = `Até ${(state.importMaxBytes / 1024 / 1024).toLocaleString('pt-BR', {maximumFractionDigits: 2})} MB por arquivo.`;
    }
    if (!data.llm_configured) notice('Para começar, configure OPENAI_API_KEY ou OPENAI_KEY no arquivo .config/.env ou .env e reinicie o serviço.');
  } catch (error) { $('model-label').textContent = 'Modelo indisponível'; notice(error.message); }
}
async function refreshHistory(options = {}) {
  const request = state.historyRequest = (state.historyRequest || 0) + 1;
  const full = ['/sessoes', '/historico'].includes(appPath());
  if (full && !options.silent) {
    $('history-feedback').textContent = 'Atualizando suas sessões…'; $('history-feedback').hidden = false;
    $('reload-history').disabled = true;
  }
  try {
    const runs = await (await api(`/api/workspace-sessions${full ? '' : '?limit=2'}`)).json();
    if (request !== state.historyRequest || full !== ['/sessoes', '/historico'].includes(appPath())) return;
    const known = new Map((state.sessionGroups || []).map(group => [group.conversation_id, group]));
    for (const group of runs) known.set(group.conversation_id, group);
    state.sessionGroups = [...known.values()];
    if (state.run) renderSessionIdentity(state.run);
    const signature = JSON.stringify([full, state.runId, runs.map(run => [run.id, run.title, run.prompt, run.status, run.created_at, run.subagents])]);
    if (state.sessionsSignature !== signature) {
      state.sessionsSignature = signature;
      $('history').replaceChildren();
      if (!runs.length) $('history').append(el('p', 'muted', 'Nenhuma sessão ainda.'));
      for (const run of runs.slice(0, 2)) {
        const selected = run.id === state.runId;
        const button = el('button', `history-item${selected ? ' selected' : ''}`);
        const title = run.title || run.prompt;
        button.type = 'button'; button.title = title;
        button.disabled = !run.id;
        button.setAttribute('aria-label', `${title} · ${statuses[run.status]}`);
        if (selected) button.setAttribute('aria-current', 'page');
        button.append(el('span', 'session-title', title),
          el('small', `session-status status-${run.status}`, statuses[run.status]));
        button.addEventListener('click', () => selectRun(run));
        $('history').append(button);
        appendSessionAgents($('history'), run, true);
      }
      if (full) {
        state.historyRuns = runs;
        renderHistoryResults();
      }
    }
    if (full) $('history-feedback').hidden = true;
    scheduleSessionsRefresh(runs);
  } catch (error) {
    if (request !== state.historyRequest) return;
    if (full) {
      $('history-feedback').textContent = `Não foi possível atualizar as sessões. ${error.message} Use Atualizar para tentar novamente.`;
      $('history-feedback').hidden = false;
    } else notice(error.message);
  } finally { if (request === state.historyRequest) $('reload-history').disabled = false; }
}
function scheduleSessionsRefresh(runs) {
  clearTimeout(state.sessionsTimer);
  state.sessionsTimer = null;
  if (!runs.some(run => ['queued', 'running'].includes(run.status) || (run.subagents || []).some(agent => ['queued', 'running'].includes(agent.status)))) return;
  state.sessionsTimer = setTimeout(() => {
    if (document.visibilityState === 'hidden') return scheduleSessionsRefresh(runs);
    return refreshHistory({silent: true});
  }, 4000);
}
function historyIcon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'ui-icon'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', appUrl(`/static/vendor/lucide/sprite.svg?v=0.468.0#icon-${name}`)); svg.append(use); return svg;
}
function sessionAgentIdentity(run) {
  for (const group of state.sessionGroups || []) {
    const agent = (group.subagents || []).find(item => item.run_id === run.id || item.id === run.agent_profile_id);
    if (agent) return {group, agent};
  }
  return null;
}
function renderSessionIdentity(run) {
  const identity = sessionAgentIdentity(run);
  $('conversation-title').textContent = identity ? `${identity.group.title} · ${identity.agent.name}` : run.title || 'Nova Conversa';
  $('conversation-title').setAttribute('data-agent-color', identity?.agent.color || '');
  if ($('session-origin')) {
    $('session-origin').hidden = !identity?.group.id;
    $('session-origin').onclick = identity?.group.id ? () => selectRun(identity.group) : null;
  }
}
function appendSessionAgents(container, group, compact = false) {
  if (!group.subagents?.length) return;
  const list = el('div', compact ? 'session-agents compact' : 'session-agents');
  list.setAttribute('aria-label', `Subagentes de ${group.title}`);
  for (const agent of group.subagents) {
    const button = el('button', `session-agent${agent.run_id === state.runId ? ' selected' : ''}`);
    button.type = 'button'; button.disabled = !agent.run_id;
    button.title = `${group.title} · ${agent.name}`;
    button.setAttribute('data-agent-color', agent.color);
    button.setAttribute('aria-label', `${group.title} · ${agent.name} · ${statuses[agent.status] || 'Disponível'}`);
    if (agent.run_id === state.runId) button.setAttribute('aria-current', 'page');
    button.append(el('span', 'agent-avatar', agent.name.slice(0, 1)), el('span', 'agent-name', agent.name),
      el('small', `session-status status-${agent.status}`, statuses[agent.status] || 'Disponível'));
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { selectRun(await (await api(`/api/runs/${agent.run_id}`)).json()); }
      catch (error) { notice(error.message); }
      finally { button.disabled = false; }
    });
    list.append(button);
  }
  container.append(list);
}
function renderHistoryResults() {
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const query = normalize(($('history-search').value || '').trim());
  const status = $('history-status').value || '';
  const all = state.historyRuns || [];
  const runs = all.filter(run => {
    const agents = run.subagents || [];
    const matches = agent => (!status || agent.status === status) && normalize(`${run.title || ''} ${agent.name} ${agent.task || ''}`).includes(query);
    return ((!status || run.status === status) && normalize(`${run.title || ''} ${run.prompt}`).includes(query)) || agents.some(matches);
  });
  const filterKey = JSON.stringify([query, status]);
  if (state.historyFilterKey !== filterKey) state.historyPage = 1;
  state.historyFilterKey = filterKey;
  const pages = Math.max(1, Math.ceil(runs.length / 5));
  const page = state.historyPage = Math.min(Math.max(1, state.historyPage || 1), pages);
  $('history-pagination').hidden = runs.length <= 5;
  $('history-page-label').textContent = `Página ${page} de ${pages}`;
  $('history-previous').disabled = page === 1;
  $('history-next').disabled = page === pages;
  $('clear-history-filters').hidden = !query && !status;
  $('history-count').textContent = query || status ? `${runs.length} de ${all.length} sessões` : `${all.length} ${all.length === 1 ? 'sessão' : 'sessões'} · Mais recentes primeiro`;
  if ($('sessions-live')) $('sessions-live').hidden = !all.some(run => ['queued', 'running'].includes(run.status) || (run.subagents || []).some(agent => ['queued', 'running'].includes(agent.status)));
  $('all-history').replaceChildren();
  if (!runs.length) {
    const empty = el('div', 'history-empty');
    empty.append(historyIcon(query || status ? 'search' : 'chat'),
      el('h2', '', all.length ? 'Nenhuma sessão encontrada' : 'Nenhuma sessão ainda.'),
      el('p', 'muted', all.length ? 'Tente outro termo ou limpe os filtros para ver suas sessões.' : 'Crie uma sessão para começar. Suas análises ficam disponíveis aqui.'));
    $('all-history').append(empty);
  }
  for (const run of runs.slice((page - 1) * 5, page * 5)) {
    const button = el('button', 'conversation-card'); button.type = 'button';
    button.disabled = !run.id;
    button.setAttribute('data-status', run.status);
    button.setAttribute('aria-label', `${run.title || run.prompt} · ${statuses[run.status]} · Abrir sessão`);
    const mark = el('span', 'conversation-mark'); mark.append(historyIcon('chat'));
    const content = el('span', 'conversation-card-content');
    const meta = el('span', 'conversation-meta');
    const badge = el('span', `conversation-status status-${run.status}`, statuses[run.status]);
    const time = el('time', 'muted', new Date(run.created_at).toLocaleString('pt-BR', {dateStyle: 'short', timeStyle: 'short'}));
    time.setAttribute('datetime', run.created_at);
    meta.append(badge, time);
    content.append(el('strong', 'conversation-title', run.title || run.prompt), meta);
    const action = el('span', 'conversation-open'); action.append(el('span', '', run.id ? 'Abrir' : 'Sessão de origem'), historyIcon('arrow'));
    button.append(mark, content, action);
    button.addEventListener('click', () => selectRun(run));
    $('all-history').append(button);
    appendSessionAgents($('all-history'), run);
  }
}
function renderHistoryPage() {
  const full = ['/sessoes', '/historico'].includes(appPath());
  $('history-page').hidden = !full;
  $('chat-page').hidden = full;
  const dashboards = appPath() === '/dashboards';
  const detail = /^\/dashboards\/[^/]+$/.test(appPath());
  for (const [id, active] of [['more-history', full], ['open-dashboards', dashboards || detail], ['open-schedules', appPath() === '/agendamentos']]) {
    const link = $(id);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute?.('aria-current');
  }
  document.body?.classList.toggle('dashboard-detail', detail);
  if (appPath() !== '/') {
    document.body?.classList.remove('preview-open');
    for (const [panel, toggle] of [['data-preview', 'toggle-preview'], ['skills-panel', 'toggle-skills'], ['imports-panel', 'toggle-imports'], ['queries-panel', 'toggle-queries']]) {
      if ($(panel)) $(panel).hidden = true;
      if ($(toggle)) $(toggle).setAttribute('aria-expanded', 'false');
    }
  }
  if ($('dashboards-page')) $('dashboards-page').hidden = !dashboards;
  if ($('dashboard-detail-page')) $('dashboard-detail-page').hidden = !detail;
  if (dashboards || detail) $('chat-page').hidden = true;
  document.title = full ? 'Sessões · Atlas Agent' : 'Atlas Agent · Seu espaço de análise';
  if (dashboards || detail) document.title = 'Dashboards · Atlas Agent';
  if (typeof renderSchedulesPage === 'function') renderSchedulesPage();
  if (typeof renderDashboardPage === 'function') return renderDashboardPage();
}
function navigatePage(path) {
  if (appPath() !== path) window.history.pushState({}, '', appUrl(path));
  return renderHistoryPage();
}
function renderAttachments() {
  $('attachments').replaceChildren();
  for (const file of state.files) {
    const unit = ['pdf', 'docx', 'pptx'].includes(file.format) ? 'trechos/linhas' : 'linhas';
    const chip = el('span', 'attachment', `${file.filename} · ${file.row_count} ${unit}`);
    const remove = el('button'); remove.type = 'button'; remove.append(historyIcon('close'));
    remove.setAttribute('aria-label', `Remover ${file.filename}`);
    remove.addEventListener('click', () => {state.files = state.files.filter(item => item.id !== file.id); renderAttachments();});
    chip.append(remove); $('attachments').append(chip);
  }
}
function renderEvents(run) {
  const container = $('run-events');
  if (container.dataset.runId !== run.id) {
    container.replaceChildren();
    container.dataset.runId = run.id;
    container.dataset.count = '0';
  }
  const followLatest = container.scrollHeight - container.scrollTop - container.clientHeight < 48;
  const count = Number(container.dataset.count);
  run.events.slice(count).forEach((event, relativeIndex) => {
    const index = count + relativeIndex;
    let node;
    if (event.kind === 'tool_result' && event.tool === 'update_plan' && event.result.steps) {
      node = el('div', 'event');
      const plan = el('ol', 'plan-list');
      event.result.steps.forEach(step => plan.append(el('li', '', step)));
      node.append(plan);
    } else if (event.kind === 'tool_result') {
      node = el('details', 'event');
      node.append(el('summary', '', event.message), el('pre', '', JSON.stringify(event.result, null, 2)));
    } else {
      node = el('div', `event${event.kind === 'tool_error' ? ' error' : ''}`, event.message);
    }
    node.dataset.index = String(index);
    container.append(node);
  });
  container.dataset.count = String(run.events.length);
  const nodes = [...container.children];
  nodes.forEach((node, index) => {
    node.classList.toggle('event-current', index === nodes.length - 1);
    node.classList.toggle('event-previous', index === nodes.length - 2);
    node.classList.toggle('event-past', index < nodes.length - 2);
    if (index === nodes.length - 1) node.setAttribute('aria-current', 'step');
    else node.removeAttribute('aria-current');
  });
  if (followLatest) container.scrollTop = container.scrollHeight;
}
function render(run) {
  state.run = run;
  if (typeof renderWorkspaceSuggestions === 'function') renderWorkspaceSuggestions(run);
  renderSessionIdentity(run);
  $('welcome').hidden = true; $('conversation').hidden = false;
  $('user-message').textContent = run.prompt;
  if ($('run-status').textContent !== statuses[run.status]) $('run-status').textContent = statuses[run.status];
  $('run-status').className = `status-pill status-${run.status}`;
  const busy = ['queued', 'running'].includes(run.status);
  $('cancel-run').hidden = !busy; $('send').disabled = busy || state.uploading;
  if ($('answer').dataset.markdown !== (run.answer || '')) {
    renderMarkdown($('answer'), run.answer);
    $('answer').dataset.markdown = run.answer || '';
  }
  $('run-error').hidden = !run.error; $('run-error').textContent = run.error || '';
  $('run-reference').textContent = `Execução ${run.id} · ${new Date(run.created_at).toLocaleString('pt-BR')}`;
  renderEvents(run);
  $('artifacts').replaceChildren();
  for (const artifact of run.artifacts) {
    if (artifact.format === 'dashboard') {
      const link = el('a', 'artifact'); link.append(historyIcon('dashboard'), el('span', '', `${artifact.title} · Abrir dashboard`));
      link.href = appUrl(artifact.url);
      link.addEventListener('click', event => { event.preventDefault(); navigatePage(artifact.url); });
      $('artifacts').append(link); continue;
    }
    const button = el('button', 'artifact'); button.type = 'button';
    button.append(el('span', 'file-type', artifact.format.toUpperCase()));
    const label = el('span'); label.append(el('strong', '', artifact.title), el('small', '', 'Baixar arquivo'));
    button.append(historyIcon('download'));
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
    if (!['queued', 'running'].includes(run.status)) { stopPolling(); await refreshHistory(); }
  } catch (error) { if (state.runId === id) notice(error.message); }
  finally { state.polling = false; }
}
function selectRun(run) {
  if (typeof resetWorkspaceUi === 'function') resetWorkspaceUi();
  navigatePage('/');
  stopPolling(); state.runId = run.id; state.conversationId = run.conversation_id;
  render(run); refreshHistory();
  if (['queued', 'running'].includes(run.status)) state.timer = setInterval(poll, 1500);
}
$('new-run').addEventListener('click', async () => {
  if (typeof resetWorkspaceUi === 'function') resetWorkspaceUi();
  if (state.uploading) return;
  $('new-run').disabled = true;
  try { await ensureDataSession(); await rotateDataSession(); }
  catch (error) { notice(error.message); return; }
  finally { $('new-run').disabled = false; }
  stopPolling(); state.runId = null; state.conversationId = null; state.run = null;
  $('conversation-title').textContent = 'Nova Conversa';
  $('conversation-title').setAttribute('data-agent-color', '');
  if ($('session-origin')) $('session-origin').hidden = true;
  if (typeof clearQueryAttachments === 'function') clearQueryAttachments();
  $('import-results').replaceChildren(); $('import-status').textContent = '';
  $('import-summary').textContent = 'Nenhum dado importado nesta sessão.';
  state.files = []; renderAttachments(); $('welcome').hidden = false; $('conversation').hidden = true;
  navigatePage('/');
  $('send').disabled = state.uploading; $('prompt').value = ''; $('prompt').focus(); notice(); refreshHistory();
});
$('more-history').addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
  event.preventDefault(); navigatePage('/sessoes'); refreshHistory(); $('history-title').focus();
});
$('back-chat').addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
  event.preventDefault(); navigatePage('/'); refreshHistory();
});
window.addEventListener('popstate', () => { renderHistoryPage(); refreshHistory(); });
$('history-search').addEventListener('input', renderHistoryResults);
$('history-previous').addEventListener('click', () => {
  state.historyPage = (state.historyPage || 1) - 1; renderHistoryResults();
});
$('history-next').addEventListener('click', () => {
  state.historyPage = (state.historyPage || 1) + 1; renderHistoryResults();
});
$('history-status').addEventListener('change', renderHistoryResults);
$('reload-history').addEventListener('click', refreshHistory);
$('clear-history-filters').addEventListener('click', () => {
  $('history-search').value = ''; $('history-status').value = ''; renderHistoryResults(); $('history-search').focus();
});
$('data-files').addEventListener('change', async event => {
  const input = event.target;
  const files = [...input.files]; if (!files.length || state.uploading) return;
  if (state.files.length + files.length > 10) { notice('Anexe no máximo 10 arquivos por pedido.'); input.value = ''; return; }
  input.disabled = true; state.uploading = true; $('send').disabled = true;
  $('new-run').disabled = true;
  const errors = [];
  try {
    for (const [index, file] of files.entries()) {
      notice(`Importando ${index + 1}/${files.length}: ${file.name}…`);
      try {
        const body = new FormData(); body.append('file', file);
        const data = await (await api('/api/datasets/upload', {method: 'POST', body})).json();
        state.files.push({id: data.dataset_id, filename: file.name, row_count: data.row_count, format: data.source.format});
        renderAttachments();
        for (const warning of data.source.extraction_warnings || []) errors.push(`${file.name}: ${warning}`);
      } catch (error) { errors.push(`${file.name}: ${error.message}`); }
    }
    notice(errors.join('\n'));
  } finally {
    input.value = ''; input.disabled = false; state.uploading = false; $('new-run').disabled = false;
    $('send').disabled = ['queued', 'running'].includes(state.run?.status);
  }
});
$('web-search-enabled').addEventListener('click', event => {
  const button = event.currentTarget;
  if (!button.disabled) button.setAttribute('aria-pressed', button.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
});
$('prompt-form').addEventListener('submit', async event => {
  event.preventDefault(); const prompt = $('prompt').value.trim(); if (!prompt || state.uploading) return;
  const requestPrompt = typeof expandChatMentions === 'function' ? expandChatMentions(prompt) : prompt;
  if (requestPrompt.length > $('prompt').maxLength) { notice('O pedido excede o limite de caracteres. Reduza o texto ou as seleções.'); return; }
  $('send').disabled = true; notice();
  try {
    const run = await (await api('/api/runs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({web_search_enabled: $('web-search-enabled')?.getAttribute('aria-pressed') === 'true' && !$('web-search-enabled')?.disabled, output_format: $('output-dashboard')?.checked ? 'dashboard' : 'auto', prompt: requestPrompt, conversation_id: state.conversationId, dataset_ids: state.files.map(file => file.id), query_ids: typeof selectedQueryIds === 'function' ? selectedQueryIds() : []})})).json();
    selectRun(run); $('prompt').value = ''; state.files = []; renderAttachments();
    if (typeof clearQueryAttachments === 'function') clearQueryAttachments();
  } catch (error) { notice(error.message); $('send').disabled = false; }
});
$('prompt').addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.isComposing || event.defaultPrevented) return;
  if (event.altKey) {
    event.preventDefault();
    const prompt = $('prompt');
    const start = prompt.selectionStart, end = prompt.selectionEnd;
    if (prompt.maxLength > 0 && prompt.value.length - (end - start) + 1 > prompt.maxLength) return;
    prompt.setRangeText('\n', start, end, 'end');
    prompt.dispatchEvent(new Event('input', {bubbles: true}));
    return;
  }
  if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !$('mention-menu').hidden) return;
  event.preventDefault();
  if (!$('send').disabled) $('prompt-form').requestSubmit();
});
$('cancel-run').addEventListener('click', async () => {
  const id = state.runId; $('cancel-run').disabled = true;
  try {
    const run = await (await api(`/api/runs/${id}/cancel`, {method: 'POST'})).json();
    if (state.runId === id) { render(run); stopPolling(); }
    await refreshHistory();
  } catch (error) { notice(error.message); }
  finally { $('cancel-run').disabled = false; }
});
document.querySelectorAll('.suggestion').forEach(button => button.addEventListener('click', () => {
  $('prompt').value = button.dataset.prompt; $('prompt').focus();
}));
renderHistoryPage(); refreshStatus(); refreshHistory();
