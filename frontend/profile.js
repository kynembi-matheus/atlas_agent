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
  async function loadProfile({background = false} = {}) {
    const current = ++revision;
    $('profile-stats').hidden = true;
    $('profile-body').setAttribute('aria-busy', 'true');
    $('profile-feedback').textContent = 'Atualizando informações do perfil…';
    $('refresh-profile').disabled = true;
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
      $('profile-stats').hidden = false;
      $('profile-feedback').textContent = '';
    } catch (_) {
      if (current === revision && dialog.open) $('profile-feedback').textContent = 'Não foi possível atualizar o perfil. Tente novamente em Atualizar perfil.';
    } finally {
      if (current === revision) {
        $('refresh-profile').disabled = false;
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
  $('close-profile').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { revision++; $('refresh-profile').disabled = false; $('profile-body').setAttribute('aria-busy', 'false'); });
  $('refresh-profile').addEventListener('click', loadProfile);
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
      $('refresh-profile').disabled = false;
    }
  });
  loadProfile({background: true});
})();
