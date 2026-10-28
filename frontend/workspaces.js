'use strict';
const workspaceUi = {conversationId: null, timer: null, revision: 0, openRequest: 0, pending: null, delegating: false};

async function ensureWorkspace() {
  if (state.conversationId) return state.conversationId;
  if (!workspaceUi.pending) workspaceUi.pending = (async () => {
    await ensureDataSession();
    const session = state.sessionId;
    const result = await (await api('/api/workspaces', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})).json();
    if (session !== state.sessionId || state.conversationId) throw new Error('A sessão mudou. Abra a opção novamente.');
    state.conversationId = result.conversation_id;
    return state.conversationId;
  })();
  try { return await workspaceUi.pending; }
  finally { workspaceUi.pending = null; }
}
function resetWorkspaceUi() {
  $('schedule-chat').hidden = true;
  workspaceUi.approved = false; workspaceUi.plan = null;
  workspaceUi.revision++; workspaceUi.openRequest++; clearInterval(workspaceUi.timer); workspaceUi.timer = null;
  for (const id of ['schedule-dialog', 'subagents-dialog', 'delegate-dialog']) if ($(id).open) $(id).close();
}
async function openWorkspaceDialog(kind, proposal = null) {
  const openRequest = ++workspaceUi.openRequest;
  const feedback = $(`${kind}-feedback`);
  feedback.textContent = '';
  try {
    const draft = proposal?.prompt || $('prompt').value.trim() || state.run?.prompt || '';
    const prompt = typeof expandChatMentions === 'function' ? expandChatMentions(draft) : draft;
    if (kind === 'schedule' && prompt.length < 3) throw new Error('Escreva o pedido que deseja agendar no chat.');
    const scheduleOptions = {dataset_ids: (state.files || []).map(file => file.id), query_ids: typeof selectedQueryIds === 'function' ? selectedQueryIds() : [], output_format: $('output-dashboard').checked ? 'dashboard' : 'auto', web_search_enabled: $('web-search-enabled').getAttribute('aria-pressed') === 'true' && !$('web-search-enabled').disabled};
    const id = kind === 'subagents' && state.run?.origin_conversation_id ? state.run.origin_conversation_id : await ensureWorkspace();
    if (openRequest !== workspaceUi.openRequest) return;
    resetWorkspaceUi(); workspaceUi.conversationId = id;
    workspaceUi.sourceRunId = proposal?.source_run_id || state.run?.id || null;
    workspaceUi.viewConversationId = state.conversationId;
    const revision = workspaceUi.revision;
    if (kind !== 'schedule') $(`${kind}-dialog`).showModal();
    if (kind === 'schedule') {
      workspaceUi.approved = false; workspaceUi.plan = null;
      $('schedule-chat').hidden = false; $('schedule-chat-feedback').textContent = '';
      $('schedule-frequency').value = 'once'; $('schedule-days').hidden = true;
      for (const input of $('schedule-days').querySelectorAll('input')) input.checked = false;
      $('schedule-form').hidden = true; $('schedule-plan-review').hidden = false;
      $('confirm-schedule-plan').disabled = true;
      $('schedule-plan-steps').replaceChildren();
      $('schedule-plan-prompt').textContent = prompt;
      $('schedule-context').textContent = 'Preparando o planejamento…';
      const result = await (await api(`/api/workspaces/${id}/schedules/plan`, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt, source_run_id: workspaceUi.sourceRunId, ...scheduleOptions})})).json();
      if (revision !== workspaceUi.revision) return;
      workspaceUi.plan = {...result, options: scheduleOptions};
      workspaceUi.sourceRunId = result.source_run_id;
      $('schedule-plan-prompt').textContent = result.prompt;
      for (const step of result.steps) $('schedule-plan-steps').append(el('li', '', step));
      $('schedule-context').textContent = 'Revise o pedido e confirme o plano para configurar o agendamento.';
      $('schedule-proposal-reason').textContent = proposal?.reason || '';
      $('schedule-proposal-reason').hidden = !proposal?.reason;
      const date = proposal?.suggested_run_at ? new Date(proposal.suggested_run_at) : new Date(Date.now() + 3600000);
      $('schedule-at').value = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      $('schedule-timezone').textContent = `Fuso horário: ${Intl.DateTimeFormat().resolvedOptions().timeZone}.`;
      $('confirm-schedule-plan').disabled = false;
      $('confirm-schedule-plan').focus();
    } else {
      await loadSubagents();
    }
    if (revision !== workspaceUi.revision || !$(`${kind}-dialog`).open) return;
    workspaceUi.timer = setInterval(() => {
      if (document.hidden) return;
      if (state.conversationId !== workspaceUi.viewConversationId) return resetWorkspaceUi();
      if ($('subagents-dialog').open) loadSubagents();
    }, 4000);
  } catch (error) {
    if ($(`${kind}-dialog`).open) feedback.textContent = error.message;
    else if (kind === 'schedule') $('schedule-chat-feedback').textContent = error.message;
    else notice(error.message);
  }
}
function workspaceBadge(status) {
  const labels = {idle: 'Disponível', pending: 'Agendada', dispatching: 'Iniciando', queued: 'Na fila',
    running: 'Em andamento', completed: 'Concluída', failed: 'Com falha', cancelled: 'Cancelada'};
  return el('span', `conversation-status status-${status}`, labels[status] || status);
}
async function loadSchedules() {
  $('schedules-feedback').textContent = '';
  try {
    const data = await (await api('/api/schedules')).json();
    if ((typeof appPath === 'function' ? appPath() : window.location.pathname) !== '/agendamentos') return;
    $('schedule-list').replaceChildren();
    if (!data.schedules.length) $('schedule-list').append(el('p', 'muted', 'Nenhuma tarefa agendada.'));
    for (const item of data.schedules) {
      const card = el('article', 'workspace-card');
      const heading = el('div', 'workspace-card-heading'); heading.append(el('strong', '', item.title), workspaceBadge(item.status));
      card.append(heading, el('p', 'muted', new Date(item.run_at).toLocaleString('pt-BR')));
      const labels = {once: 'Uma vez', daily: 'Diariamente', weekly: 'Semanalmente'};
      const days = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
      card.append(el('p', 'muted', `${labels[item.frequency || 'once']} ${(item.weekdays || []).map(day => days[day]).join(', ')} · ${item.timezone || 'America/Sao_Paulo'}`), el('p', '', item.prompt));
      if (item.error) card.append(el('p', 'muted', item.error));
      if (item.last_status) card.append(el('p', 'muted', `Última execução: ${item.last_status}`));
      if (item.status === 'pending') {
        const cancel = el('button', 'text-button danger', 'Cancelar agendamento'); cancel.type = 'button';
        cancel.addEventListener('click', async () => {
          cancel.disabled = true;
          try { await api(`/api/schedules/${item.id}/cancel`, {method: 'POST'}); await loadSchedules(); }
          catch (error) { $('schedules-feedback').textContent = error.message; cancel.disabled = false; }
        }); card.append(cancel);
      }
      if (item.last_run_id || ['running', 'completed', 'failed'].includes(item.status)) {
        const open = el('button', 'secondary', 'Abrir execução'); open.type = 'button';
        open.addEventListener('click', async () => {
          try { const run = await (await api(`/api/runs/${item.last_run_id || item.run_id}`)).json(); resetWorkspaceUi(); selectRun(run); }
          catch (error) { $('schedules-feedback').textContent = error.message; }
        }); card.append(open);
      }
      $('schedule-list').append(card);
    }
  } catch (error) { if ((typeof appPath === 'function' ? appPath() : window.location.pathname) === '/agendamentos') $('schedules-feedback').textContent = error.message; }
}
async function loadSubagents() {
  const revision = workspaceUi.revision, id = workspaceUi.conversationId;
  try {
    const data = await (await api(`/api/workspaces/${id}/subagents`)).json();
    if (revision !== workspaceUi.revision || !$('subagents-dialog').open) return;
    $('subagents-count').textContent = `${data.subagents.length} de 2 subagentes nesta sessão`;
    const signature = JSON.stringify(data.subagents);
    if ($('subagents-list').dataset.signature === signature) return;
    $('subagents-list').dataset.signature = signature;
    $('subagents-list').replaceChildren();
    if (!data.subagents.length) $('subagents-list').append(el('p', 'muted', 'Nenhum subagente nesta sessão.'));
    for (const [index, item] of data.subagents.entries()) {
      const card = el('button', 'workspace-card agent-card'); card.type = 'button';
      card.setAttribute('data-agent-color', index === 0 ? 'teal' : 'violet');
      const heading = el('div', 'workspace-card-heading');
      heading.append(el('strong', '', item.name), workspaceBadge(item.status));
      card.append(heading, el('p', 'muted', item.task || 'Nenhuma tarefa em execução.'));
      card.disabled = !item.run_id;
      card.addEventListener('click', async () => {
        try {
          const run = await (await api(`/api/runs/${item.run_id}`)).json();
          resetWorkspaceUi(); selectRun(run);
        } catch (error) { $('subagents-feedback').textContent = error.message; }
      });
      $('subagents-list').append(card);
    }
  } catch (error) { if (revision === workspaceUi.revision) $('subagents-feedback').textContent = error.message; }
}
$('open-schedule').addEventListener('click', () => openWorkspaceDialog('schedule'));
function updateScheduleSummary() {
  const frequency = $('schedule-frequency').value;
  $('schedule-days').hidden = frequency !== 'weekly';
  $('schedule-at-label').textContent = frequency === 'once' ? 'Data e horário' : 'Primeira execução';
  const date = new Date($('schedule-at').value);
  const days = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
  const selected = [...$('schedule-days').querySelectorAll('input:checked')].map(input => Number(input.value));
  const cadence = frequency === 'daily' ? 'Todos os dias' : frequency === 'weekly' ? `Toda semana (${selected.map(day => days[day]).join(', ') || 'selecione os dias'})` : 'Uma única execução';
  $('schedule-summary').textContent = Number.isFinite(date.getTime()) ? `${cadence}, às ${date.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'})}. Início em ${date.toLocaleDateString('pt-BR')}.` : 'Escolha uma data e um horário para executar.';
  $('schedule-feedback').textContent = '';
}
$('schedule-frequency').addEventListener('change', updateScheduleSummary);
$('schedule-at').addEventListener('input', updateScheduleSummary);
$('schedule-days').addEventListener('change', updateScheduleSummary);
let schedulesPageTimer = null;
function renderSchedulesPage() {
  const visible = (typeof appPath === 'function' ? appPath() : window.location.pathname) === '/agendamentos';
  $('schedules-page').hidden = !visible;
  clearInterval(schedulesPageTimer);
  if (!visible) return;
  $('chat-page').hidden = true;
  loadSchedules();
  schedulesPageTimer = setInterval(() => { if (!document.hidden) loadSchedules(); }, 5000);
}
$('open-schedules').addEventListener('click', event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigatePage('/agendamentos'); });
$('schedules-back').addEventListener('click', event => { event.preventDefault(); navigatePage('/'); });
$('reload-schedules').addEventListener('click', loadSchedules);
$('open-subagents').addEventListener('click', () => openWorkspaceDialog('subagents'));
for (const kind of ['schedule', 'subagents']) {
  $(`close-${kind}`).addEventListener('click', () => { resetWorkspaceUi(); $(`open-${kind}`).focus(); });
  $(`${kind}-dialog`).addEventListener('close', () => { clearInterval(workspaceUi.timer); workspaceUi.timer = null; workspaceUi.revision++; });
}
$('confirm-schedule-plan').addEventListener('click', () => {
  if (!workspaceUi.plan) return;
  workspaceUi.approved = true;
  $('schedule-form').hidden = false;
  $('schedule-chat-feedback').textContent = 'Plano confirmado. Configure quando executar.';
  $('schedule-dialog').showModal();
  $('schedule-task-title').textContent = workspaceUi.plan.title;
  $('schedule-task-prompt').textContent = workspaceUi.plan.prompt;
  const minimum = new Date(Date.now() + 60000);
  $('schedule-at').min = new Date(minimum.getTime() - minimum.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  updateScheduleSummary();
  $('save-schedule').disabled = false; $('schedule-at').focus();
});
$('revise-schedule-plan').addEventListener('click', () => {
  workspaceUi.approved = false;
  $('schedule-dialog').close(); $('schedule-form').hidden = true; $('schedule-plan-review').hidden = false;
  $('confirm-schedule-plan').focus();
});
$('schedule-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!workspaceUi.approved || !workspaceUi.plan) return;
  if ($('save-schedule').disabled) return;
  $('save-schedule').disabled = true; $('schedule-feedback').textContent = '';
  try {
    const date = new Date($('schedule-at').value);
    if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) throw new Error('Escolha uma data e hora futuras.');
    const weekdays = $('schedule-frequency').value === 'weekly' ? [...$('schedule-days').querySelectorAll('input:checked')].map(input => Number(input.value)) : [];
    if ($('schedule-frequency').value === 'weekly' && !weekdays.length) throw new Error('Selecione pelo menos um dia da semana.');
    if ($('schedule-frequency').value === 'weekly' && !weekdays.includes((date.getDay() + 6) % 7)) throw new Error('A data inicial deve cair em um dos dias selecionados.');
    await api(`/api/workspaces/${workspaceUi.conversationId}/schedules`, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title: workspaceUi.plan.title, prompt: workspaceUi.plan.prompt, run_at: date.toISOString(), frequency: $('schedule-frequency').value, weekdays, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        source_run_id: workspaceUi.sourceRunId, plan_steps: workspaceUi.plan.steps, ...workspaceUi.plan.options})});
    workspaceUi.approved = false; $('schedule-form').hidden = true; $('schedule-dialog').close();
    $('schedule-chat-feedback').textContent = 'Agendamento salvo. Acompanhe na guia Agendamentos.';
  } catch (error) { $('schedule-feedback').textContent = error.message; }
  finally { $('save-schedule').disabled = false; }
});

function renderWorkspaceSuggestions(run) {
  const container = $('schedule-proposals');
  const proposals = (run.events || []).filter(event => event.kind === 'tool_result' && event.result?.kind === 'schedule_proposal').slice(-3);
  const signature = JSON.stringify([run.id, proposals]);
  if (container.dataset.signature === signature) return;
  container.dataset.signature = signature; container.replaceChildren();
  for (const event of proposals) {
    const proposal = event.result;
    const card = el('article', 'workspace-card schedule-proposal');
    card.append(el('strong', '', `Sugestão de agendamento: ${proposal.title}`), el('p', 'muted', proposal.reason));
    const review = el('button', 'secondary', 'Revisar agendamento'); review.type = 'button';
    review.addEventListener('click', () => openWorkspaceDialog('schedule', proposal));
    card.append(review); container.append(card);
  }
}
$('execute-subagent').addEventListener('click', async () => {
  const draft = $('prompt').value.trim();
  const task = typeof expandChatMentions === 'function' ? expandChatMentions(draft) : draft;
  if (task.length < 3) { notice('Descreva a tarefa com pelo menos 3 caracteres.'); return; }
  if (task.length > 6000) { notice('A tarefa do subagente aceita até 6000 caracteres.'); return; }
  if (state.uploading || $('execute-subagent').disabled) return;
  $('execute-subagent').disabled = true;
  try {
    const source = state.run;
    const id = source?.origin_conversation_id || await ensureWorkspace();
    const payload = {task, source_run_id: source?.id || null, dataset_ids: (state.files || []).map(file => file.id), query_ids: typeof selectedQueryIds === 'function' ? selectedQueryIds() : [], output_format: $('output-dashboard').checked ? 'dashboard' : 'auto', web_search_enabled: $('web-search-enabled').getAttribute('aria-pressed') === 'true' && !$('web-search-enabled').disabled};
    const sessionId = state.sessionId;
    const profiles = (await (await api(`/api/workspaces/${id}/subagents`)).json()).subagents;
    const chosen = profiles.length ? await chooseDelegate(profiles, task) : 'new';
    if (!chosen || sessionId !== state.sessionId) return;
    const profile = profiles.find(item => item.id === chosen);
    const path = profile ? (profile.created_by === 'user' ? `/api/workspaces/${id}/subagents/${profile.id}/run` : `/api/workspaces/${id}/delegate`) : `/api/workspaces/${id}/subagents/execute`;
    if (profile) payload.subagent_id = profile.id;
    const run = await (await api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})).json();
    selectRun(run); $('prompt').value = ''; state.files = []; renderAttachments();
    if (typeof clearQueryAttachments === 'function') clearQueryAttachments();
  } catch (error) { notice(error.message); }
  finally { $('execute-subagent').disabled = false; }
});

let resolveDelegate = null;
function chooseDelegate(profiles, task) {
  const select = $('delegate-agent'); select.replaceChildren();
  for (const profile of profiles) {
    const option = el('option', '', `${profile.name} - ${profile.status === 'running' || profile.status === 'queued' ? 'Ocupado' : 'Disponível'}`);
    option.value = profile.id; option.disabled = ['running', 'queued'].includes(profile.status); select.append(option);
  }
  if (profiles.length < 2) { const option = el('option', '', 'Criar novo subagente'); option.value = 'new'; select.append(option); }
  const available = profiles.find(profile => !['running', 'queued'].includes(profile.status));
  select.value = available?.id || (profiles.length < 2 ? 'new' : '');
  $('confirm-delegate').disabled = !select.value;
  $('delegate-task').textContent = task;
  $('delegate-dialog').showModal(); select.focus();
  return new Promise(resolve => { resolveDelegate = resolve; });
}
$('delegate-form').addEventListener('submit', event => {
  event.preventDefault();
  const value = $('delegate-agent').value;
  if (!value) return;
  const resolve = resolveDelegate; resolveDelegate = null;
  $('delegate-dialog').close(); resolve?.(value);
});
$('close-delegate').addEventListener('click', () => $('delegate-dialog').close());
$('delegate-dialog').addEventListener('close', () => { resolveDelegate?.(null); resolveDelegate = null; });
renderSchedulesPage();
