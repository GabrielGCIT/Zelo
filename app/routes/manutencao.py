from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app import db
from app.auth import exige, pode, registrar_log
from app.manutencao import ACOES_MANUT, registrar
from app.models import FORNEC_MANUT, STATUS_MANUT, Consumivel, Item, Manutencao, cfg_lista

manutencao_bp = Blueprint('manutencao', __name__)
CAMPOS = ('acao', 'item', 'defeito', 'fornecedor', 'caso', 'status', 'visita', 'tecnico', 'chamado', 'backup', 'peca', 'qtd',
          'feito', 'backup_volta', 'obs')


@manutencao_bp.route('/manutencao', methods=['GET', 'POST'])
@exige('ver')
def inicio():
    if request.method == 'POST':
        if not pode('lancar'):
            flash('Seu perfil é só de consulta.', 'danger')
            return redirect(url_for('manutencao.inicio'))
        d = {k: (request.form.get(k) or '').strip() for k in CAMPOS}
        ok, msg = registrar(d, g.usuario.nome)
        if ok:
            registrar_log('manutenção', f'{d["item"]}: {msg}')
            flash('OK → ' + msg, 'success')
            return redirect(url_for('manutencao.inicio'))
        flash(msg, 'danger')
        return render_template('manutencao.html', **_ctx(d))
    return render_template('manutencao.html', **_ctx({'acao': request.args.get('acao', ''), 'item': request.args.get('item', '')}))


def _ctx(d):
    todas = Manutencao.query.order_by(Manutencao.id.desc()).all()
    abertas = [m for m in todas if m.aberta]
    itens = {i.codigo: i for i in Item.query.filter(Item.codigo.in_([m.item for m in todas[:300]])).all()}
    pool = [i.codigo for i in Item.query.filter_by(finalidade='Pool de empréstimo', situacao='Em estoque').order_by(Item.codigo)]
    return dict(d=d, acoes=ACOES_MANUT, status=STATUS_MANUT, fornec=FORNEC_MANUT, tecnicos=cfg_lista('tecnicos'),
                pecas=[c.nome for c in Consumivel.query.order_by(Consumivel.nome)], pool=pool, abertas=abertas,
                fechadas=[m for m in todas if not m.aberta][:50], itens=itens)
