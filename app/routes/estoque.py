from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from app.auth import exige, pode, registrar_log
from app.estoque import MOVIMENTOS, cadastrar_consumivel, conferir_item, mover, saldos
from app.models import SITES, Compra, Consumivel, MovConsumivel

estoque_bp = Blueprint('estoque', __name__)


@estoque_bp.route('/consumiveis', methods=['GET', 'POST'])
@exige('ver')
def consumiveis():
    if request.method == 'POST':
        if not pode('lancar'):
            flash('Seu perfil é só de consulta.', 'danger')
            return redirect(url_for('estoque.consumiveis'))
        f = {k: (request.form.get(k) or '').strip() for k in request.form}
        if f.get('acao') == 'catalogo':
            ok, msg = cadastrar_consumivel(f.get('item_c'), f.get('marca_c'), f.get('compat_c'), f.get('minimo_c'))
        else:
            ok, msg = mover(f, g.usuario.nome)
        if ok:
            registrar_log('consumível', msg)
        flash(msg, 'success' if ok else 'danger')
        return redirect(url_for('estoque.consumiveis', c=f.get('consumivel', '')))
    sal = saldos()
    cat = Consumivel.query.order_by(Consumivel.nome).all()
    sites = [s for s in SITES if any(sal[c.nome].get(s) for c in cat)] or ['EC']
    filtro = request.args.get('c', '')
    movs = MovConsumivel.query
    if filtro:
        movs = movs.filter_by(consumivel=filtro)
    movs = movs.order_by(MovConsumivel.id.desc()).limit(80).all()
    return render_template('consumiveis.html', cat=cat, sal=sal, sites=sites, todos_sites=SITES, movimentos=MOVIMENTOS,
                           movs=movs, filtro=filtro,
                           compras=[c.compra for c in Compra.query.filter(Compra.status.notin_(('Recebido', 'Cancelado')))])


@estoque_bp.route('/api/item-novo/conferir', methods=['POST'])
@exige('lancar')
def api_conferir_item():
    st, msg = conferir_item(request.get_json(silent=True) or {})
    return jsonify({'status': st, 'msg': msg})
