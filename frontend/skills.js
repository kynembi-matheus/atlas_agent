'use strict';
let skillsLoading = false;

function chooseSkill(skill) {
  const prompt = $('prompt');
  const instruction = `Use a skill ${JSON.stringify(skill.name)}. Leia ${JSON.stringify(skill.document_path)} com read_doc e siga suas orientações para este pedido.`;
  const next = `${prompt.value}${prompt.value ? '\n' : ''}${instruction}\n`;
  if (next.length > prompt.maxLength) { notice('O pedido excede o limite de caracteres. Reduza o texto antes de adicionar a skill.'); return; }
  prompt.value = next; prompt.focus();
}
async function loadSkills() {
  if (skillsLoading) return;
  skillsLoading = true;
  $('skills-status').textContent = 'Carregando skills…';
  $('retry-skills').hidden = true; $('skills-list').replaceChildren();
  try {
    const data = await (await api('/api/skills')).json();
    for (const skill of data.skills) {
      const card = el('article', 'skill-card');
      card.append(el('h3', '', skill.name), el('p', 'muted', skill.description));
      const button = el('button', 'secondary', 'Usar no chat'); button.type = 'button';
      button.setAttribute('aria-label', `Usar ${skill.name} no chat`);
      button.addEventListener('click', () => chooseSkill(skill));
      card.append(button); $('skills-list').append(card);
    }
    $('skills-status').textContent = data.skills.length ? `${data.skills.length} skill(s) disponível(is).` : 'Nenhuma skill disponível.';
  } catch (error) { $('skills-status').textContent = error.message; $('retry-skills').hidden = false; }
  finally { skillsLoading = false; }
}
function setSkillsOpen(open) {
  if (open) {
    $('data-preview').hidden = true;
    $('toggle-preview').setAttribute('aria-expanded', 'false');
    $('imports-panel').hidden = true;
    $('toggle-imports').setAttribute('aria-expanded', 'false');
  }
  $('skills-panel').hidden = !open;
  $('toggle-skills').setAttribute('aria-expanded', String(open));
  document.body.classList.toggle('preview-open', open);
  if (open) { $('close-skills').focus(); loadSkills(); }
  else $('toggle-skills').focus();
}
$('toggle-skills').addEventListener('click', () => setSkillsOpen($('skills-panel').hidden));
$('close-skills').addEventListener('click', () => setSkillsOpen(false));
$('skills-panel').addEventListener('keydown', event => { if (event.key === 'Escape') setSkillsOpen(false); });
$('retry-skills').addEventListener('click', loadSkills);
