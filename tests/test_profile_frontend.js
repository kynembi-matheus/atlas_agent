'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup({saved, blocked = false, api, fetch: fetcher} = {}) {
  const nodes = new Map();
  function $(id) {
    if (!nodes.has(id)) nodes.set(id, {hidden: false, listeners: {}, attributes: {},
      addEventListener(event, callback) { this.listeners[event] = callback; },
      setAttribute(key, value) { this.attributes[key] = value; },
      removeAttribute(key) { delete this[key]; },
      showModal() { this.open = true; },
      close() { this.open = false; this.listeners.close?.(); },
    });
    return nodes.get(id);
  }
  const root = {dataset: {}};
  const storage = new Map(saved ? [['scd-theme', saved]] : []);
  const events = {};
  const navigation = [];
  const context = vm.createContext({appUrl: path => path, appPath: () => context.window.location.pathname, $, URL, document: {documentElement: root},
    localStorage: {getItem: key => { if (blocked) throw Error(); return storage.get(key); },
      setItem: (key, value) => { if (blocked) throw Error(); storage.set(key, value); }},
    window: {addEventListener: (event, callback) => { events[event] = callback; }, location: {href: 'https://atlas.test/atlas/', origin: 'https://atlas.test', assign: url => navigation.push(url)}},
    sessionStorage: {removeItem: () => {}},
    fetch: fetcher || (async () => ({ok: true, status: 204})),
    api: api || (async () => ({json: async () => ({name: 'Usuário', identity: 'Perfil local',
      scope: 'Histórico compartilhado', usage: {conversations: 2, requests: 1200, completed: 3, artifacts: 4}})})),
  });
  for (const file of ['theme.js', 'profile.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend', file), 'utf8'), context);
  return {$, root, storage, events, navigation};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('professional data and session origin are rendered literally with missing-field fallbacks', async () => {
  const {$} = setup({api: async () => ({json: async () => ({
    name: 'Ana Silva', identity: 'ana@example.test', profile: 'Analista',
    role: '<script>unsafe</script>', function: null, department: 'Crédito',
    unit_number: '001', unit_name: 'Central', auth_mode: 'development',
    usage: {conversations: 1, requests: 2, completed: 1, artifacts: 0},
  })})});
  await settle();
  assert.equal($('profile-initials').textContent, 'AS');
  assert.equal($('profile-access').textContent, 'Analista');
  assert.equal($('profile-access').hidden, false);
  assert.equal($('profile-role').textContent, '<script>unsafe</script>');
  assert.equal($('profile-function').textContent, 'Não informado');
  assert.equal($('profile-department').textContent, 'Crédito');
  assert.equal($('profile-unit').textContent, 'PA 001 · Central');
  assert.equal($('profile-session-mode').textContent, 'Ambiente de desenvolvimento');
  assert.equal($('profile-session-actions').hidden, false);
  assert.equal($('profile-body').attributes['aria-busy'], 'false');
});

test('local profile hides logout and absent access profile', async () => {
  const {$} = setup();
  await settle();
  assert.equal($('profile-access').hidden, true);
  assert.equal($('profile-session-actions').hidden, true);
  assert.equal($('profile-unit').textContent, 'Não informado');
  assert.equal($('sidebar-user-identity').textContent, 'Departamento não informado');
});

test('logout posts to server and navigates only after successful revocation', async () => {
  let called = 0;
  const {$, navigation} = setup({fetch: async (url, options) => {
    called++;
    assert.equal(url, '/logout');
    assert.equal(options.method, 'POST');
    return {ok: true, status: 204};
  }});
  await settle();
  await $('logout-profile').listeners.click();
  assert.equal(called, 1);
  assert.deepEqual(navigation, ['/login?logged_out=1']);
});

test('failed logout stays on the page with an available retry', async () => {
  const {$, navigation} = setup({fetch: async () => ({ok: false, status: 500})});
  await settle();
  await $('logout-profile').listeners.click();
  assert.equal(navigation.length, 0);
  assert.equal($('logout-profile').disabled, false);
  assert.match($('profile-session-feedback').textContent, /Não foi possível sair/);
});

test('loads signed-in identity into the sidebar before opening the dialog', async () => {
  const {$} = setup({api: async () => ({json: async () => ({
    name: 'Ana Silva', identity: 'ana@example.test', department: 'Crédito', scope: 'Histórico compartilhado',
    usage: {conversations: 0, requests: 0, completed: 0, artifacts: 0},
  })})});
  await settle();
  assert.equal($('profile-dialog').open, undefined);
  assert.equal($('sidebar-user-name').textContent, 'Ana Silva');
  assert.equal($('sidebar-user-identity').textContent, 'Crédito');
  assert.equal($('profile-identity').textContent, 'ana@example.test');
  assert.equal($('profile-name').textContent, 'Ana Silva');
  assert.match($('open-profile').attributes['aria-label'], /Ana Silva/);
});

test('refreshing profile also updates identity in the sidebar', async () => {
  let name = 'Ana';
  const {$} = setup({api: async () => ({json: async () => ({
    name, identity: `${name.toLowerCase()}@example.test`, department: name === 'Ana' ? 'Crédito' : 'Operações', scope: 'Compartilhado',
    usage: {conversations: 0, requests: 0, completed: 0, artifacts: 0},
  })})});
  await settle();
  name = 'Maria';
  $('open-profile').listeners.click();
  await settle();
  assert.equal($('sidebar-user-name').textContent, 'Maria');
  assert.equal($('profile-name').textContent, 'Maria');
  assert.equal($('sidebar-user-identity').textContent, 'Operações');
});

test('theme restores before render, toggles both ways and follows other tabs', () => {
  const {$, root, storage, events} = setup({saved: 'dark'});
  assert.equal(root.dataset.theme, 'dark');
  assert.equal($('theme-toggle').attributes['aria-checked'], 'true');
  $('theme-toggle').listeners.click();
  assert.equal(root.dataset.theme, 'light');
  assert.equal(storage.get('scd-theme'), 'light');
  $('theme-toggle').listeners.click();
  assert.equal(storage.get('scd-theme'), 'dark');
  events.storage({key: 'scd-theme', newValue: 'light'});
  assert.equal(root.dataset.theme, 'light');
  assert.equal($('theme-toggle').attributes['aria-checked'], 'false');
});

test('theme still works when browser storage is unavailable', () => {
  const {$, root} = setup({blocked: true});
  $('theme-toggle').listeners.click();
  assert.equal(root.dataset.theme, 'dark');
});

test('opening profile loads real totals and reopening refreshes usage', async () => {
  const {$} = setup();
  $('open-profile').listeners.click();
  assert.equal($('profile-dialog').open, true);
  assert.equal($('profile-stats').hidden, true);
  await settle();
  assert.equal($('usage-requests').textContent, (1200).toLocaleString('pt-BR'));
  assert.equal($('profile-stats').hidden, false);
  $('close-profile').listeners.click();
  assert.equal($('profile-dialog').open, false);
  $('open-profile').listeners.click();
  assert.equal($('profile-stats').hidden, true);
  await settle();
  assert.equal($('profile-stats').hidden, false);
});

test('failed usage hides stale totals, supports retry and keeps theme available', async () => {
  let failed = true;
  const {$, root} = setup({api: async () => {
    if (failed) throw Error('offline');
    return {json: async () => ({usage: {conversations: 0, requests: 0, completed: 0, artifacts: 0}})};
  }});
  $('open-profile').listeners.click();
  await settle();
  assert.equal($('profile-stats').hidden, true);
  assert.match($('profile-feedback').textContent, /Não foi possível/);
  $('theme-toggle').listeners.click();
  assert.equal(root.dataset.theme, 'dark');
  failed = false;
  $('close-profile').listeners.click();
  $('open-profile').listeners.click();
  await settle();
  assert.equal($('usage-requests').textContent, '0');
  assert.equal($('profile-feedback').textContent, '');
});

test('responses arriving after closing the profile do not update it', async () => {
  let resolve;
  const {$} = setup({api: () => new Promise(done => { resolve = done; })});
  $('open-profile').listeners.click();
  $('close-profile').listeners.click();
  resolve({json: async () => ({usage: {}})});
  await settle();
  assert.equal($('profile-stats').hidden, true);
});

test('signed-in profile photo appears in both locations and falls back on error', async () => {
  let photo = 'https://auth.example.test/public/photo.png';
  const {$} = setup({api: async () => ({json: async () => ({
    name: 'Ana Silva', identity: 'ana@example.test', photo_url: photo,
    usage: {conversations: 0, requests: 0, completed: 0, artifacts: 0},
  })})});
  await settle();
  for (const [image, fallback] of [['sidebar-user-photo', 'sidebar-user-initials'], ['profile-photo', 'profile-initials']]) {
    assert.equal($(image).src, photo);
    assert.equal($(image).hidden, true);
    $(image).onload();
    assert.equal($(image).hidden, false);
    assert.equal($(fallback).hidden, true);
    $(image).onerror();
    assert.equal($(image).hidden, true);
    assert.equal($(fallback).hidden, false);
  }
  photo = 'javascript:alert(1)';
  $('open-profile').listeners.click();
  await settle();
  assert.equal($('profile-photo').src, undefined);
  assert.equal($('profile-initials').hidden, false);
});

test('usage opens in a separate dialog and returns to the profile', async () => {
  const {$} = setup();
  $('open-profile').listeners.click();
  await settle();
  $('open-usage').listeners.click();
  assert.equal($('profile-dialog').open, true);
  assert.equal($('usage-dialog').open, true);
  assert.equal($('profile-stats').hidden, false);
  assert.equal($('usage-requests').textContent, '1.200');
  $('close-usage').listeners.click();
  assert.equal($('usage-dialog').open, false);
  assert.equal($('profile-dialog').open, true);
});
