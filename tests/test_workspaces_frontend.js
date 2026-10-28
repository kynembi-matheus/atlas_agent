'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Node {
  constructor() { this.handlers = {}; this.children = []; this.dataset = {}; this.value = ''; this.open = false; this.disabled = false; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.handlers.close?.(); }
  querySelectorAll() { return []; }
  getAttribute() { return 'true'; }
  setAttribute(name, value) { this[name] = value; }
}
function harness(profiles = null) {
  const nodes = new Map(), requests = [], timers = new Map(), selected = []; let nextTimer = 0;
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const state = {conversationId: null, sessionId: 'session', run: null};
  const context = vm.createContext({$, state, ensureDataSession: async () => {},
    api: async (path, options) => {
      requests.push({path, body: options?.body && JSON.parse(options.body)});
      return {json: async () => path.endsWith('/schedules/plan') ? {title: 'Plano', prompt: JSON.parse(options.body).prompt, source_run_id: 'source-run', steps: ['Conferir fontes', 'Gerar resultado']} : (path.endsWith('/run') || path.endsWith('/execute')) ? {id: 'personal-run', conversation_id: 'personal-conversation'} : path.includes('/context?') ? {source_run_id: 'source-run', title: 'Carteira', request: 'Atualize os indicadores.', dataset_count: 1, query_count: 1, web_search_enabled: true} : path === '/api/workspaces' ? {conversation_id: 'workspace'} : path.endsWith('/subagents') ?
        {subagents: profiles || [{id: 'one', name: 'Um', status: 'idle', instructions: 'Leia dados'}, {id: 'two', name: 'Dois', status: 'idle', instructions: 'Revise dados'}]} : {schedules: []}};
    }, el: (tag, cls, text) => Object.assign(new Node(), {tag, className: cls, textContent: text}),
    notice: message => assert.fail(message), renderAttachments() {}, renderMarkdown() {}, selectRun(run) { selected.push(run); },
    window: {location: {pathname: '/'}}, document: {hidden: false}, setInterval(fn) { timers.set(++nextTimer, fn); return nextTimer; },
    clearInterval(id) { timers.delete(id); }, Intl, Date});
  vm.runInContext(fs.readFileSync('frontend/workspaces.js', 'utf8'), context);
  return {$, state, requests, context, timers, selected};
}
test('context shortcuts are next to Anexar and open labelled dialogs', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');
  const heading = html.slice(html.indexOf('<section class="workspace-head"'), html.indexOf('<section id="welcome"'));
  assert.match(heading, /open-subagents/);
  assert.doesNotMatch(heading, /open-schedule/);
  const composer = html.slice(html.indexOf('<div class="composer-toolbar"'), html.indexOf('<div class="composer-options"'));
  assert.match(composer, /Anexar[\s\S]*open-schedule[\s\S]*execute-subagent[\s\S]*id="send"/);
  assert.doesNotMatch(html, /id="subagent-form"|Criar meu subagente/);
  assert.match(html, /id="schedule-dialog"[^>]+aria-labelledby="schedule-heading"/);
  assert.match(html, /id="subagents-dialog"[^>]+aria-labelledby="subagents-heading"/);
});
test('opening subagents reserves a session and enforces the two-profile limit in the UI', async () => {
  const h = harness(); await h.context.openWorkspaceDialog('subagents');
  assert.equal(h.state.conversationId, 'workspace');
  assert.equal(h.$('subagents-dialog').open, true);
  assert.equal(h.$('subagents-count').textContent, '2 de 2 subagentes nesta sessão');
  assert.equal(h.timers.size, 1);
  h.context.resetWorkspaceUi(); assert.equal(h.timers.size, 0);
});
test('schedule submission converts local time to UTC and does not submit an immediate run', async () => {
  const h = harness(); h.$('prompt').value = 'Analise os indicadores amanhã.';
  h.state.conversationId = 'workspace'; h.state.run = {id: 'source-run', title: 'Carteira'};
  await h.context.openWorkspaceDialog('schedule');
  assert.equal(h.$('schedule-form').hidden, true);
  assert.equal(h.$('schedule-dialog').open, false);
  assert.equal(h.$('schedule-chat').hidden, false);
  await h.$('schedule-form').handlers.submit({preventDefault() {}});
  assert.equal(h.requests.some(item => item.path.endsWith('/schedules') && item.body), false);
  h.$('confirm-schedule-plan').handlers.click();
  assert.equal(h.$('schedule-form').hidden, false);
  assert.equal(h.$('schedule-dialog').open, true);
  h.$('schedule-title').value = 'Resumo';
  h.$('schedule-at').value = '2099-10-28T09:30';
  await h.$('schedule-form').handlers.submit({preventDefault() {}});
  const request = h.requests.find(item => item.path.endsWith('/schedules') && item.body);
  assert.equal(request.body.prompt, h.$('prompt').value);
  assert.equal(request.body.plan_steps.length, 2);
  assert.equal(request.body.run_at, new Date('2099-10-28T09:30').toISOString());
  assert.equal(request.body.source_run_id, 'source-run');
  assert.equal(request.body.web_search_enabled, true);
  assert.equal(h.requests.some(item => item.path === '/api/runs'), false);
});

test('an agent schedule proposal stays a suggestion until reviewed', async () => {
  const h = harness();
  h.context.renderWorkspaceSuggestions({id: 'run', events: [{kind: 'tool_result', result: {
    kind: 'schedule_proposal', source_run_id: 'source-run', title: '<script>literal</script>',
    prompt: 'Atualize os indicadores.', reason: 'Acompanhar a evolução.'}}]});
  const card = h.$('schedule-proposals').children[0];
  assert.equal(card.children[0].textContent, 'Sugestão de agendamento: <script>literal</script>');
  assert.equal(h.requests.length, 0);
  assert.equal(h.$('schedule-dialog').open, false);
});

test('agent popup only shows task and status and opens its execution', async () => {
  const h = harness([{id: 'one', name: 'Ana', status: 'running', task: 'Confira os filtros.', run_id: 'run-one'}]);
  h.state.conversationId = 'workspace'; h.state.run = {id: 'source-run'};
  await h.context.openWorkspaceDialog('subagents');
  const card = h.$('subagents-list').children[0];
  assert.equal(card.tag, 'button');
  assert.equal(card.children[1].textContent, 'Confira os filtros.');
  assert.equal(card.children.some(node => node.tag === 'textarea'), false);
  await card.handlers.click();
  assert.equal(h.requests.some(request => request.path === '/api/runs/run-one'), true);
  assert.equal(h.selected.length, 1);
});

test('delegation selector reuses an agent or offers a new one only below the limit', async () => {
  const h = harness();
  let pending = h.context.chooseDelegate([{id: 'one', name: 'Ana', status: 'completed'}], 'Check sources');
  assert.equal(h.$('delegate-agent').children.length, 2);
  h.$('delegate-agent').value = 'new';
  h.$('delegate-form').handlers.submit({preventDefault() {}});
  assert.equal(await pending, 'new');
  pending = h.context.chooseDelegate([{id: 'one', name: 'Ana', status: 'completed'}, {id: 'two', name: 'Bruno', status: 'running'}], 'Check sources');
  assert.equal(h.$('delegate-agent').children.length, 2);
  assert.equal(h.$('delegate-agent').children[1].disabled, true);
  h.$('delegate-agent').value = 'one';
  h.$('delegate-form').handlers.submit({preventDefault() {}});
  assert.equal(await pending, 'one');
});

test('chat delegation starts immediately when none exists even if main is busy', async () => {
  const h = harness([]); h.state.conversationId = 'workspace'; h.state.run = {id: 'source-run', status: 'running'};
  h.$('send').disabled = true; h.$('prompt').value = 'Verify selected sources';
  await h.$('execute-subagent').handlers.click();
  const request = h.requests.find(item => item.path.endsWith('/subagents/execute'));
  assert.equal(request.body.task, 'Verify selected sources');
  assert.equal(request.body.source_run_id, 'source-run');
  assert.equal(h.selected.length, 1);
});

test('schedules page lists tasks and their recurrence without a dialog', async () => {
  const h = harness(); h.context.window.location.pathname = '/agendamentos';
  h.context.api = async () => ({json: async () => ({schedules: [
    {id: 'schedule', title: 'Daily summary', prompt: 'Prepare summary', status: 'pending', frequency: 'daily', timezone: 'UTC', run_at: '2099-01-01T10:00:00Z'}
  ]})});
  h.context.renderSchedulesPage(); await h.context.loadSchedules();
  assert.equal(h.$('schedules-page').hidden, false);
  assert.equal(h.$('chat-page').hidden, true);
  assert.equal(h.$('schedule-list').children.length, 1);
  assert.equal(h.$('schedule-dialog').open, false);
  h.context.window.location.pathname = '/'; h.context.renderSchedulesPage();
  assert.equal(h.$('schedules-page').hidden, true);
});

test('schedule popup shows the confirmed task and a live recurrence summary', async () => {
  const h = harness(); h.$('prompt').value = 'Atualizar a carteira'; h.state.conversationId = 'workspace';
  await h.context.openWorkspaceDialog('schedule');
  h.$('confirm-schedule-plan').handlers.click();
  assert.equal(h.$('schedule-task-title').textContent, 'Plano');
  assert.equal(h.$('schedule-task-prompt').textContent, 'Atualizar a carteira');
  h.$('schedule-frequency').value = 'daily';
  h.$('schedule-frequency').handlers.change();
  assert.match(h.$('schedule-summary').textContent, /Todos os dias/);
  assert.equal(h.$('schedule-days').hidden, true);
  h.$('schedule-frequency').value = 'weekly'; h.$('schedule-frequency').handlers.change();
  assert.equal(h.$('schedule-days').hidden, false);
  assert.match(h.$('schedule-summary').textContent, /selecione os dias/);
  h.$('schedule-at').value = '2099-10-28T09:30';
  await h.$('schedule-form').handlers.submit({preventDefault() {}});
  assert.match(h.$('schedule-feedback').textContent, /Selecione pelo menos/);
  assert.equal(h.requests.some(item => item.path.endsWith('/schedules')), false);
  h.$('schedule-days').querySelectorAll = () => [{value: String((new Date('2099-10-28T09:30').getDay() + 6) % 7)}];
  await h.$('schedule-form').handlers.submit({preventDefault() {}});
  assert.equal(h.requests.filter(item => item.path.endsWith('/schedules')).length, 1);
});

test('revising a schedule requires confirmation again', async () => {
  const h = harness(); h.$('prompt').value = 'Revisar carteira'; h.state.conversationId = 'workspace';
  await h.context.openWorkspaceDialog('schedule'); h.$('confirm-schedule-plan').handlers.click();
  h.$('revise-schedule-plan').handlers.click();
  assert.equal(h.$('schedule-dialog').open, false);
  h.$('schedule-at').value = '2099-10-28T09:30';
  await h.$('schedule-form').handlers.submit({preventDefault() {}});
  assert.equal(h.requests.some(item => item.path.endsWith('/schedules')), false);
  h.$('confirm-schedule-plan').handlers.click();
  assert.equal(h.$('schedule-dialog').open, true);
});
