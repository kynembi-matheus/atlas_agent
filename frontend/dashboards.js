'use strict';
const dashboardsState = {items: [], selected: null, revision: 0, updating: false, filters: {}, filterRevision: 0};
function dashboardDetailId() { return (typeof appPath === 'function' ? appPath() : window.location.pathname).match(/^\/(?:sites|dashboards)\/([^/]+)$/)?.[1] || null; }
function dashboardVisible() { return Boolean(dashboardDetailId()) && !document.hidden; }
async function loadDashboards() {
  const revision = ++dashboardsState.revision;
  $('dashboard-status').textContent = 'Carregando biblioteca…';
  try {
    const data = await (await api('/api/dashboards')).json();
    if (revision !== dashboardsState.revision || !['/sites', '/dashboards'].includes(typeof appPath === 'function' ? appPath() : window.location.pathname)) return;
    dashboardsState.items = data.dashboards;
    $('dashboard-count').textContent = `${data.dashboards.length} de ${data.limit} dashboards`;
    $('create-dashboard').disabled = data.dashboards.length >= data.limit;
    $('dashboard-library').replaceChildren();
    for (const item of data.dashboards) {
      const card = el('article', 'dashboard-card site-library-card');
      card.append(el('span', 'site-kind', 'DASHBOARD'), el('h2', '', item.title), el('p', 'muted', item.description));
      const actions = el('div', 'dashboard-actions');
      const open = el('a', 'secondary', 'Abrir dashboard'); open.href = appUrl(`/sites/${item.id}`);
      open.target = '_blank'; open.rel = 'noopener noreferrer';
      const remove = el('button', 'text-button danger', 'Excluir'); remove.type = 'button';
      remove.setAttribute('aria-label', `Excluir ${item.title}`);
      remove.addEventListener('click', async () => {
        if (!window.confirm(`Excluir o dashboard “${item.title}”?`)) return;
        remove.disabled = true;
        try {
          await api(`/api/dashboards/${item.id}`, {method: 'DELETE'});
          if (dashboardsState.selected?.id === item.id) {
            dashboardsState.selected = null; $('dashboard-frame').srcdoc = '';
          }
          await loadDashboards();
        } catch (error) { $('dashboard-status').textContent = error.message; remove.disabled = false; }
      });
      actions.append(open, remove); card.append(actions); $('dashboard-library').append(card);
    }
    const sites = (await (await api('/api/sites')).json()).sites;
    if (!data.dashboards.length && !sites.length) {
      const empty = el('div', 'dashboard-empty');
      empty.append(el('h2', '', 'Sua biblioteca está vazia'), el('p', 'muted', 'Crie um site ou dashboard para encontrá-lo aqui.'));
      $('dashboard-library').append(empty);
    }
    if (revision !== dashboardsState.revision || !['/sites', '/dashboards'].includes(typeof appPath === 'function' ? appPath() : window.location.pathname)) return;
    for (const item of sites) {
      const card = el('article', 'dashboard-card site-library-card');
      card.append(el('span', 'site-kind site-kind-public', 'SITE PÚBLICO'), el('h2', '', item.title), el('p', 'muted', item.description));
      const actions = el('div', 'dashboard-actions');
      const open = el('a', 'secondary', 'Abrir site'); open.href = appUrl(`/public/sites/${item.id}`); open.target = '_blank'; open.rel = 'noopener noreferrer';
      const remove = el('button', 'text-button danger', 'Excluir'); remove.type = 'button';
      remove.setAttribute('aria-label', `Excluir ${item.title}`);
      remove.addEventListener('click', async () => {
        if (!window.confirm(`Excluir o site "${item.title}"?`)) return;
        remove.disabled = true;
        try { await api(`/api/sites/${item.id}`, {method: 'DELETE'}); await loadDashboards(); }
        catch (error) { $('dashboard-status').textContent = error.message; remove.disabled = false; }
      });
      actions.append(open, remove); card.append(actions); $('dashboard-library').append(card);
    }
    $('dashboard-status').textContent = '';
    const selected = data.dashboards.find(item => item.id === window.location.hash.slice(1));
    if (selected) await openDashboard(selected);
  } catch (error) { if (revision === dashboardsState.revision) $('dashboard-status').textContent = error.message; }
}
function openDashboard(item) {
  return navigatePage(`/sites/${item.id}`);
}
async function renderDashboardPage() {
  dashboardsState.filters = {}; dashboardsState.filterRevision++;
  const id = dashboardDetailId();
  $('dashboard-detail-page').hidden = !id;
  $('dashboards-page').hidden = !['/sites', '/dashboards'].includes(typeof appPath === 'function' ? appPath() : window.location.pathname);
  if (!id) {
    dashboardsState.selected = null;
    if (['/sites', '/dashboards'].includes(typeof appPath === 'function' ? appPath() : window.location.pathname)) return loadDashboards();
    return;
  }
  const revision = ++dashboardsState.revision;
  dashboardsState.selected = null; $('dashboard-frame').srcdoc = '';
  $('dashboard-view-title').textContent = 'Dashboard';
  $('dashboard-update-status').textContent = 'Carregando dashboard…';
  try {
    const item = await (await api(`/api/dashboards/${id}`)).json();
    if (revision !== dashboardsState.revision || dashboardDetailId() !== id) return;
    dashboardsState.selected = item;
    $('dashboard-view-title').textContent = item.title;
    document.title = `${item.title} · Sites · Assistente`;
    await updateDashboard();
  } catch (error) {
    if (revision === dashboardsState.revision && dashboardDetailId() === id) $('dashboard-update-status').textContent = error.message;
  }
}
async function updateDashboard() {
  if (!dashboardVisible() || !dashboardsState.selected || dashboardsState.updating) return;
  const id = dashboardsState.selected.id;
  const filterRevision = dashboardsState.filterRevision;
  dashboardsState.updating = true; $('refresh-dashboard').disabled = true;
  $('dashboard-update-status').textContent = 'Atualizando dados…';
  try {
    const query = Object.keys(dashboardsState.filters).length
      ? `?filters=${encodeURIComponent(JSON.stringify(dashboardsState.filters))}` : '';
    const html = await (await api(`/api/dashboards/${id}/html${query}`)).text();
    if (filterRevision !== dashboardsState.filterRevision) return;
    if (dashboardsState.selected?.id !== id || dashboardDetailId() !== id || !dashboardVisible()) return;
    $('dashboard-frame').srcdoc = html;
    $('dashboard-update-status').textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR')}. Próxima atualização em 1 minuto.`;
  } catch (error) {
    if (dashboardsState.selected?.id === id && filterRevision === dashboardsState.filterRevision) {
      $('dashboard-frame').srcdoc = '';
      $('dashboard-update-status').textContent = error.message;
    }
  } finally {
    dashboardsState.updating = false; $('refresh-dashboard').disabled = false;
    if (dashboardsState.selected && (dashboardsState.selected.id !== id || filterRevision !== dashboardsState.filterRevision)) updateDashboard();
  }
}
window.addEventListener('message', event => {
  if (event.source !== $('dashboard-frame').contentWindow || !dashboardVisible()
      || event.data?.type !== 'dashboard-filters') return;
  const filters = event.data.filters;
  if (!filters || typeof filters !== 'object' || Array.isArray(filters)
      || Object.keys(filters).length > 12 || Object.entries(filters).some(([key, value]) =>
        !/^[a-z][a-z0-9_]{0,39}$/.test(key) || typeof value !== 'string' || value.length > 500)) return;
  dashboardsState.filters = filters; dashboardsState.filterRevision++;
  updateDashboard();
});
$('open-dashboards').addEventListener('click', event => { event.preventDefault(); navigatePage('/sites'); });
$('dashboard-back').addEventListener('click', event => { event.preventDefault(); navigatePage('/'); });
$('dashboard-library-back').addEventListener('click', event => { event.preventDefault(); navigatePage('/sites'); });
const siteDraft = 'Crie um site estático público sobre: ';
const dashboardDraft = 'Crie um dashboard visual com gráficos, cards de indicadores e tabelas interativas dos dados selecionados. Use pouco texto.';
function prepareSiteDraft(draft) {
  navigatePage('/');
  $('output-dashboard').checked = true;
  const prompt = $('prompt');
  if (!prompt.value.trim() || [siteDraft.trim(), dashboardDraft].includes(prompt.value.trim())) prompt.value = draft;
  prompt.focus();
}
$('create-dashboard').addEventListener('click', () => prepareSiteDraft(dashboardDraft));
$('create-site')?.addEventListener('click', () => prepareSiteDraft(siteDraft));
$('reload-dashboards').addEventListener('click', loadDashboards);
$('refresh-dashboard').addEventListener('click', updateDashboard);
window.addEventListener('hashchange', () => { if (['/sites', '/dashboards'].includes(typeof appPath === 'function' ? appPath() : window.location.pathname)) loadDashboards(); });
document.addEventListener('visibilitychange', () => { if (dashboardVisible()) updateDashboard(); });
setInterval(() => { if (dashboardVisible()) updateDashboard(); }, 60000);
renderDashboardPage();
