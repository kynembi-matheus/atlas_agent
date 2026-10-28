'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {};
    this.className = ''; this.scrollTop = 0; this.clientHeight = 200; this.style = {};
    this.classList = {toggle: (name, enabled) => {
      const classes = new Set(this.className.split(' ').filter(Boolean));
      if (enabled) classes.add(name); else classes.delete(name);
      this.className = [...classes].join(' ');
    }};
  }
  get scrollHeight() { return this.children.length * 80; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
}

function markdown(text) {
  const context = vm.createContext({document: {
    createElement: tag => new Element(tag),
    createTextNode: text => ({tag: '#text', textContent: text}),
  }});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/markdown.js'), 'utf8'), context);
  const container = new Element('div');
  context.renderMarkdown(container, text);
  return {container, render: value => context.renderMarkdown(container, value)};
}
function descendants(node, tag) {
  return (node.children || []).flatMap(child => [...(child.tag === tag ? [child] : []), ...descendants(child, tag)]);
}
function textOf(node) { return (node.textContent || '') + (node.children || []).map(textOf).join(''); }

test('answers render emphasis, headings, paragraphs, quotes and code as DOM elements', () => {
  const {container} = markdown('# Resultado\n\n**Total: R$ 100** e *estimativa* com __fonte__ e ~~antigo~~.\nOutra linha com `**literal**`.\n\n> **Amostra**, não total.\n\n---\n\n```sql\nSELECT * FROM tabela;\n<script>alert(1)</script>\n```');
  assert.equal(textOf(descendants(container, 'h1')[0]), 'Resultado');
  assert.equal(textOf(descendants(container, 'strong')[0]), 'Total: R$ 100');
  assert.equal(descendants(container, 'strong').length, 3);
  assert.equal(textOf(descendants(container, 'em')[0]), 'estimativa');
  assert.equal(textOf(descendants(container, 'del')[0]), 'antigo');
  assert.equal(textOf(descendants(container, 'code')[0]), '**literal**');
  assert.equal(descendants(container, 'blockquote').length, 1);
  assert.equal(descendants(container, 'br').length, 1);
  assert.equal(descendants(container, 'hr').length, 1);
  assert.match(textOf(descendants(container, 'pre')[0]), /<script>alert\(1\)<\/script>/);
  assert.equal(descendants(container, 'script').length, 0);
});

test('answers render nested lists and aligned tables with inline formatting', () => {
  const {container} = markdown('3. **Primeiro**\n   - Subitem\n4. Segundo\n\n| Indicador | Valor |\n| --- | ---: |\n| **Total** | 100 |\n| Amostra | 10 |');
  assert.equal(descendants(container, 'ol')[0].attributes.start, '3');
  assert.equal(descendants(container, 'ul').length, 1);
  assert.equal(descendants(container, 'li').length, 3);
  assert.equal(descendants(container, 'table').length, 1);
  assert.equal(descendants(container, 'th').length, 2);
  assert.equal(descendants(container, 'td').length, 4);
  assert.equal(descendants(container, 'td')[1].style.textAlign, 'right');
  assert.equal(textOf(descendants(container, 'strong')[1]), 'Total');
});

test('HTML stays literal and unsafe links cannot become executable DOM', () => {
  const {container} = markdown('<img src=x onerror=alert(1)> [site](https://example.com) [local](/docs) [email](mailto:teste@example.com) [ruim](javascript:alert) [dados](data:text/html,test) [rede](//example.com)');
  assert.equal(descendants(container, 'img').length, 0);
  assert.match(textOf(container), /<img src=x onerror=alert\(1\)>/);
  assert.equal(descendants(container, 'a').length, 3);
  assert.equal(descendants(container, 'a')[0].attributes.href, 'https://example.com');
  assert.match(textOf(container), /\[ruim\]\(javascript:alert\)/);
});

test('rerender replaces the previous answer and handles empty and unfinished Markdown', () => {
  const {container, render} = markdown('**Antes**');
  render('Depois\n\n```\n**literal**');
  assert.equal(descendants(container, 'strong').length, 0);
  assert.equal(textOf(descendants(container, 'code')[0]), '**literal**');
  assert.doesNotMatch(textOf(container), /Antes/);
  render('');
  assert.equal(container.children.length, 0);
});

test('chat rendering formats answers from history and preserves unchanged DOM during polling', () => {
  const nodes = new Map();
  const context = vm.createContext({
    document: {createElement: tag => new Element(tag), createTextNode: text => ({tag: '#text', textContent: text})},
    $: id => { if (!nodes.has(id)) nodes.set(id, new Element('div')); return nodes.get(id); },
    state: {}, statuses: {completed: 'Concluída'}, renderEvents: () => {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/markdown.js'), 'utf8'), context);
  const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf('function sessionAgentIdentity('), source.indexOf('function appendSessionAgents(')), context);
  vm.runInContext(source.slice(source.indexOf('function render(run)'), source.indexOf('function stopPolling()')), context);
  const run = {prompt: '**pedido literal**', answer: '**Resposta**', status: 'completed', id: 'history', created_at: '2026-10-26T12:00:00Z', artifacts: []};
  context.render(run);
  assert.equal(nodes.get('conversation-title').textContent, 'Nova Conversa');
  assert.equal(nodes.get('user-message').textContent, '**pedido literal**');
  const strong = descendants(nodes.get('answer'), 'strong')[0];
  assert.equal(textOf(strong), 'Resposta');
  context.render(run);
  assert.equal(descendants(nodes.get('answer'), 'strong')[0], strong);
  context.render({...run, answer: '*Atualizada*'});
  assert.equal(descendants(nodes.get('answer'), 'strong').length, 0);
  assert.equal(textOf(descendants(nodes.get('answer'), 'em')[0]), 'Atualizada');
  context.render({...run, title: '<img src=x onerror=alert(1)>'});
  assert.equal(nodes.get('conversation-title').textContent, '<img src=x onerror=alert(1)>');
});

test('steps fade as new events arrive, preserving expanded results and scroll position', () => {
  const container = new Element('div');
  const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
  const context = vm.createContext({
    document: {createElement: tag => new Element(tag)},
    $: () => container,
  });
  vm.runInContext(source.slice(source.indexOf('function el('), source.indexOf('async function refreshStatus'))
    + source.slice(source.indexOf('function renderEvents('), source.indexOf('function render(run)')), context);
  const run = {id: 'one', events: [
    {kind: 'progress', message: 'Etapa 1'},
    {kind: 'tool_result', message: 'Dados', result: {rows: [1]}},
  ]};
  context.renderEvents(run);
  const details = container.children[1];
  details.open = true;
  assert.match(details.className, /event-current/);
  run.events.push({kind: 'progress', message: 'Etapa 2'});
  context.renderEvents(run);
  assert.equal(container.children[1], details);
  assert.equal(details.open, true);
  assert.match(details.className, /event-previous/);
  assert.match(container.children[0].className, /event-past/);
  assert.equal(container.children[2].attributes['aria-current'], 'step');
  assert.equal(details.attributes['aria-current'], undefined);
  // Polling does not duplicate the events.
  context.renderEvents(run);
  assert.equal(container.children.length, 3);
  container.scrollTop = 0;
  container.clientHeight = 100;
  run.events.push({kind: 'progress', message: 'Etapa 3'});
  context.renderEvents(run);
  assert.equal(container.scrollTop, 0);
  context.renderEvents({id: 'two', events: [{kind: 'progress', message: 'Nova execução'}]});
  assert.equal(container.children.length, 1);
  assert.match(container.children[0].className, /event-current/);
});

function uploadHarness(files, initial = []) {
  const nodes = new Map(); const handlers = {}; const notices = []; const requests = [];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {disabled: false, addEventListener: (event, handler) => { handlers[id] = handler; }});
    return nodes.get(id);
  };
  const state = {files: [...initial], uploading: false, run: null};
  const context = vm.createContext({
    $: node, state, notice: message => notices.push(message), renderAttachments: () => {},
    FormData: class { append(_, file) { this.file = file; } },
    api: async (_, options) => {
      requests.push(options.body.file.name);
      if (options.body.file.name.endsWith('.exe')) throw new Error('Formato inválido');
      return {json: async () => ({dataset_id: options.body.file.name, row_count: 2, source: {format: 'csv'}})};
    },
  });
  const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf("$('data-files').addEventListener"), source.indexOf("$('prompt-form').addEventListener")), context);
  const input = {files, disabled: false, value: 'selected'};
  return {state, nodes, notices, requests, input, run: () => handlers['data-files']({target: input})};
}

test('multiple attachments preserve valid uploads when another file fails', async () => {
  const harness = uploadHarness([{name: 'one.csv'}, {name: 'bad.exe'}, {name: 'two.csv'}]);
  const pending = harness.run();
  assert.equal(harness.state.uploading, true);
  assert.equal(harness.nodes.get('send').disabled, true);
  assert.equal(harness.nodes.get('new-run').disabled, true);
  await pending;
  assert.deepEqual(Array.from(harness.state.files, file => file.filename), ['one.csv', 'two.csv']);
  assert.deepEqual(harness.requests, ['one.csv', 'bad.exe', 'two.csv']);
  assert.match(harness.notices.at(-1), /bad.exe: Formato inválido/);
  assert.equal(harness.input.disabled, false);
  assert.equal(harness.input.value, '');
  assert.equal(harness.nodes.get('send').disabled, false);
});

test('attachment limit rejects the whole selection before uploading', async () => {
  const harness = uploadHarness([{name: 'one.csv'}, {name: 'two.csv'}], Array(9).fill({id: 'existing'}));
  await harness.run();
  assert.equal(harness.requests.length, 0);
  assert.equal(harness.state.files.length, 9);
  assert.match(harness.notices.at(-1), /10 arquivos/);
  assert.equal(harness.input.value, '');
});

test('model name is displayed in the sidebar from the status API', async () => {
  const label = {};
  const context = vm.createContext({$: id => id === 'web-search-enabled' ? null : label,
    api: async () => ({json: async () => ({model: 'modelo-configurado', llm_configured: true})}), notice: () => {}});
  const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf('async function refreshStatus'), source.indexOf('async function refreshHistory')), context);
  await context.refreshStatus();
  assert.equal(label.textContent, 'modelo-configurado');
});
