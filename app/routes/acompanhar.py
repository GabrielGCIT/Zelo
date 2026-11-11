from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app import db
from app.acompanhar import PASSOS, corrigir, marcas_de, preparar, ultima_preparacao
from app.auth import exige, registrar_log
from app.models import ESTADOS_DEV, Item, Movimentacao, cfg, cfg_lista

acompanhar_bp = Blueprint('acompanhar', __name__)


@acompanhar_bp.route('/acompanhar')
@exige('ver')
def inicio():
    fluxo = cfg('fluxo_preparacao') or '2026-11-05'
    # 1 · entregas em andamento e entregas/empréstimos com termo pendente
    em_and = Item.query.filter(Item.situacao == 'Reservada').all()
    pend = Item.query.filter(Item.situacao.in_(('Em uso', 'Emprestado')), Item.termo == 'Pendente').all()
    s1 = []
    for it in sorted(em_and + pend, key=lambda i: i.desde or ''):
        m = db.session.get(Movimentacao, it.ultima_mov_id) if it.ultima_mov_id else None
        if m:
            s1.append((it, m))
    # linhas sem item com termo pendente (BYOD)
    s1 += [(None, m) for m in Movimentacao.query.filter(Movimentacao.item.is_(None), Movimentacao.tipo == 'Entrega',
                                                       Movimentacao.termo == 'Pendente', Movimentacao.data >= fluxo)]
    # 2 · devolvidos e em preparação
    s2 = []
    for it in Item.query.filter(Item.situacao.in_(('Devolvido', 'Em preparação'))).order_by(Item.desde).all():
        prep, dev = ultima_preparacao(it)
        base = prep or dev
        s2.append(dict(it=it, dev=dev, prep=prep, marcas=marcas_de(prep),
                       veio_fonte=(base.fonte_dev if base else None), veio_mouse=(base.mouse_dev if base else None),
                       veio_teclado=(base.teclado_dev if base else None), estado=(base.estado if base else None)))
    # 3 · termos assinados sem link (desde a data do fluxo)
    s3 = (Movimentacao.query.filter(Movimentacao.tipo.in_(('Entrega', 'Empréstimo', 'Devolução')),
                                    Movimentacao.data >= fluxo, (Movimentacao.link.is_(None)) | (Movimentacao.link == ''),
                                    ((Movimentacao.termo == 'Assinado') | (Movimentacao.tipo == 'Devolução')))
          .order_by(Movimentacao.id.desc()).limit(200).all())
    n4 = request.args.get('n', '')
    m4 = db.session.get(Movimentacao, int(n4)) if n4.isdigit() else None
    return render_template('acompanhar.html', s1=s1, s2=s2, s3=s3, m4=m4, n4=n4, passos=PASSOS, estados=ESTADOS_DEV,
                           tecnicos=cfg_lista('tecnicos'), recebido=cfg_lista('recebido_por'))


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
