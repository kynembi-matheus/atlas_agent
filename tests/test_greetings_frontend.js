'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('welcome chooses a greeting safely across the random range', () => {
  const source = fs.readFileSync(path.join(__dirname, '../frontend/greetings.js'), 'utf8');
  const selected = new Set();
  for (let i = 0; i < 10; i++) {
    const node = {textContent: ''};
    vm.runInNewContext(source, {document: {getElementById: id => id === 'welcome-greeting' ? node : null}, Math: {floor: Math.floor, random: () => (i + 0.5) / 10}});
    assert.ok(node.textContent.length > 0);
    selected.add(node.textContent);
  }
  assert.equal(selected.size, 10);
  assert.doesNotThrow(() => vm.runInNewContext(source, {document: {getElementById: () => null}, Math}));
});

test('suggestions have distinct labels and matching requests', () => {
  const source = fs.readFileSync(path.join(__dirname, '../frontend/greetings.js'), 'utf8');
  const buttons = Array.from({length: 3}, () => ({dataset: {}, lastChild: {}, querySelector: () => null}));
  vm.runInNewContext(source, {document: {getElementById: () => null, querySelectorAll: () => buttons}, Math});
  assert.equal(new Set(buttons.map(button => button.lastChild.textContent)).size, 3);
  for (const button of buttons) assert.ok(button.dataset.prompt);
});
