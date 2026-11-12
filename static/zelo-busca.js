/* Busca rápida (Ctrl+K): acha e faz.

   Cada resultado é uma linha navegável pelo teclado. Enter abre a ficha; Tab abre as ações que
   cabem na situação daquele item (devolver, entregar, ajustar), para que bipar a plaqueta em
   qualquer tela do Zelo já leve à ação, sem passar pela ficha.
   O <script> que carrega este arquivo traz a URL da API em data-url. */
(function () {
  const URL_API = document.currentScript.dataset.url;
  const cx = document.getElementById('z-paleta');
  if (!cx) return;
  const campo = document.getElementById('z-pq'), res = document.getElementById('z-pr');
  const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  let linhas = [], sel = -1, aberto = -1, pedido = 0, ultimo = null, mouseVivo = false;
  // o mouse só manda na seleção depois de se mexer de verdade: senão o ponteiro parado em cima
  // de uma linha rouba a seleção de quem está navegando pelo teclado
  document.addEventListener('mousemove', () => { mouseVivo = true; }, {passive: true});

  window.zPaleta = function (mostrar) {
    const on = mostrar !== false;
    cx.hidden = !on;
    document.body.classList.toggle('z-travado', on);
    if (on) { campo.value = ''; campo.focus(); mouseVivo = false; buscar(''); } else { linhas = []; sel = aberto = -1; }
  };

  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); zPaleta(cx.hidden); return; }
    if (e.key === 'Escape' && !cx.hidden) { e.preventDefault(); zPaleta(false); }
  });
  cx.addEventListener('mousedown', e => { if (e.target === cx) zPaleta(false); });

  let t;
  campo.addEventListener('input', () => { clearTimeout(t); const q = campo.value; t = setTimeout(() => buscar(q), 160); });

  async function buscar(q) {
    const meu = ++pedido;
    try {
      const r = await fetch(URL_API + '?q=' + encodeURIComponent(q));
      const j = await r.json();
      if (meu !== pedido) return;                 // chegou uma resposta mais nova
      ultimo = j; pinta(j, q);
    } catch (e) { res.innerHTML = '<div class="z-paleta-vazio">Não deu para buscar agora.</div>'; }
  }

  function pinta(j, q) {
    linhas = []; sel = -1; aberto = -1;
    let h = '';
    j.grupos.forEach(g => {
      if (!g.linhas.length) return;
      h += `<div class="z-pg"><i class="fa ${esc(g.icone)}"></i>${esc(g.titulo)}</div>`;
      g.linhas.forEach(l => {
        const i = linhas.length; linhas.push(l);
        h += `<div class="z-pl" data-i="${i}" role="option" tabindex="-1">
          <div class="z-pl-ico"><i class="fa ${esc(l.icone || g.icone)}"></i></div>
          <div class="z-pl-m"><div class="z-pl-t">${esc(l.titulo)}${l.cod ? ` <span class="z-mono">${esc(l.cod)}</span>` : ''}</div>
            ${l.sub ? `<div class="z-pl-s">${esc(l.sub)}</div>` : ''}</div>
          ${l.acoes && l.acoes.length ? '<i class="fa fa-ellipsis z-pl-mais" title="Tab para as ações"></i>' : ''}</div>
          ${l.acoes && l.acoes.length ? `<div class="z-pa" data-de="${i}" hidden>${l.acoes.map(a =>
            `<a class="z-acao" href="${esc(a.url)}">${esc(a.rotulo)}</a>`).join('')}</div>` : ''}`;
      });
    });
    res.innerHTML = h || `<div class="z-paleta-vazio"><i class="fa fa-magnifying-glass-minus mb-2"></i>
      <div>Nada com “${esc(q)}”.</div><small>Vale plaqueta, service tag, hostname, IMEI, nome, matrícula, linha ou Nº do lançamento.</small></div>`;
    res.querySelectorAll('.z-pl').forEach(d => {
      d.onclick = () => { sel = +d.dataset.i; abrir(); };
      d.onmouseenter = () => { if (mouseVivo) marca(+d.dataset.i, false); };
    });
    if (linhas.length) marca(0, false);
  }

  function marca(i, rola) {
    sel = Math.max(0, Math.min(linhas.length - 1, i));
    res.querySelectorAll('.z-pl').forEach(d => d.classList.toggle('sel', +d.dataset.i === sel));
    if (rola !== false) res.querySelector('.z-pl.sel')?.scrollIntoView({block: 'nearest'});
  }
  function acoes(i, mostrar) {
    const box = res.querySelector(`.z-pa[data-de="${i}"]`);
    if (!box) return false;
    box.hidden = !mostrar; aberto = mostrar ? i : -1;
    if (mostrar) { box.querySelector('a')?.focus(); box.scrollIntoView({block: 'nearest'}); }
    return true;
  }
  function abrir() { const l = linhas[sel]; if (l) location.href = l.url; }

  campo.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); marca(sel + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); marca(sel - 1); }
    else if (e.key === 'Enter') { e.preventDefault(); abrir(); }
    else if (e.key === 'Tab' && !e.shiftKey && sel >= 0) { if (acoes(sel, true)) e.preventDefault(); }
  });
  res.addEventListener('keydown', e => {
    if (e.key === 'Escape' || (e.key === 'Tab' && e.shiftKey)) { e.preventDefault(); acoes(aberto, false); campo.focus(); }
  });
})();
