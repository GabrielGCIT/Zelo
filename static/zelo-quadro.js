/* Quadros de arrastar (kanban) do Zelo. Sem biblioteca: arrastar nativo + menu "Mover para" (toque e teclado).
   <div class="z-quadro" data-url="/api/..."> <div class="z-col" data-col="X"><div class="z-col-corpo"> cartões .z-kc[data-id] */
/* zAviso e zPost vêm do zelo.js, carregado pelo base.html. */
function zContar(q) { q.querySelectorAll('.z-col').forEach(c => { const n = c.querySelectorAll('.z-kc').length; const b = c.querySelector('.z-col-n'); if (b) b.textContent = n;
  const v = c.querySelector('.z-col-vazio'); if (v) v.hidden = n > 0; }); }
function zQuadro(q, aoMover) {
  let arrastando = null;
  const mover = async (card, col) => {
    const de = card.closest('.z-col'); if (!col || col === de) return;
    if (col.dataset.aceita === 'nao') { zAviso('Não dá para mover para "' + col.dataset.col + '" por aqui.', 'aviso'); return; }
    const corpo = col.querySelector('.z-col-corpo'), volta = card.nextSibling, corpoDe = card.parentNode;
    corpo.prepend(card); card.classList.add('z-salvando'); zContar(q);
    let r; try { r = await aoMover(card, col.dataset.col, de.dataset.col); } catch (e) { r = {ok: false, msg: e.message}; }
    card.classList.remove('z-salvando');
    if (!r || !r.ok) { corpoDe.insertBefore(card, volta); zContar(q); if (r && r.ir) { location.href = r.ir; return; } zAviso((r && r.msg) || 'Não foi possível mover.', 'erro'); return; }
    card.classList.add('z-pousou'); setTimeout(() => card.classList.remove('z-pousou'), 600);
    if (r.msg) zAviso(r.msg, 'ok', r.link);
    if (r.some) { card.classList.add('z-some'); setTimeout(() => { card.remove(); zContar(q); }, 350); }
    if (r.trava) card.draggable = false;
  };
  q.querySelectorAll('.z-kc').forEach(card => {
    card.addEventListener('dragstart', e => { if (!card.draggable) return; arrastando = card; card.classList.add('z-arrastando'); q.classList.add('z-em-arrasto'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', card.dataset.id); });
    card.addEventListener('dragend', () => { card.classList.remove('z-arrastando'); q.classList.remove('z-em-arrasto'); q.querySelectorAll('.z-sobre').forEach(c => c.classList.remove('z-sobre')); arrastando = null; });
    card.querySelectorAll('[data-mover]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); mover(card, q.querySelector('.z-col[data-col="' + a.dataset.mover + '"]')); }));
  });
  q.querySelectorAll('.z-col').forEach(col => {
    col.addEventListener('dragover', e => { if (!arrastando) return; e.preventDefault(); col.classList.add('z-sobre'); });
    col.addEventListener('dragleave', e => { if (!col.contains(e.relatedTarget)) col.classList.remove('z-sobre'); });
    col.addEventListener('drop', e => { e.preventDefault(); col.classList.remove('z-sobre'); if (arrastando) mover(arrastando, col); });
  });
  zContar(q);
  return {mover};
}
