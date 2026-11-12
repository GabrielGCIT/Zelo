/* Quadro de assinatura: caneta no tablet, dedo no celular ou mouse no notebook.

   Usa Pointer Events, que chegam igual nos três casos, então não há um caminho para toque e
   outro para mouse. Dois cuidados que decidem se a assinatura sai parecida com a da pessoa:

   - o canvas é desenhado na resolução real da tela (devicePixelRatio), senão o traço sai
     serrilhado no tablet e feio no PDF;
   - a linha é suavizada por ponto médio em vez de ligar ponto a ponto, que é o que faz o
     traço de dedo parecer um gráfico de barras.

   `touch-action: none` no elemento impede a tela de rolar enquanto se assina — sem isso, no
   tablet, cada traço arrasta a página. */
function zAssinatura(canvas, aoMudar) {
  const ctx = canvas.getContext('2d');
  let desenhando = false, pontos = [], temTinta = false, pilha = [];

  function dimensionar() {
    const r = canvas.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 3);
    const antes = temTinta ? ctx.getImageData(0, 0, canvas.width, canvas.height) : null;
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#111827';
    if (antes) { try { ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.putImageData(antes, 0, 0); ctx.restore(); } catch (e) {} }
  }
  const onde = e => { const r = canvas.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };

  function comeca(e) {
    if (e.button !== undefined && e.button !== 0) return;      // só o botão principal
    e.preventDefault();
    canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
    try { pilha.push(ctx.getImageData(0, 0, canvas.width, canvas.height)); if (pilha.length > 12) pilha.shift(); } catch (err) {}
    desenhando = true; pontos = [onde(e)];
    // um toque curto também marca: um ponto é um pingo, não um traço perdido
    ctx.beginPath(); ctx.arc(pontos[0].x, pontos[0].y, 1.1, 0, Math.PI * 2); ctx.fillStyle = '#111827'; ctx.fill();
    marcar();
  }
  function move(e) {
    if (!desenhando) return;
    e.preventDefault();
    // eventos coalescidos: no tablet vêm vários por quadro e é isso que dá fluidez ao traço
    const lista = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of lista) {
      pontos.push(onde(ev));
      if (pontos.length < 3) continue;
      const [a, b, c] = pontos.slice(-3);
      const m1 = {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}, m2 = {x: (b.x + c.x) / 2, y: (b.y + c.y) / 2};
      ctx.beginPath(); ctx.moveTo(m1.x, m1.y); ctx.quadraticCurveTo(b.x, b.y, m2.x, m2.y); ctx.stroke();
    }
  }
  function termina(e) { if (!desenhando) return; desenhando = false; pontos = []; if (e) e.preventDefault(); }
  function marcar() { if (!temTinta) { temTinta = true; aoMudar && aoMudar(true); } }

  canvas.addEventListener('pointerdown', comeca);
  canvas.addEventListener('pointermove', move);
  ['pointerup', 'pointercancel', 'pointerleave'].forEach(t => canvas.addEventListener(t, termina));
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  addEventListener('resize', dimensionar);
  dimensionar();

  return {
    limpar() { ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.restore();
               pilha = []; temTinta = false; aoMudar && aoMudar(false); },
    voltar() { const p = pilha.pop(); if (!p) return;
               ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
               ctx.putImageData(p, 0, 0); ctx.restore();
               if (!pilha.length) { temTinta = false; aoMudar && aoMudar(false); } },
    temTinta: () => temTinta,
    /* PNG recortado no que foi desenhado: o servidor recebe a assinatura, não a folha em branco,
       e o PDF encaixa o traço sem margens enormes em volta. */
    png() {
      if (!temTinta) return '';
      let d; try { d = ctx.getImageData(0, 0, canvas.width, canvas.height); } catch (e) { return canvas.toDataURL('image/png'); }
      let x0 = canvas.width, y0 = canvas.height, x1 = 0, y1 = 0;
      for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
        if (d.data[(y * canvas.width + x) * 4 + 3] > 40) {
          if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; } }
      if (x1 < x0 || y1 < y0) return canvas.toDataURL('image/png');
      const m = 8;
      x0 = Math.max(0, x0 - m); y0 = Math.max(0, y0 - m);
      x1 = Math.min(canvas.width - 1, x1 + m); y1 = Math.min(canvas.height - 1, y1 + m);
      const c2 = document.createElement('canvas');
      c2.width = x1 - x0 + 1; c2.height = y1 - y0 + 1;
      c2.getContext('2d').drawImage(canvas, x0, y0, c2.width, c2.height, 0, 0, c2.width, c2.height);
      return c2.toDataURL('image/png');
    },
  };
}
