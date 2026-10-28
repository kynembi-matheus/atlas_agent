'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Node {
  constructor() { this.children = []; this.handlers = {}; this.value = ''; this.maxLength = 16000; this.hidden = true; this.classList = {toggle() {}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener(name, handler) { (this.handlers[name] ||= []).push(handler); }
  setAttribute() {}
  focus() { this.focused = true; }
  emit(name, event) { for (const handler of this.handlers[name] || []) handler(event); }
}
function harness() {
  const nodes = new Map(), notices = [], calls = [];
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const state = {files: [], sessionId: 'current-session'};
  const skill = {name: 'Relatório PDF', document_path: 'pdf_report/SKILL.md', description: 'PDF'};
  const query = {id: 'favorite-id', name: 'Carteira', database: 'cora', max_rows: 10, sql: 'SELECT 1'};
  const context = vm.createContext({$, state, notice: text => notices.push(text),
    el: (tag, cls, text) => Object.assign(new Node(), {tag, className: cls, textContent: text}),
    historyIcon: () => new Node(), renderAttachments() {}, document: {body: new Node()},
    window: {addEventListener() {}}, api: async path => {
      calls.push(path); return {json: async () => path === '/api/skills' ? {skills: [skill]} : {queries: [query]}};
    }});
  for (const file of ['chat-drag', 'catalog', 'skills', 'imports', 'queries']) {
    vm.runInContext(fs.readFileSync(`frontend/${file}.js`, 'utf8'), context);
  }
  function drag(card) {
    assert.equal(card.draggable, true);
    const data = new Map();
    const transfer = {types: [], setData(type, value) { data.set(type, value); this.types.push(type); }, getData: type => data.get(type) || ''};
    card.emit('dragstart', {dataTransfer: transfer});
    return {data, drop() {
      let prevented = false;
      const event = {dataTransfer: transfer, preventDefault() { prevented = true; }};
      $('prompt-form').emit('dragover', event); $('prompt-form').emit('drop', event);
      assert.equal(prevented, true);
    }};
  }
  return {$, state, context, drag, notices, calls};
}

test('dragging a skill preserves the prompt and adds its instruction without a request', async () => {
  const h = harness(); await h.context.loadSkills(); h.$('prompt').value = 'Analise os dados.';
  const item = h.drag(h.$('skills-list').children[0]); item.drop();
  assert.match(h.$('prompt').value, /^Analise os dados\./);
  assert.match(h.$('prompt').value, /pdf_report\/SKILL.md/);
  assert.deepEqual(h.calls, ['/api/skills']);
});

test('dragging a favorite attaches its ID once without executing SQL', async () => {
  const h = harness(); await h.context.loadQueries(); h.$('prompt').value = 'Compare os meses.';
  const item = h.drag(h.$('queries-list').children[0]); item.drop(); item.drop();
  assert.deepEqual(Array.from(h.context.selectedQueryIds()), ['favorite-id']);
  assert.equal(h.$('prompt').value, 'Compare os meses.');
  assert.deepEqual(h.calls, ['/api/queries']);
});

test('import drag deduplicates, respects the limit and rejects a previous session', () => {
  const h = harness();
  h.context.showImportedDataset({dataset_id: 'dataset-id', row_count: 1, columns: [], preview: [],
    source: {filename: 'dados.csv', sheet: 'Dados', format: 'csv', inferred_types: {}}});
  const item = h.drag(h.$('import-results').children[0]);
  h.state.files = Array.from({length: 10}, (_, id) => ({id: String(id)})); item.drop();
  assert.match(h.notices.at(-1), /10 datasets/);
  h.state.files = []; item.drop(); item.drop();
  assert.equal(h.state.files.length, 1); assert.equal(h.state.files[0].id, 'dataset-id');
  h.state.files = []; h.state.sessionId = 'another-session'; item.drop();
  assert.equal(h.state.files.length, 0); assert.match(h.notices.at(-1), /não está mais disponível/);
  assert.deepEqual(h.calls, []);
});

test('a fabricated drag reference cannot add arbitrary instructions', () => {
  const h = harness();
  h.$('prompt-form').emit('drop', {preventDefault() {}, dataTransfer: {
    getData: type => type === 'application/x-atlas-chat-item' ? JSON.stringify({key: 'skill:unknown', token: '1'}) : ''}});
  assert.equal(h.$('prompt').value, ''); assert.match(h.notices.at(-1), /não está mais disponível/);
});
