'use strict';
// O payload transporta somente uma referência a um item registrado nesta página.
const chatDragMime = 'application/x-atlas-chat-item';
const chatDragItems = new Map();
let chatDragSequence = 0;

function registerChatDrag(node, kind, id, label, action, isCurrent = () => true) {
  const key = `${kind}:${id}`;
  const token = String(++chatDragSequence);
  chatDragItems.set(key, {token, action, isCurrent});
  node.draggable = true;
  node.classList.toggle('chat-draggable', true);
  node.title = 'Arraste para o campo da mensagem ou use o botão para adicionar.';
  node.addEventListener('dragstart', event => {
    if (event.target?.closest?.('button, input, textarea, select, a, summary')) {
      event.preventDefault(); return;
    }
    event.dataTransfer.effectAllowed = 'copy';
    event.dataTransfer.setData(chatDragMime, JSON.stringify({key, token}));
    event.dataTransfer.setData('text/plain', label);
  });
  node.addEventListener('dragend', () => $('prompt-form').classList.toggle('table-drop-target', false));
}

$('prompt-form').addEventListener('dragover', event => {
  if (!Array.from(event.dataTransfer.types).includes(chatDragMime)) return;
  event.preventDefault(); event.dataTransfer.dropEffect = 'copy';
  $('prompt-form').classList.toggle('table-drop-target', true);
});
$('prompt-form').addEventListener('dragleave', () => $('prompt-form').classList.toggle('table-drop-target', false));
$('prompt-form').addEventListener('drop', event => {
  const payload = event.dataTransfer.getData(chatDragMime);
  if (!payload) return;
  event.preventDefault(); $('prompt-form').classList.toggle('table-drop-target', false);
  try {
    if (payload.length > 1024) throw new Error('invalid');
    const item = JSON.parse(payload);
    const registered = chatDragItems.get(item.key);
    if (!registered || registered.token !== item.token || !registered.isCurrent()) {
      notice('Este item não está mais disponível. Abra o painel e escolha novamente.'); return;
    }
    registered.action(); $('prompt').focus();
  } catch (_) { notice('Não foi possível adicionar o item arrastado.'); }
});
