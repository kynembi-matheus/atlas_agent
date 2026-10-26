'use strict';

// Autocomplete only inserts explicit references; it never runs a skill or queries rows.
const mentions = {revision: 0, token: null, items: [], active: 0, skills: null, databases: null, tables: new Map()};
const mentionRequests = new Map();
const selectedMentions = new Map();
function expandChatMentions(text) {
  // Keep technical instructions out of the editor while preserving complete sources in the request.
  const entries = [...selectedMentions].sort((a, b) => b[0].length - a[0].length);
  for (const [label, reference] of entries) {
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(`(^|\\s)${escaped}(?=$|\\s|[,.!?;:)])`, 'g'), (_, prefix) => prefix + reference);
  }
  return text;
}
async function mentionData(path) {
  if (!mentionRequests.has(path)) {
    const pending = api(path).then(response => response.json()).catch(error => {
      mentionRequests.delete(path); throw error;
    });
    mentionRequests.set(path, pending);
  }
  return mentionRequests.get(path);
}
function mentionToken(value, caret) {
  const match = /(?:^|\s)([/@?])([^\s/@?]*)$/.exec(value.slice(0, caret));
  return match ? {kind: match[1], query: match[2], start: caret - match[2].length - 1, end: caret} : null;
}
function closeMentions() {
  mentions.revision++; mentions.token = null; mentions.items = [];
  $('mention-menu').hidden = true;
  $('prompt').setAttribute('aria-expanded', 'false');
  $('prompt').removeAttribute('aria-activedescendant');
}
function paintMentions(message) {
  const menu = $('mention-options'); menu.replaceChildren();
  $('mention-status').textContent = message || (mentions.token?.kind === '/' ? 'Skills' : mentions.token?.kind === '?' ? 'Queries favoritas' : 'Dados · base → tabela');
  mentions.items.forEach((item, index) => {
    const row = el('button', 'mention-option'); row.type = 'button'; row.id = `mention-${index}`;
    row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(index === mentions.active));
    row.append(el('strong', '', item.label), el('small', '', item.detail));
    row.addEventListener('mousedown', event => event.preventDefault());
    row.addEventListener('click', () => selectMention(index));
    menu.append(row);
  });
  $('mention-menu').hidden = false;
  $('prompt').setAttribute('aria-expanded', 'true');
  if (mentions.items.length) $('prompt').setAttribute('aria-activedescendant', `mention-${mentions.active}`);
  else $('prompt').removeAttribute('aria-activedescendant');
}
function replaceMention(text) {
  const prompt = $('prompt'), token = mentions.token;
  if (!token) return false;
  const next = prompt.value.slice(0, token.start) + text + prompt.value.slice(token.end);
  if (next.length > prompt.maxLength) { notice('O pedido excede o limite de caracteres.'); return false; }
  prompt.value = next; prompt.focus();
  prompt.setSelectionRange(token.start + text.length, token.start + text.length);
  return true;
}
function selectMention(index) {
  const item = mentions.items[index]; if (!item) return;
  const prompt = $('prompt');
  const current = mentionToken(prompt.value, prompt.selectionStart);
  if (prompt.selectionStart !== prompt.selectionEnd || !current ||
      current.start !== mentions.token?.start || current.end !== mentions.token?.end ||
      current.kind !== mentions.token?.kind || current.query !== mentions.token?.query) {
    closeMentions(); return;
  }
  if (item.database) {
    if (replaceMention(`@${item.database}.`)) updateMentions();
    return;
  }
  const reference = item.favorite
    ? `Use a consulta favorita ${JSON.stringify(item.favorite.name)} da base ${JSON.stringify(item.favorite.database)} com run_favorite_query, query_id=${JSON.stringify(item.favorite.id)}. A definição ainda não foi executada. `
    : item.skill
    ? `Use a skill ${JSON.stringify(item.skill.name)}. Leia ${JSON.stringify(item.skill.document_path)} com read_doc e siga suas orientações para este pedido. `
    : `${tableReference(item.table)} `;
  const label = item.favorite ? `?${item.favorite.name} (${item.favorite.database}, ${item.favorite.id.slice(0, 8)})` : item.skill ? `/${item.skill.name}` : `@${item.table.database}.${item.table.schema}.${item.table.table}`;
  if (replaceMention(`${label} `)) {
    selectedMentions.set(label, reference); closeMentions();
  }
}
async function updateMentions() {
  const prompt = $('prompt');
  const token = prompt.selectionStart === prompt.selectionEnd ? mentionToken(prompt.value, prompt.selectionStart) : null;
  if (!token) { closeMentions(); return; }
  const revision = ++mentions.revision;
  mentions.token = token; mentions.items = []; mentions.active = 0;
  paintMentions('Carregando…');
  try {
    let items;
    if (token.kind === '/') {
      if (!mentions.skills) mentions.skills = (await mentionData('/api/skills')).skills;
      items = mentions.skills.map(skill => ({label: skill.name, detail: skill.description, skill}));
    } else if (token.kind === '?') {
      const data = await mentionData('/api/queries');
      items = data.queries.map(favorite => ({label: favorite.name, detail: `${favorite.database} · ${favorite.description || 'Consulta favorita'}`, favorite}));
    } else if (token.query.includes('.')) {
      const database = token.query.split('.')[0];
      if (!mentions.databases) mentions.databases = (await mentionData('/api/catalog/databases')).databases.filter(name => databaseOptions.includes(name));
      if (!mentions.databases.includes(database)) throw new Error('Escolha uma base disponível usando @.');
      if (!mentions.tables.has(database)) {
        const params = new URLSearchParams({database, schema: 'public'});
        const data = await mentionData(`/api/catalog/tables?${params}`);
        mentions.tables.set(database, data.tables.map(table => ({...table, database})));
      }
      items = mentions.tables.get(database).map(table => ({label: `${database}.${table.table}`, detail: `${table.schema} · tabela`, table}));
    } else {
      if (!mentions.databases) mentions.databases = (await mentionData('/api/catalog/databases')).databases.filter(name => databaseOptions.includes(name));
      items = mentions.databases.map(database => ({label: database, detail: 'Escolher tabela →', database}));
    }
    if (revision !== mentions.revision) return;
    const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
    mentions.items = items.filter(item => normalize(item.label).includes(normalize(token.query)));
    paintMentions(mentions.items.length ? '' : 'Nenhum resultado.');
  } catch (error) {
    if (revision !== mentions.revision) return;
    paintMentions(`${error.message} Digite novamente para tentar.`);
  }
}
$('prompt').addEventListener('input', updateMentions);
$('prompt').addEventListener('click', updateMentions);
$('prompt').addEventListener('keydown', event => {
  if ($('mention-menu').hidden || event.isComposing) return;
  if (event.key === 'Escape' || event.key === 'Tab') { closeMentions(); return; }
  if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { closeMentions(); return; }
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
  if (['ArrowDown', 'ArrowUp'].includes(event.key) && mentions.items.length) {
    event.preventDefault();
    mentions.active = (mentions.active + (event.key === 'ArrowDown' ? 1 : -1) + mentions.items.length) % mentions.items.length;
    paintMentions();
    $(`mention-${mentions.active}`)?.scrollIntoView({block: 'nearest'});
  } else if (event.key === 'Enter' && mentions.items.length) {
    event.preventDefault(); selectMention(mentions.active);
  }
});
document.addEventListener('click', event => {
  if (!$('prompt-form').contains(event.target)) closeMentions();
});
$('prompt-form').addEventListener('submit', closeMentions);
$('new-run').addEventListener('click', closeMentions);
