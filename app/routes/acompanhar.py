from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from app import db
from app.acompanhar import PASSOS, corrigir, marcas_de, preparar, ultima_preparacao
from app.auth import exige, registrar_log
from app.models import ESTADOS_DEV, Item, Movimentacao, cfg, cfg_lista

acompanhar_bp = Blueprint('acompanhar', __name__)


COLUNAS_ENTREGA = ['Reservado', 'Entregue']      # o que acontece com a máquina; termo e chamado são marcas no cartão


def _cartao_entrega(m, it):
    from app.pendencias import texto
    return dict(m=m, it=it, pend=texto(m, it), col='Entregue' if m.etapa == 'Entregue' else 'Reservado')


@acompanhar_bp.route('/acompanhar')
@exige('ver')
def inicio():
    from datetime import date, timedelta
    fluxo = cfg('fluxo_preparacao') or '2026-11-05'
    semana = (date.today() - timedelta(days=7)).isoformat()
    # 1 · quadro das entregas: reservas em andamento + entregues com termo pendente + entregues na última semana
    vistos, cartoes = set(), []
    andamento = Item.query.filter(Item.situacao == 'Reservada').all()
    pend = Item.query.filter(Item.situacao.in_(('Em uso', 'Emprestado')), Item.termo == 'Pendente').all()
    for it in sorted(andamento + pend, key=lambda i: i.desde or ''):
        m = db.session.get(Movimentacao, it.ultima_mov_id) if it.ultima_mov_id else None
        if m and m.tipo in ('Entrega', 'Empréstimo') and m.id not in vistos:
            vistos.add(m.id)
            cartoes.append(_cartao_entrega(m, it))
    recentes = (Movimentacao.query.filter(Movimentacao.tipo.in_(('Entrega', 'Empréstimo')), Movimentacao.etapa == 'Entregue',
                                          Movimentacao.data_ent >= semana).order_by(Movimentacao.id.desc()).limit(40).all())
    for m in recentes:
        if m.id not in vistos:
            vistos.add(m.id)
            cartoes.append(_cartao_entrega(m, db.session.get(Item, m.item) if m.item else None))
    quadro1 = {c: [x for x in cartoes if x['col'] == c] for c in COLUNAS_ENTREGA}
    # 2 · quadro da preparação
    hoje = date.today().isoformat()
    prep_cols = {'Devolvido': [], 'Em preparação': [], 'Liberado': []}
    for it in Item.query.filter(Item.situacao.in_(('Devolvido', 'Em preparação'))).order_by(Item.desde).all():
        prep, dev = ultima_preparacao(it)
        base = prep or dev
        prep_cols[it.situacao].append(dict(
            it=it, dev=dev, marcas=marcas_de(prep), preparado=(prep.receb_por if prep else ''),
            veio_fonte=(base.fonte_dev if base else None), veio_mouse=(base.mouse_dev if base else None),
            veio_teclado=(base.teclado_dev if base else None), estado=(base.estado if base else None)))
    for m in Movimentacao.query.filter(Movimentacao.tipo == 'Liberação', Movimentacao.data >= semana).order_by(
            Movimentacao.id.desc()).limit(30):
        prep_cols['Liberado'].append(dict(it=db.session.get(Item, m.item), lib=m))
    # 3 · termos assinados sem link (desde a data do fluxo)
    s3 = (Movimentacao.query.filter(Movimentacao.tipo.in_(('Entrega', 'Empréstimo')), Movimentacao.data >= fluxo,
                                    (Movimentacao.link.is_(None)) | (Movimentacao.link == ''),
                                    Movimentacao.termo_arquivo.is_(None), Movimentacao.termo == 'Assinado',
                                    (Movimentacao.etapa.is_(None)) | (Movimentacao.etapa != 'Cancelado'))
          .order_by(Movimentacao.id.desc()).limit(200).all())
    n4 = request.args.get('n', '')
    if n4.isdigit() and db.session.get(Movimentacao, int(n4)):
        return redirect(url_for('lancar.lancamento', num=int(n4)))
    return render_template('acompanhar.html', quadro1=quadro1, colunas=COLUNAS_ENTREGA, prep_cols=prep_cols, s3=s3, n4=n4,
                           passos=PASSOS, hoje=hoje)


@acompanhar_bp.route('/api/acompanhar/etapa', methods=['POST'])
@exige('lancar')
def api_etapa():
    """Arrastar o cartão no quadro das entregas."""
    j = request.get_json(silent=True) or {}
    m = db.session.get(Movimentacao, int(j.get('id') or 0))
    if not m:
        return jsonify(ok=False, msg='Lançamento não encontrado')
    para = j.get('para')
    if para == m.etapa:
        return jsonify(ok=True, msg='')
    if para not in ('Entregue', 'Cancelado'):
        return jsonify(ok=False, msg='Não dá para voltar a Reservado: abra o lançamento para corrigir')
    ok, msg = corrigir(m, {'etapa': para}, g.usuario.nome)
    if ok:
        registrar_log('acompanhar', msg)
        from flask import current_app
        from app import servicedesk as sd
        if para == 'Entregue' and sd.configurado():
            sd.enfileirar_tudo(current_app._get_current_object(), [m])
    from app.pendencias import texto
    return jsonify(ok=ok, msg=msg, pend=texto(m) if ok and para != 'Cancelado' else [])


@acompanhar_bp.route('/api/acompanhar/marca', methods=['POST'])
@exige('lancar')
def api_marca():
    """Marcas do cartão: termo assinado (sim/não) e Nº do chamado. Tudo vai para a auditoria."""
    from app.pendencias import editar, texto
    j = request.get_json(silent=True) or {}
    m = db.session.get(Movimentacao, int(j.get('id') or 0))
    campo, valor = j.get('campo'), (j.get('valor') or '').strip()
    if not m or campo not in ('termo', 'chamado'):
        return jsonify(ok=False, msg='Lançamento não encontrado')
    if campo == 'termo' and valor not in ('Assinado', 'Pendente'):
        return jsonify(ok=False, msg='Valor inválido')
    antes = m.chamado
    mudou = editar(m, {campo: valor}, g.usuario.nome)
    if mudou:
        registrar_log('acompanhar', f'Nº {m.id}: ' + '; '.join(mudou))
        from flask import current_app
        from app import servicedesk as sd
        if campo == 'chamado' and m.chamado and not antes and sd.configurado():
            sd.enfileirar_tudo(current_app._get_current_object(), [m])
    return jsonify(ok=True, msg='; '.join(mudou), pend=texto(m), termo=m.termo, chamado=m.chamado or '')


@acompanhar_bp.route('/api/acompanhar/preparo', methods=['POST'])
@exige('lancar')
def api_preparo():
    """Cada clique no cartão da preparação salva aqui; liberar = volta ao estoque."""
    j = request.get_json(silent=True) or {}
    it = db.session.get(Item, j.get('item') or '')
    if not it:
        return jsonify(ok=False, msg='Item não encontrado')
    dados = {k: (str(j.get(k) or '')).strip() for k in ('veio_fonte', 'veio_mouse', 'veio_teclado', 'estado', 'liberar',
                                                       *[p for p, _r in PASSOS])}
    ok, msg = preparar(it, dados, g.usuario.nome)
    if ok and dados['liberar'] == 'Sim':
        registrar_log('preparação', f'{it.codigo}: {msg}')
    db.session.refresh(it)
    return jsonify(ok=ok, msg=msg, situacao=it.situacao)


@acompanhar_bp.route('/acompanhar/corrigir/<int:num>', methods=['POST'])
@exige('lancar')
def corrigir_mov(num):
    m = db.session.get(Movimentacao, num)
    if not m:
        flash(f'Nº {num} não encontrado.', 'danger')
        return redirect(url_for('acompanhar.inicio'))
    dados = {k: (request.form.get(k) or '').strip() for k in ('etapa', 'data_ass', 'chamado', 'data_ent', 'tecnico', 'link', 'termo')}
    chamado_antes = m.chamado
    ok, msg = corrigir(m, dados, g.usuario.nome)
    if ok:
        registrar_log('acompanhar', msg)
        from flask import current_app
        from app import servicedesk as sd
        if sd.configurado():
            app_ = current_app._get_current_object()
            if m.chamado and (dados['etapa'] == 'Entregue' or not chamado_antes):
                ids = sd.enfileirar([m])
                if ids:
                    sd.processar(app_, ids)
                    msg += ' · termo enviado ao chamado'
            if dados['etapa'] == 'Entregue' and sd.ativos_ligado():
                ids = sd.enfileirar_ativos([m])
                if ids:
                    sd.processar(app_, ids)
    flash(msg, 'success' if ok else 'danger')
    volta = request.form.get('volta') or url_for('acompanhar.inicio')
    return redirect(volta if volta.startswith('/') else url_for('acompanhar.inicio'))


@acompanhar_bp.route('/acompanhar/preparar/<path:codigo>', methods=['POST'])
@exige('lancar')
def preparar_item(codigo):
    it = db.session.get(Item, codigo)
    dados = {k: (request.form.get(k) or '').strip() for k in ('veio_fonte', 'veio_mouse', 'veio_teclado', 'estado',
                                                            'preparado_por', 'liberar', *[p for p, _r in PASSOS])}
    ok, msg = preparar(it, dados, g.usuario.nome) if it else (False, 'Item não encontrado')
    if ok:
        registrar_log('preparação', f'{codigo}: {msg}')
    flash(f'{codigo}: {msg}', 'success' if ok else 'danger')
    return redirect(url_for('acompanhar.inicio') + '#preparacao')
