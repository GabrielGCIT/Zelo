from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app import db
from app.auth import exige, registrar_log
from app.desligamento import ACOES_LINHA, devolver_tudo, o_que_tem, pendentes, total
from app.models import Pessoa, cfg_lista

desligar_bp = Blueprint('desligar', __name__)


@desligar_bp.route('/desligamentos')
@exige('ver')
def lista():
    """Quem saiu e ainda consta com alguma coisa."""
    return render_template('desligamentos.html', fila=pendentes())


@desligar_bp.route('/desligamento/<path:pid>', methods=['GET', 'POST'])
@exige('ver')
def ficha(pid):
    """Tudo que está com a pessoa, numa fila só, para devolver de uma vez."""
    p = db.session.get(Pessoa, pid) or abort(404)
    if request.method == 'POST':
        from app.auth import pode
        if not pode('lancar'):
            abort(403)
        escolhas = {
            'itens': request.form.getlist('item'),
            'linhas': {n: request.form.get(f'linha_acao_{n}', 'Devolver') for n in request.form.getlist('linha')},
            'kit': [tuple(x.split('|', 1)) for x in request.form.getlist('kit') if '|' in x],
            'acess': request.form.getlist('acess'),
            'receb_por': (request.form.get('receb_por') or '').strip(),
            'obs': (request.form.get('obs') or '').strip(),
        }
        ok, msg, detalhes = devolver_tudo(p, escolhas, g.usuario.nome)
        if ok:
            registrar_log('desligamento', f'{p.id} {p.nome}: {msg}')
        flash(msg, 'success' if ok else 'danger')
        for d in detalhes[:12]:
            if ': OK' not in d and 'voltou' not in d and 'devolvido' not in d:
                flash(d, 'warning')
        return redirect(url_for('desligar.ficha', pid=pid))
    t = o_que_tem(pid)
    return render_template('desligamento.html', p=p, t=t, n=total(t), acoes_linha=ACOES_LINHA,
                           recebido=cfg_lista('recebido_por'))
