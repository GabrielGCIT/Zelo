"""Assinatura do termo: a página pública do link e o painel dentro do lançamento.

A página do link não exige login — é a mesma tela para quem assina no tablet do balcão e para
quem assina de casa. O que a protege é o token: 32 bytes aleatórios, válido por um prazo, para um
único termo e uma única via, e que deixa de valer no instante em que é usado.
"""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from app import db
from app.assinatura import (PAPEIS, ROTULO, abrir, assinar, cancelar, codigo, conferir, link, local, pedir, quem_assina,
                            vias)
from app.auth import exige, registrar_log
from app.models import Movimentacao, cfg_lista

assinar_bp = Blueprint('assinar', __name__)


def _ip():
    """Atrás do IIS/proxy o endereço real vem no cabeçalho; sem proxy, vale o da conexão."""
    enc = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return enc or request.remote_addr or ''


# ------------------------------------------------------------------ página pública do link
@assinar_bp.route('/assinar/<token>', methods=['GET', 'POST'])
def pagina(token):
    a, m, erro = abrir(token)
    if not a:
        return render_template('assinar.html', erro=erro, a=None, m=None, d=None), 404
    from app.routes.termo import montar
    d = montar(str(m.id))[0] if m else None
    if request.method == 'POST' and not erro and not a.assinado:
        ok, msg, fechou = assinar(a, m, request.form.get('desenho'), request.form.get('nome'),
                                  _ip(), request.headers.get('User-Agent', ''))
        if ok:
            registrar_log('termo assinado', f'Nº {m.id} · {ROTULO[a.papel]}: {a.assinante} (IP {a.ip})')
        if request.headers.get('X-Requested-With') == 'fetch':
            return jsonify(ok=ok, msg=msg, fechou=fechou)
        flash(msg, 'success' if ok else 'danger')
        return redirect(url_for('assinar.pagina', token=token))
    return render_template('assinar.html', a=a, m=m, d=d, erro=erro, codigo=codigo(a) if a.assinado else '',
                           outras=vias(m) if m else {})


@assinar_bp.route('/assinar/<token>/termo.pdf')
def pdf_do_link(token):
    """O termo que a pessoa está prestes a assinar, para ler antes (ou guardar depois de assinado)."""
    from flask import Response
    from app.assinatura import vias as _vias
    from app.routes.termo import montar
    from app.termo_pdf import gerar_pdf
    a, m, erro = abrir(token)
    if not a or not m or (erro and not a.assinado):
        abort(404)
    d = montar(str(m.id))[0] or abort(404)
    assinadas = [x for x in _vias(m).values() if x and x.assinado] if a.assinado else None
    return Response(gerar_pdf(d, assinaturas=assinadas), mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="Termo_{m.id}.pdf"'})


@assinar_bp.route('/assinatura/<int:aid>.png')
@exige('ver')
def traco(aid):
    """O desenho de uma via, para a tela do Zelo (quem vê precisa estar logado)."""
    from flask import Response
    from app.models import Assinatura
    a = db.session.get(Assinatura, aid) or abort(404)
    if not a.traco:
        abort(404)
    return Response(a.traco, mimetype='image/png', headers={'Cache-Control': 'private, max-age=600'})


# ------------------------------------------------------------------ porta de entrada
@assinar_bp.route('/assinaturas')
@exige('ver')
def lista():
    """Atalho antigo: a lista passou a morar na tela Termo — duas telas para a mesma coisa só confundia."""
    num = (request.args.get('n') or '').strip()
    if num.isdigit() and db.session.get(Movimentacao, int(num)):
        return redirect(url_for('assinar.painel', num=int(num)))
    return redirect(url_for('termo.inicio', n=num or None))


# ------------------------------------------------------------------ painel dentro do lançamento
@assinar_bp.route('/lancamento/<int:num>/assinaturas', methods=['GET', 'POST'])
@exige('ver')
def painel(num):
    from app.auth import pode
    m = db.session.get(Movimentacao, num) or abort(404)
    if request.method == 'POST':
        if not pode('lancar'):
            abort(403)
        acao, papel = request.form.get('acao'), request.form.get('papel')
        if acao == 'pedir':
            a, msg = pedir(m, papel, request.form.get('nome'), g.usuario.nome, request.form.get('contato'))
            if a:
                registrar_log('assinatura pedida', f'Nº {num} · {ROTULO.get(papel, papel)}: {a.nome}')
            flash(msg, 'success' if a else 'danger')
        elif acao == 'cancelar':
            a = vias(m).get(papel)
            if a and not a.assinado:
                cancelar(a, request.form.get('motivo') or 'Cancelado', g.usuario.nome)
                registrar_log('assinatura cancelada', f'Nº {num} · {ROTULO.get(papel, papel)}')
                flash('Pedido de assinatura cancelado.', 'success')
            else:
                flash('Não há pedido em aberto nessa via.', 'danger')
        return redirect(url_for('assinar.painel', num=num))
    from app.assinatura import TEM_TERMO
    v = vias(m)
    links = {p: (link(a) if a and not a.assinado else '') for p, a in v.items()}
    return render_template('assinaturas.html', m=m, vias=v, papeis=PAPEIS, rotulo=ROTULO,
                           tem_termo=m.tipo in TEM_TERMO, tipos_com_termo=TEM_TERMO,
                           sugerido={p: quem_assina(m, p) for p in PAPEIS},
                           assinantes=cfg_lista('assinantes_empresa'), avisos=conferir(m), links=links,
                           so_local=any(local(u) for u in links.values() if u),
                           estado=_estado_do_termo(m, v),
                           codigos={p: (codigo(a) if a and a.assinado else '') for p, a in v.items()})


def _estado_do_termo(m, v):
    """O que dizer na etiqueta do alto: assinado na tela, guardado, no papel, ou ainda pendente."""
    if any(a and a.assinado for a in v.values()):
        return ('success', 'assinado nesta tela') if all(a and a.assinado for a in v.values()) else \
               ('warning', 'uma via assinada')
    if m.termo_arquivo:
        return 'success', 'termo guardado'
    if m.termo == 'Assinado':
        return 'secondary', 'marcado como assinado (sem via no Zelo)'
    if m.termo == 'Dispensado':
        return 'secondary', 'termo dispensado'
    return 'warning', 'termo pendente'
