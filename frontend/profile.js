'use strict';
(() => {
  const dialog = $('profile-dialog');
  const toggle = $('theme-toggle');
  let revision = 0;
  const text = value => typeof value === 'string' && value.trim() ? value.trim() : 'Não informado';
  const initials = name => (name || 'Usuário').trim().split(/\s+/).filter(Boolean).filter((_, index, words) => index === 0 || index === words.length - 1).map(word => Array.from(word)[0]).join('').toLocaleUpperCase('pt-BR');
  function updatePhoto(value) {
    let url = '';
    try {
      const parsed = new URL(value, window.location.href);
      if (typeof value === 'string' && value.trim() &&
          (parsed.protocol === 'https:' || parsed.origin === window.location.origin && parsed.protocol === 'http:')) url = parsed.href;
    } catch (_) { /* URL ausente ou inválida. */ }
    for (const [photoId, initialsId] of [['sidebar-user-photo', 'sidebar-user-initials'], ['profile-photo', 'profile-initials']]) {
      const photo = $(photoId), fallback = $(initialsId);
      photo.hidden = true;
      fallback.hidden = false;
      photo.onload = () => { photo.hidden = false; fallback.hidden = true; };
      photo.onerror = () => { photo.hidden = true; fallback.hidden = false; };
      if (url) photo.src = url;
      else photo.removeAttribute('src');
    }
  }
  const syncTheme = () => toggle.setAttribute('aria-checked', String(document.documentElement.dataset.theme === 'dark'));
  syncTheme();
  toggle.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('scd-theme', theme); } catch (_) { /* Keep the current-page preference. */ }
    syncTheme();
  });
  window.addEventListener('storage', event => {
    if (event.key !== 'scd-theme' && event.key !== null) return;
    document.documentElement.dataset.theme = event.newValue === 'dark' ? 'dark' : 'light';
    syncTheme();
  });
  function updateSidebarUsage(usage) {
    const windows = [['six_hours', '6 horas'], ['week', '7 dias']]
      .map(([key, label]) => ({label, ...usage?.[key]}))
      .filter(item => Number.isFinite(item.tokens) && Number.isFinite(item.limit) && item.limit > 0);
    const button = $('sidebar-usage');
    if (!windows.length) { button.hidden = true; return; }
    const highest = windows.reduce((a, b) => a.tokens / a.limit >= b.tokens / b.limit ? a : b);
    const percent = Math.min(100, Math.round(highest.tokens / highest.limit * 100));
    $('sidebar-usage-percent').textContent = `${percent}%`;
    $('sidebar-usage-period').textContent = `Maior uso: ${highest.label}`;
    $('sidebar-usage-fill').style.width = `${percent}%`;
    button.setAttribute('aria-label', `Uso de IA: ${percent}% do limite de ${highest.label}. Abrir detalhes.`);
    button.hidden = false;
  }
  async function refreshSidebarUsage() {
    try {
      const profile = await (await api('/api/profile')).json();
      updateSidebarUsage(profile.token_usage);
    } catch (_) { /* Preserve the last known value if the refresh fails. */ }
  }
  async function loadProfile({background = false} = {}) {
    const current = ++revision;
    $('profile-stats').hidden = true;
    $('token-usage').hidden = true;
    $('profile-body').setAttribute('aria-busy', 'true');
    $('profile-feedback').textContent = 'Atualizando informações do perfil…';
    try {
      const profile = await (await api('/api/profile')).json();
      if (current !== revision || (!background && !dialog.open)) return;
      $('sidebar-user-name').textContent = profile.name;
      $('sidebar-user-identity').textContent = typeof profile.department === 'string' && profile.department.trim() ? profile.department.trim() : 'Departamento não informado';
      $('open-profile').setAttribute('aria-label', `Abrir perfil e uso de ${profile.name}`);
      $('profile-name').textContent = profile.name;
      $('profile-identity').textContent = profile.identity;
      $('profile-initials').textContent = initials(profile.name);
      $('sidebar-user-initials').textContent = initials(profile.name);
      updatePhoto(profile.photo_url);
      $('profile-access').textContent = profile.profile || '';
      $('profile-access').hidden = !profile.profile;
      for (const field of ['role', 'function', 'department']) $('profile-' + field).textContent = text(profile[field]);
      const number = profile.unit_number;
      const unit = [number !== null && number !== undefined && String(number).trim() ? `PA ${number}` : '', profile.unit_name].filter(Boolean).join(' · ');
      $('profile-unit').textContent = unit || 'Não informado';
      const mode = profile.auth_mode || 'local';
      $('profile-session-mode').setAttribute('data-mode', mode);
      $('profile-session-mode').textContent = {sso: 'Sessão autenticada', development: 'Ambiente de desenvolvimento', local: 'Perfil local'}[mode] || 'Perfil local';
      $('profile-source').textContent = {sso: 'Dados fornecidos pelo ScdAuth.', development: 'Dados do ambiente de desenvolvimento.', local: 'Informações profissionais indisponíveis neste perfil local.'}[mode];
      $('profile-session-actions').hidden = mode === 'local';
      $('profile-scope').textContent = profile.scope;
      for (const key of ['conversations', 'requests', 'completed', 'artifacts']) {
        $(`usage-${key}`).textContent = profile.usage[key].toLocaleString('pt-BR');
      }
      const usage = profile.token_usage || {};
      updateSidebarUsage(usage);
      for (const [key, id, label] of [['six_hours', 'six-hours', 'Últimas 6 horas'], ['week', 'week', 'Últimos 7 dias']]) {
        const item = usage[key];
        if (!item) continue;
        const release = item.available_at ? ` · liberação estimada: ${new Date(item.available_at).toLocaleString('pt-BR')}` : '';
        $(`token-usage-${id}`).textContent = `${label}: ${item.tokens.toLocaleString('pt-BR')} de ${item.limit.toLocaleString('pt-BR')} tokens${release}`;
        $(`token-progress-${id}`).value = Math.min(100, item.tokens / item.limit * 100);
      }
      $('token-usage-note').textContent = (usage.week?.unavailable || 0) ? `${usage.week.unavailable} chamada(s) sem dados de consumo do provedor.` : 'O consumo anterior à ativação não está incluído.';
      $('token-usage').hidden = !usage.week;
      $('profile-stats').hidden = false;
      $('profile-feedback').textContent = '';
    } catch (_) {
      if (current === revision && dialog.open) $('profile-feedback').textContent = 'Não foi possível atualizar o perfil. Feche e abra o perfil para tentar novamente.';
    } finally {
      if (current === revision) {
        $('profile-body').setAttribute('aria-busy', 'false');
      }
    }
  }
  $('open-profile').addEventListener('click', () => {
    dialog.showModal();
    $('profile-body').scrollTop = 0;
    syncTheme();
    loadProfile();
  });
  $('sidebar-usage').addEventListener('click', () => {
    $('usage-dialog').showModal();
    loadProfile({background: true});
  });
  window.setInterval?.(() => { if (!document.hidden) refreshSidebarUsage(); }, 60000);
  $('open-usage').addEventListener('click', () => $('usage-dialog').showModal());
  $('close-usage').addEventListener('click', () => $('usage-dialog').close());
  $('close-profile').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { revision++; $('profile-body').setAttribute('aria-busy', 'false'); });
  $('logout-profile').addEventListener('click', async () => {
    const button = $('logout-profile');
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Saindo…';
    $('profile-session-feedback').textContent = '';
    $('profile-body').setAttribute('aria-busy', 'false');
    revision++;
    try {
      const response = await fetch(appUrl('/logout'), {method: 'POST', credentials: 'same-origin'});
      if (!response.ok && response.status !== 401) throw new Error('logout');
      try { sessionStorage.removeItem('scd-import-session'); } catch (_) { /* Armazenamento indisponível. */ }
      window.location.assign(appUrl('/login?logged_out=1'));
    } catch (_) {
      $('profile-session-feedback').textContent = 'Não foi possível sair. Tente novamente.';
      button.disabled = false;
      button.textContent = 'Sair da sessão';
    }
  });
  loadProfile({background: true});
})();
