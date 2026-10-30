'use strict';
(() => {
  const greetings = [
    'O que vamos descobrir juntos?',
    'Vamos dar sentido a esses números?',
    'Tem uma pergunta? Vamos aos dados!',
    'Vamos transformar curiosidade em descobertas?',
    'Dados à vista! Qual é a missão de hoje?',
    'Planilhas preparadas? Vamos nessa!',
    'Qual mistério os dados vão contar hoje?',
    'Um café, uma ideia e alguns dados. Vamos?',
    'Vamos encontrar a história por trás dos números?',
    'Pode perguntar: os dados não mordem!',
  ];
  const greeting = document.getElementById('welcome-greeting');
  if (greeting) greeting.textContent = greetings[Math.floor(Math.random() * greetings.length)];
  const descriptions = [
    'Conte o que você precisa ou escolha uma ideia para começar.',
    'Escreva sua pergunta ou escolha uma sugestão abaixo.',
    'Toda descoberta começa com uma pergunta. Qual é a sua?',
    'Diga por onde quer começar e vamos explorar juntos.',
    'Compartilhe sua ideia ou escolha um ponto de partida.',
    'Pode trazer sua dúvida: a gente começa por ela.',
    'Escolha uma sugestão ou escreva o que está pensando.',
    'Uma boa pergunta já é meio caminho andado. Vamos lá?',
  ];
  const description = document.getElementById('welcome-description');
  if (description) description.textContent = descriptions[Math.floor(Math.random() * descriptions.length)];
  const ideas = [
    ['Criar relatório', 'Crie um relatório em Excel com os principais indicadores e gráficos.'],
    ['Encontrar padrões', 'Encontre padrões e valores atípicos nos dados, com evidências e limites da análise.'],
    ['Fazer projeções', 'Faça uma projeção dos dados. Vamos definir a variável, a frequência e o horizonte.'],
    ['Comparar resultados', 'Compare os resultados disponíveis e destaque as diferenças relevantes com suas fontes.'],
    ['Resumir dados', 'Resuma os dados disponíveis e destaque os principais pontos e limitações.'],
    ['Investigar tendências', 'Analise as tendências ao longo do tempo e explique as evidências e limitações.'],
    ['Criar gráficos', 'Sugira e crie gráficos adequados para apresentar os dados disponíveis.'],
    ['Explorar oportunidades', 'Analise os dados disponíveis e identifique possíveis oportunidades, com evidências.'],
    ['Identificar riscos', 'Examine os dados disponíveis e destaque possíveis riscos, com evidências e limitações.'],
  ];
  for (let i = ideas.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [ideas[i], ideas[j]] = [ideas[j], ideas[i]];
  }
  document.querySelectorAll?.('.suggestion').forEach((button, index) => {
    if (!ideas[index]) return;
    button.dataset.prompt = ideas[index][1];
    button.lastChild.textContent = ` ${ideas[index][0]}`;
    button.querySelector('use')?.setAttribute('href', '/static/vendor/lucide/sprite.svg?v=0.468.0#icon-sparkles');
  });
})();
