from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app import db
from app.auth import exige, pode, registrar_log
from app.manutencao import ACOES_MANUT, registrar
from app.models import FORNEC_MANUT, STATUS_MANUT, Consumivel, Item, Manutencao, cfg_lista

manutencao_bp = Blueprint('manutencao', __name__)


def _avisar_sd(codigo):
    """Máquina que entra ou sai de manutenção muda de estado no Service Desk (In Repair e volta)."""
    from flask import current_app
    from app import servicedesk as sd
    from app.routes.consulta import achar_item
    it = achar_item(codigo)
    if it:
        sd.enfileirar_item(current_app._get_current_object(), it)
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
            _avisar_sd(d['item'])
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
    quadro = {st: [m for m in abertas if m.status == st] for st in STATUS_MANUT if st not in ('Concluída', 'Sem conserto')}
    outros = [m for m in abertas if m.status not in quadro]
    if outros:
        quadro[STATUS_MANUT[0]] = outros + quadro[STATUS_MANUT[0]]
    return dict(quadro=quadro, d=d, acoes=ACOES_MANUT, status=STATUS_MANUT, fornec=FORNEC_MANUT, tecnicos=cfg_lista('tecnicos'),
                pecas=[c.nome for c in Consumivel.query.order_by(Consumivel.nome)], pool=pool, abertas=abertas,
                fechadas=[m for m in todas if not m.aberta][:50], itens=itens)


@manutencao_bp.route('/api/manutencao/status', methods=['POST'])
@exige('lancar')
def api_status():
    """Arrastar a ocorrência no quadro: muda o status; soltar em Concluída fecha."""
    from flask import jsonify
    j = request.get_json(silent=True) or {}
    os_ = db.session.get(Manutencao, int(j.get('id') or 0))
    para = j.get('para')
    if not os_ or not os_.aberta or para not in STATUS_MANUT:
        return jsonify(ok=False, msg='Ocorrência não encontrada ou já fechada')
    if para == os_.status:
        return jsonify(ok=True, msg='')
    if para in ('Concluída', 'Sem conserto'):
        if os_.substituto:
            sub = db.session.get(Item, os_.substituto)
            if sub and sub.situacao == 'Emprestado':
                return jsonify(ok=False, ir=url_for('manutencao.inicio', acao='Fechar ocorrência', item=os_.item),
                               msg=f'O backup {sub.codigo} está com {sub.com_quem}: diga se ele volta ao fechar')
        ok, msg = registrar({'acao': 'Fechar ocorrência', 'item': os_.item, 'status': para if para == 'Sem conserto' else ''},
                            g.usuario.nome)
    else:
        ok, msg = registrar({'acao': 'Atualizar ocorrência', 'item': os_.item, 'status': para}, g.usuario.nome)
    if ok:
        registrar_log('manutenção', f'{os_.item}: {msg}')
        _avisar_sd(os_.item)
    return jsonify(ok=ok, msg=msg)
