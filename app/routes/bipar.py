from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, url_for

from app import db
from app.auth import exige, registrar_log
from app.bipagem import MODOS, codigos_de_itens, fila, gravar_fila, modo_ok
from app.models import MOTIVOS, SITES, Item, cfg_lista

bipar_bp = Blueprint('bipar', __name__)
MAX_FILA = 300


def _codigos(j):
    c = (j or {}).get('codigos') or []
    return [str(x) for x in c][:MAX_FILA]


@bipar_bp.route('/bipar', methods=['GET', 'POST'])
@exige('lancar')
def inicio():
    """Fila de bipagem: escolhe a ação uma vez e bipa tudo. Também recebe a seleção da lista de Itens."""
    modo = modo_ok(request.values.get('modo', 'devolver'))
    pre = codigos_de_itens(request.form.getlist('codigo') or request.args.getlist('c'))
    return render_template('bipar.html', modos=MODOS, modo=modo, pre=pre, motivos=MOTIVOS, sites=SITES,
                           recebido=cfg_lista('recebido_por'), tecnicos=cfg_lista('tecnicos'),
                           kit=['Mouse + teclado', 'Só mouse', 'Só teclado', 'Nenhum'], max_fila=MAX_FILA)


@bipar_bp.route('/api/bipar/fila', methods=['POST'])
@exige('lancar')
def api_fila():
    j = request.get_json(silent=True) or {}
    return jsonify(fila(j.get('modo'), _codigos(j), j.get('comum')))


@bipar_bp.route('/api/bipar/gravar', methods=['POST'])
@exige('lancar')
def api_gravar():
    j = request.get_json(silent=True) or {}
    n, lote, saida = gravar_fila(j.get('modo'), _codigos(j), j.get('comum'), g.usuario.nome)
    if n:
        registrar_log('bipagem', f'{saida["acao"]}: {n} item(ns), lote {lote}')
        from flask import current_app
        from app import servicedesk as sd
        sd.enfileirar_tudo(current_app._get_current_object(), saida.pop('movs', []))
    saida.pop('movs', None)
    return jsonify(dict(saida, gravadas=n, lote=lote))


# ------------------------------------------------------------------ etiqueta com código de barras
@bipar_bp.route('/etiquetas', methods=['GET', 'POST'])
@exige('ver')
def etiquetas():
    """Folha de etiquetas para imprimir e colar no equipamento (Code 128 da plaqueta)."""
    from app.etiqueta import codigo_do_item, svg
    cods = request.form.getlist('codigo') or request.args.getlist('c')
    itens = [i for i in (db.session.get(Item, c) for c in dict.fromkeys(cods)) if i]
    if not itens:
        return redirect(url_for('consulta.itens'))
    try:
        copias = max(1, min(20, int(request.values.get('copias') or 1)))
    except ValueError:
        copias = 1
    etq = [(it, svg(codigo_do_item(it))) for it in itens for _ in range(copias)]
    return render_template('etiquetas.html', etq=etq, n=len(itens), copias=copias,
                           codigos=[i.codigo for i in itens])


@bipar_bp.route('/etiqueta/<path:codigo>.svg')
@exige('ver')
def etiqueta_svg(codigo):
    """O código de barras de um item, sozinho (para colar em outro lugar)."""
    from app.etiqueta import codigo_do_item, svg
    it = db.session.get(Item, codigo) or abort(404)
    s = svg(codigo_do_item(it), altura=48, modulo=2)
    if not s:
        abort(404)
    return s, 200, {'Content-Type': 'image/svg+xml; charset=utf-8'}
