'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Node {
  constructor() {
    this.children = []; this.handlers = {}; this.attributes = {}; this.value = ''; this.maxLength = 16000;
    this.hidden = true; this.classList = {toggle() {}};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
}
function harness(api) {
  const nodes = new Map(), notices = [];
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const el = (tag, className, text) => { const node = new Node(); node.tag = tag; node.textContent = text; return node; };
  const context = vm.createContext({$, el, api, notice: text => notices.push(text), document: {body: new Node()}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/chat-drag.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/skills.js'), 'utf8'), context);
  return {$, context, notices};
}
const skill = {name: 'Relatórios em PDF', description: '<b>Descrição literal</b>', document_path: 'pdf_report/SKILL.md'};

test('all skills render with descriptions and selection preserves the existing question', async () => {
  const {$, context} = harness(async () => ({json: async () => ({skills: [skill, {...skill, name: 'Dados internos'}]})}));
  await context.loadSkills();
  assert.equal($('skills-list').children.length, 2);
  const card = $('skills-list').children[0];
  assert.equal(card.children[1].textContent, '<b>Descrição literal</b>');
  $('prompt').value = 'Analise minha carteira.';
  card.children[2].handlers.click();
  assert.match($('prompt').value, /^Analise minha carteira\.\nUse a skill/);
  assert.ok($('prompt').value.includes(skill.document_path));
  assert.equal($('prompt').focused, true);
});

test('skills panel closes data panel and Escape restores focus', () => {
  const {$, context} = harness(async () => ({json: async () => ({skills: []})}));
  $('data-preview').hidden = false;
  context.setSkillsOpen(true);
  assert.equal($('data-preview').hidden, true);
  assert.equal($('toggle-preview').attributes['aria-expanded'], 'false');
  assert.equal($('skills-panel').hidden, false);
  $('skills-panel').handlers.keydown({key: 'Escape'});
  assert.equal($('skills-panel').hidden, true);
  assert.equal($('toggle-skills').focused, true);
});

test('skills errors allow retry and empty skills have a clear state', async () => {
  let failed = true;
  const {$, context} = harness(async () => { if (failed) throw new Error('Indisponível'); return {json: async () => ({skills: []})}; });
  await context.loadSkills();
  assert.equal($('retry-skills').hidden, false);
  assert.equal($('skills-status').textContent, 'Indisponível');
  failed = false;
  await $('retry-skills').handlers.click();
  assert.equal($('skills-status').textContent, 'Nenhuma skill disponível.');
  assert.equal($('retry-skills').hidden, true);
});

test('selecting a skill does not exceed the prompt length limit', () => {
  const {$, context, notices} = harness();
  $('prompt').value = 'Pergunta'; $('prompt').maxLength = 10;
  context.chooseSkill(skill);
  assert.equal($('prompt').value, 'Pergunta');
  assert.match(notices[0], /limite/);
});

test('chat tool controls are inside the composer next to web search', () => {
  const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
  const sidebar = html.slice(html.indexOf('<aside id="app-sidebar"'), html.indexOf('</aside>'));
  const workspace = html.slice(html.indexOf('<form id="prompt-form"'), html.indexOf('</form>', html.indexOf('<form id="prompt-form"')));
  assert.doesNotMatch(sidebar, /id="toggle-preview"|id="toggle-skills"/);
  assert.match(workspace, /id="toggle-preview"/);
  assert.match(workspace, /id="toggle-skills"/);
  assert.match(workspace, /id="toggle-imports"/);
  assert.match(workspace, /id="toggle-queries"/);
  assert.ok(workspace.indexOf('id="toggle-preview"') > workspace.indexOf('id="web-search-enabled"'));
  const header = html.slice(html.indexOf('<section class="workspace-head"'), html.indexOf('<section id="welcome"'));
  assert.doesNotMatch(header, /id="toggle-preview"|id="toggle-imports"|id="toggle-skills"|id="toggle-queries"/);
  assert.equal((html.match(/id="toggle-preview"/g) || []).length, 1);
});
