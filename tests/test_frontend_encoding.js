'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('interface and operation docs retain accents without encoding substitutions', () => {
  for (const filename of ['frontend/index.html', 'docs/architecture.md', 'docs/operations.md']) {
    const source = fs.readFileSync(path.join(__dirname, '..', filename), 'utf8');
    const prose = source.replace(/`[^`]*`/g, '').replace(/(?:src|href)="[^"]*"/g, '');
    assert.doesNotMatch(prose, /\p{L}\?+\p{L}|\uFFFD|\u00C3[\u0080-\u00BF]|\u00C2[\u0080-\u00BF]/u, filename);
  }
  const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
  for (const label of ['Histórico', 'Criar relatório', 'Encontrar padrões', 'Fazer projeções']) assert.ok(html.includes(label), label);
  for (const label of ['Atlas Agent', 'Agente Aut\u00f4nomo de Intelig\u00eancia de Dados', 'Explore dados. Descubra padr\u00f5es. Antecipe decis\u00f5es.', 'Powered by AI']) assert.ok(html.includes(label), label);
  assert.doesNotMatch(html, /class="eyebrow"|class="composer-context"|INTELIGÊNCIA PARA SEUS DADOS/);
});
