'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/app.js', 'utf8');
test('historical turns remain visible and stale responses cannot overwrite the selected conversation', async () => {
  const container = {children: [], replaceChildren() { this.children = []; }, append(...items) { this.children.push(...items); }};
  const el = (tag, cls, text) => ({tag, cls, text, children: [], append(...items) { this.children.push(...items); }, addEventListener() {}});
  let response;
  const context = vm.createContext({state: {conversationId: 'a', runId: '2'}, $: () => container, el,
    renderMarkdown(node, text) {node.text = text;}, notice() {}, api: async () => ({json: async () => response})});
  vm.runInContext(source.slice(source.indexOf('async function loadConversation('), source.indexOf('function selectRun(')), context);
  response = [{id: '1', prompt: 'Primeira', answer: 'Resposta', artifacts: []}, {id: '2', prompt: 'Segunda'}];
  await context.loadConversation({id: '2', conversation_id: 'a'});
  assert.equal(container.children.length, 2);
  assert.equal(container.children[0].children[1].text, 'Primeira');
  assert.equal(container.children[1].children[1].text, 'Resposta');
  context.state.conversationId = 'b';
  await context.loadConversation({id: '2', conversation_id: 'a'});
  assert.equal(container.children.length, 2);
});
