/* Peças que todas as telas do Zelo usam: tema, token do formulário, aviso flutuante, POST em JSON
   e a busca rápida (Ctrl+K). Carregado pelo base.html, antes dos scripts de cada tela. */
function zTema() {
  var a = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-bs-theme', a);
  try { localStorage.setItem('zelo-tema', a); } catch (e) {}
  document.dispatchEvent(new CustomEvent('zelo:tema', {detail: a}));
}
function zCsrf() { var m = document.querySelector('meta[name=csrf-token]'); return m ? m.content : ''; }

/* Aviso flutuante no canto: some sozinho. tipo: 'ok' | 'aviso' | 'erro'. */
function zAviso(msg, tipo, link) {
  let box = document.getElementById('z-avisos');
  if (!box) { box = document.createElement('div'); box.id = 'z-avisos'; document.body.appendChild(box); }
  const t = document.createElement('div');
  t.className = 'z-toast ' + (tipo || 'ok');
  t.innerHTML = '<i class="fa ' + (tipo === 'erro' ? 'fa-circle-xmark' : tipo === 'aviso' ? 'fa-triangle-exclamation' : 'fa-circle-check') + '"></i><span></span>';
  t.querySelector('span').textContent = msg;
  if (link) { const a = document.createElement('a'); a.href = link.href; a.textContent = link.texto; t.appendChild(a); }
  box.appendChild(t);
  setTimeout(() => { t.classList.add('sai'); setTimeout(() => t.remove(), 300); }, tipo === 'erro' ? 7000 : 4000);
}

async function zPost(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': zCsrf()},
                              body: JSON.stringify(body)});
  if (!r.ok) throw new Error(r.status === 403 ? 'Seu perfil não permite essa ação' : 'Erro ' + r.status);
  return r.json();
}
