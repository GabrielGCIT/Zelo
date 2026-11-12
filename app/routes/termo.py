"""Termo pronto para imprimir: digite o Nº do lançamento (ou EA- do acessório); o tipo sai sozinho."""
import re
from datetime import date

from flask import Blueprint, render_template, request

from app import db
from app.auth import exige
from app.models import EmprestimoAcessorio, Item, Linha, Movimentacao, Pessoa
from app.termo_textos import TEXTOS

termo_bp = Blueprint('termo', __name__)
TIPOS_TERMO = {t[0]: t for t in TEXTOS}
DIAS = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
         'novembro', 'dezembro']


def _br(d):
    return f'{d[8:10]}/{d[5:7]}/{d[0:4]}' if d and len(d) >= 10 else ''


def tipo_automatico(m, it, emprestimo_ant):
    if m.tipo not in ('Entrega', 'Empréstimo', 'Devolução', 'Ativar linha'):
        return 'Sem termo'
    tel = it is not None and it.categoria in ('Celular', 'Tablet')
    if m.tipo == 'Devolução':
        if emprestimo_ant:
            return 'Devolução de empréstimo'
        return 'Devolução telefonia' if (tel or not m.item) else 'Devolução'
    if not m.item and m.linha:
        p = db.session.get(Pessoa, m.matricula) if m.matricula else None
        return 'BYOD' if p and p.tipo == 'CLT' else 'Sem termo'
    if tel:
        return 'Telefonia'
    if m.tipo == 'Empréstimo':
        return 'Renovação de empréstimo' if (m.obs or '').startswith('Renovação do empréstimo') else 'Empréstimo'
    return 'Entrega'


def descrever_item(it):
    if not it:
        return ''
    if it.categoria in ('Celular', 'Tablet'):
        return (f'*01 {it.categoria.lower()} modelo {it.modelo or ""}, identificado pelo IMEI nº {it.imei1 or it.codigo}'
                + (f' (S/N {it.tag})' if it.tag else ''))
    s = (it.modelo or '') + (f' - {it.hostname}' if it.hostname else '') + f' – Service TAG: {it.tag or ""}'
    s += f' – Plaqueta: {it.plaqueta}' if it.plaqueta else ''
    s += f' com fonte {it.fonte}' if it.fonte else ''
    s += f' - NF {it.nf}' if it.nf else ''
    s += f' - ATIVO: {it.ativo_jde}' if it.ativo_jde else ''
    return s


def montar(num, trocar=None):
    """Dados do termo para o Nº (ou EA-0001). Devolve (dados, erro)."""
    t = (num or '').strip().upper()
    if not t:
        return None, None
    d = {'num': t}
    if t.startswith('EA'):
        ea = db.session.get(EmprestimoAcessorio, int(re.sub(r'\D', '', t) or 0))
        if not ea:
            return None, 'Empréstimo de acessório não encontrado'
        d.update(tipo='Devolução de acessório' if ea.devolvido else 'Empréstimo de acessório', nome=ea.nome,
                 matricula=ea.matricula, equipamento=f'*{ea.qtd:02d} {ea.consumivel}', linha='', acessorios='',
                 periodo=f'{_br(ea.data)} a {_br(ea.prazo)}', chamado=ea.chamado or '',
                 obs=(ea.obs_dev if ea.devolvido else ea.obs) or '', ref=f'Chamado: {ea.chamado}' if ea.chamado else '')
    else:
        if not t.isdigit():
            return None, 'Digite o Nº do lançamento (coluna Nº do Histórico) ou EA-0001'
        m = db.session.get(Movimentacao, int(t))
        if not m:
            return None, f'Lançamento Nº {t} não encontrado'
        it = db.session.get(Item, m.item) if m.item else None
        ant = None
        if m.tipo == 'Empréstimo':
            ant = m
        elif m.tipo == 'Devolução' and m.item:
            ult = (Movimentacao.query.filter(Movimentacao.item == m.item, Movimentacao.id < m.id,
                                             Movimentacao.tipo.in_(('Entrega', 'Empréstimo', 'Devolução')))
                   .order_by(Movimentacao.id.desc()).first())
            ant = ult if ult and ult.tipo == 'Empréstimo' else None
        tipo = tipo_automatico(m, it, ant if m.tipo == 'Devolução' else None)
        ln = db.session.get(Linha, m.linha) if m.linha else None
        tipo_usado = trocar or tipo
        linha = ''
        if m.linha:
            linha = (f'*01 linha de telefonia móvel corporativa da operadora {(ln.operadora if ln else None) or "Vivo"} '
                     f'nº {m.linha}' + (' (eSIM), para uso no aparelho do colaborador' if tipo_usado == 'BYOD'
                                        else ', com pacote de voz e dados habilitados'))
        cat = it.categoria if it else None
        if tipo_usado == 'Devolução telefonia':
            acess = 'Devolução somente do chip.' if not it else 'Acompanhado dos acessórios:   (   ) carregador   (   ) cabo USB   (   ) capa/película'
        elif tipo_usado in ('Devolução', 'Devolução de empréstimo'):
            acess = ('Acompanhado de:   (   ) fonte   (   ) teclado e mouse   (   ) mochila/bolsa   (   ) outros: __________'
                     if cat == 'Notebook' else 'Acompanhado de:   (   ) fonte/cabos   (   ) outros: __________') if it else ''
        elif cat == 'Notebook':
            acess = 'Conjunto Sem Fio (Wireless) Composto por Teclado Alfanumérico de 107 Teclas e Mouse (Indicador)'
        elif cat in ('Celular', 'Tablet'):
            acess = 'Acompanhado de carregador e cabo USB.'
        else:
            acess = ''
        nome, mat = m.nome or m.local or '', m.matricula
        periodo = f'{_br(ant.data)} a {_br(ant.prazo)}' if ant and ant.prazo else ''
        ref = ''
        if ant:
            ref = ' · '.join(x for x in (f'Motivo: {ant.motivo}' if ant.motivo else '',
                                         f'Chamado: {ant.chamado}' if ant.chamado else '') if x)
        d.update(tipo=tipo, nome=nome, matricula=mat, equipamento=descrever_item(it), linha=linha, acessorios=acess,
                 periodo=periodo, chamado=m.chamado or '', obs=m.obs or '', ref=ref, mov=m)
    d['tipo_auto'] = d['tipo']
    if trocar and trocar in TIPOS_TERMO:
        d['tipo'] = trocar
    mat = d.get('matricula') or ''
    d['matricula_fmt'] = mat.zfill(6) if mat.isdigit() else ''
    tp = TIPOS_TERMO[d['tipo']]
    d.update(titulo=tp[1], abertura=tp[2], p1=tp[3], p2=tp[4], fecho=tp[5], ass_empresa=tp[6])
    h = date.today()
    d['data_ext'] = f'{DIAS[h.weekday()]}, {h.day} de {MESES[h.month - 1]} de {h.year}'
    return d, None


@termo_bp.route('/termo')
@exige('ver')
def inicio():
    """Uma tela só para o termo: gerar e imprimir, e o estado das assinaturas na tela."""
    from app.assinatura import ROTULO, local
    from app.assinatura import link as link_ass
    from app.assinatura import pendentes
    from app.models import Assinatura
    num = request.args.get('n', '')
    dados, erro = montar(num, request.args.get('tipo') or None)
    abertas = pendentes(300)
    ids = {a.mov_id for a in abertas}
    feitas = (Assinatura.query.filter(Assinatura.assinado.isnot(None))
              .order_by(Assinatura.assinado.desc()).limit(15).all())
    ids |= {a.mov_id for a in feitas}
    movs = {m.id: m for m in Movimentacao.query.filter(Movimentacao.id.in_(ids)).all()} if ids else {}
    return render_template('termo.html', num=num, d=dados, erro=erro, tipos=list(TIPOS_TERMO),
                           abertas=abertas, feitas=feitas, movs=movs, rotulo=ROTULO,
                           so_local=any(local(link_ass(a)) for a in abertas[:1]))


@termo_bp.route('/termo/<num>.pdf')
@exige('ver')
def pdf(num):
    from flask import Response, abort
    from app.termo_pdf import gerar_pdf
    dados, erro = montar(num, request.args.get('tipo') or None)
    if not dados:
        abort(404)
    return Response(gerar_pdf(dados), mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="Termo_Zelo_{num}.pdf"'})


@termo_bp.route('/termo/<int:num>/assinado', methods=['GET', 'POST'])
@exige('ver')
def assinado(num):
    """GET: abre o termo assinado guardado. POST: guarda o arquivo (marca o termo como Assinado)."""
    from flask import abort, flash, g, jsonify, redirect, send_file, url_for
    from app import db
    from app.auth import pode, registrar_log
    from app.models import Movimentacao
    from app.termo_arquivo import MIME, caminho, salvar
    m = db.session.get(Movimentacao, num) or abort(404)
    if request.method == 'GET':
        c = caminho(m)
        if not c:
            abort(404)
        ext = c.rsplit('.', 1)[-1].lower()
        return send_file(c, mimetype=MIME.get(ext), download_name=f'Termo_assinado_{num}.{ext}')
    if not pode('lancar'):
        abort(403)
    ok, msg = salvar(m, request.files.get('arquivo'), g.usuario.nome)
    if ok:
        registrar_log('termo assinado guardado', f'Nº {num}: {m.termo_arquivo}')
        from flask import current_app
        from app import servicedesk as sd
        if m.chamado and sd.configurado():
            ids = sd.enfileirar_termo([m])
            if ids:
                sd.processar(current_app._get_current_object(), ids)
                from app.models import EnvioSD
                e = db.session.get(EnvioSD, ids[0])
                msg += (f' e anexado ao chamado {m.chamado}' if e and e.status == 'Enviado'
                        else '. O envio ao chamado falhou e ficou na fila (Administração → Service Desk)')
    if request.headers.get('X-Requested-With') == 'fetch':
        from app.pendencias import texto
        return jsonify(ok=ok, msg=msg, pend=texto(m) if ok else [])
    flash(msg, 'success' if ok else 'danger')
    return redirect(request.form.get('volta') or url_for('lancar.lancamento', num=num))
