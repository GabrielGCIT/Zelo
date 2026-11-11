import re
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from app import db
from app.auth import exige, registrar_log
from app.models import (CATEGORIAS, FABRICANTES, FINALIDADES, PROPRIEDADES, SITES, SITUACOES, TIPOS_PESSOA, Contrato,
                        EmprestimoAcessorio, Item, Linha, Manutencao, Movimentacao, Pessoa)
from app.regras import TIPOS, recalcular_item

consulta_bp = Blueprint('consulta', __name__)
POR_PAGINA = 50

CAMPOS_ITEM = [('categoria', 'Categoria'), ('fabricante', 'Fabricante'), ('modelo', 'Modelo'), ('plaqueta', 'Plaqueta'),
               ('tag', 'Service tag'), ('hostname', 'Hostname'), ('imei1', 'IMEI 1'), ('imei2', 'IMEI 2'), ('eid', 'EID'),
               ('propriedade', 'Propriedade'), ('fornecedor', 'Fornecedor / locadora'), ('finalidade', 'Finalidade'),
               ('compativel', 'Compatível com'), ('area', 'Área / departamento'), ('cc', 'Centro de custo'),
               ('site', 'Site'), ('ativo_jde', 'Ativo JDE'), ('nf', 'NF de compra'), ('data_nf', 'Data NF'),
               ('valor', 'Valor (R$)'), ('capex', 'CAPEX/OPEX'), ('garantia', 'Fim da garantia'),
               ('pedido', 'Pedido de compra'), ('fonte', 'Fonte (série)'), ('teclado', 'Teclado/mouse (série)'),
               ('contrato', 'Contrato'), ('origem', 'Origem do cadastro'), ('obs', 'Observação')]
CAMPOS_PESSOA = [('nome', 'Nome'), ('tipo', 'Tipo'), ('empresa', 'Empresa'), ('cpf', 'CPF'), ('jde', 'Cadastro JDE'),
                 ('cc', 'Centro de custo'), ('cargo', 'Cargo'), ('site', 'Site'), ('user', 'User'), ('email', 'E-mail'),
                 ('situacao', 'Situação'), ('obs', 'Observação')]
OPCOES = {'categoria': CATEGORIAS, 'fabricante': FABRICANTES, 'propriedade': PROPRIEDADES, 'finalidade': FINALIDADES,
          'site': SITES, 'compativel': ['Dell', 'Lenovo', 'Universal'], 'capex': ['CAPEX', 'OPEX'],
          'tipo': TIPOS_PESSOA, 'situacao': ['Ativo', 'Desligado']}


def _pagina():
    try:
        return max(1, int(request.args.get('p', 1)))
    except ValueError:
        return 1


def achar_item(termo):
    """Plaqueta, service tag, IMEI (1 ou 2), hostname ou o próprio código."""
    t = (termo or '').strip()
    if not t:
        return None
    it = db.session.get(Item, t)
    if it:
        return it
    tu = t.upper()
    return Item.query.filter(or_(Item.plaqueta == t, Item.tag == tu, Item.tag == t, Item.imei1 == t, Item.imei2 == t,
                                 Item.hostname == tu, Item.hostname == t)).first()


@consulta_bp.route('/buscar')
@exige('ver')
def buscar():
    q = (request.args.get('q') or '').strip()
    if not q:
        return redirect(url_for('painel.inicio'))
    it = achar_item(q)
    if it:
        return redirect(url_for('consulta.item', codigo=it.codigo))
    dig = re.sub(r'\D', '', q)
    if len(dig) in (10, 11) and db.session.get(Linha, dig[-11:]):
        return redirect(url_for('linhas.ficha', numero=dig[-11:]))
    p = db.session.get(Pessoa, q) or db.session.get(Pessoa, q.upper())
    if p:
        return redirect(url_for('consulta.pessoa', pid=p.id))
    like = f'%{q}%'
    itens = Item.query.filter(or_(Item.codigo.ilike(like), Item.tag.ilike(like), Item.modelo.ilike(like),
                                  Item.com_quem.ilike(like), Item.hostname.ilike(like))).limit(50).all()
    pessoas = Pessoa.query.filter(or_(Pessoa.nome.ilike(like), Pessoa.id.ilike(like), Pessoa.email.ilike(like))).limit(30).all()
    linhas = Linha.query.filter(or_(Linha.numero.ilike(f'%{dig}%') if dig else False, Linha.com_quem.ilike(like))).limit(30).all()
    return render_template('buscar.html', q=q, itens=itens, pessoas=pessoas, linhas=linhas)


@consulta_bp.route('/itens')
@exige('ver')
def itens():
    f = {k: request.args.get(k, '') for k in ('q', 'categoria', 'situacao', 'site', 'finalidade', 'propriedade')}
    qy = Item.query
    if f['q']:
        like = f"%{f['q']}%"
        qy = qy.filter(or_(Item.codigo.ilike(like), Item.tag.ilike(like), Item.modelo.ilike(like), Item.plaqueta.ilike(like),
                           Item.com_quem.ilike(like), Item.imei1.ilike(like), Item.hostname.ilike(like)))
    for k in ('categoria', 'situacao', 'finalidade', 'propriedade'):
        if f[k]:
            qy = qy.filter(getattr(Item, k) == f[k])
    if 'site' in request.args:
        qy = qy.filter(Item.site == f['site']) if f['site'] else qy.filter(or_(Item.site.is_(None), Item.site == ''))
    pag = qy.order_by(Item.categoria, Item.codigo).paginate(page=_pagina(), per_page=POR_PAGINA, error_out=False)
    return render_template('itens.html', pag=pag, f=f, categorias=CATEGORIAS, situacoes=SITUACOES, sites=SITES,
                           finalidades=FINALIDADES, propriedades=PROPRIEDADES)


@consulta_bp.route('/item/<path:codigo>', methods=['GET', 'POST'])
@exige('ver')
def item(codigo):
    it = db.session.get(Item, codigo) or abort(404)
    if request.method == 'POST':
        from app.auth import pode
        if not pode('lancar'):
            abort(403)
        mudou = []
        for k, _r in CAMPOS_ITEM:
            if k not in request.form:
                continue
            v = request.form.get(k, '').strip() or None
            if k == 'valor' and v:
                try:
                    v = float(v.replace('.', '').replace(',', '.')) if ',' in v else float(v)
                except ValueError:
                    flash('Valor inválido.', 'danger')
                    return redirect(url_for('consulta.item', codigo=codigo))
            if getattr(it, k) != v:
                mudou.append(f'{k}: {getattr(it, k)!r} → {v!r}')
                setattr(it, k, v)
        if mudou:
            recalcular_item(it)
            db.session.commit()
            registrar_log('cadastro item', f'{codigo}: ' + '; '.join(mudou))
            flash('Cadastro atualizado.', 'success')
        return redirect(url_for('consulta.item', codigo=codigo))
    movs = Movimentacao.query.filter_by(item=codigo).order_by(Movimentacao.id.desc()).all()
    linha = Linha.query.filter_by(aparelho=codigo, situacao='Em uso').first()
    manut = Manutencao.query.filter_by(item=codigo).order_by(Manutencao.id.desc()).all()
    contrato = None
    if it.propriedade == 'Locado':
        contrato = (Contrato.query.filter_by(contrato=it.contrato).first() if it.contrato else
                    Contrato.query.filter_by(locadora=it.fornecedor, padrao='Sim').first())
    from app.lancamento import acoes_possiveis, card_do_item
    card = card_do_item(it)
    acoes, recado = acoes_possiveis(it, None, card)
    acoes_est = acoes_possiveis(it, None, 'estoque')[0]
    return render_template('item.html', card=card, acoes=acoes, acoes_est=acoes_est, recado=recado, it=it, movs=movs, linha=linha, manut=manut, campos=CAMPOS_ITEM,
                           opcoes=OPCOES, contrato=contrato)


@consulta_bp.route('/pessoas')
@exige('ver')
def pessoas():
    f = {k: request.args.get(k, '') for k in ('q', 'tipo', 'situacao', 'site')}
    qy = Pessoa.query
    if f['q']:
        like = f"%{f['q']}%"
        qy = qy.filter(or_(Pessoa.nome.ilike(like), Pessoa.id.ilike(like), Pessoa.email.ilike(like), Pessoa.cpf.ilike(like)))
    for k in ('tipo', 'situacao', 'site'):
        if f[k]:
            qy = qy.filter(getattr(Pessoa, k) == f[k])
    pag = qy.order_by(Pessoa.nome).paginate(page=_pagina(), per_page=POR_PAGINA, error_out=False)
    ids = [p.id for p in pag.items]
    from sqlalchemy import func
    n_itens = dict(db.session.query(Item.matricula, func.count()).filter(Item.matricula.in_(ids)).group_by(Item.matricula))
    n_linhas = dict(db.session.query(Linha.matricula, func.count()).filter(Linha.matricula.in_(ids)).group_by(Linha.matricula))
    return render_template('pessoas.html', pag=pag, f=f, tipos=TIPOS_PESSOA, sites=SITES, n_itens=n_itens, n_linhas=n_linhas)


@consulta_bp.route('/pessoa/<path:pid>', methods=['GET', 'POST'])
@exige('ver')
def pessoa(pid):
    p = db.session.get(Pessoa, pid) or abort(404)
    if request.method == 'POST':
        from app.auth import pode
        if not pode('lancar'):
            abort(403)
        mudou = []
        for k, _r in CAMPOS_PESSOA:
            if k in request.form:
                v = request.form.get(k, '').strip() or None
                if k == 'nome' and not v:
                    continue
                if getattr(p, k) != v:
                    mudou.append(f'{k}: {getattr(p, k)!r} → {v!r}')
                    setattr(p, k, v)
        if mudou:
            db.session.commit()
            registrar_log('cadastro pessoa', f'{pid}: ' + '; '.join(mudou))
            flash('Cadastro atualizado.', 'success')
        return redirect(url_for('consulta.pessoa', pid=pid))
    itens = Item.query.filter_by(matricula=pid).order_by(Item.categoria).all()
    linhas = Linha.query.filter_by(matricula=pid, situacao='Em uso').all()
    acess = EmprestimoAcessorio.query.filter_by(matricula=pid).order_by(EmprestimoAcessorio.id.desc()).all()
    movs = Movimentacao.query.filter_by(matricula=pid).order_by(Movimentacao.id.desc()).limit(300).all()
    kit = kit_da_pessoa(pid)
    return render_template('pessoa.html', p=p, itens=itens, linhas=linhas, acess=acess, movs=movs, kit=kit,
                           campos=CAMPOS_PESSOA, opcoes=OPCOES)


def kit_da_pessoa(pid):
    """Mouse/teclado/fonte que saíram do EC em entregas para a pessoa e ainda não voltaram: [(mov, consumível, qtd)]."""
    from app.models import MovConsumivel
    ids = [i for (i,) in db.session.query(Movimentacao.id).filter(Movimentacao.matricula == pid,
                                                                 Movimentacao.tipo.in_(('Entrega', 'Empréstimo')))]
    if not ids:
        return []
    saldo = {}
    for mc in MovConsumivel.query.filter(MovConsumivel.mov_id.in_(ids)):
        k = (mc.mov_id, mc.consumivel)
        saldo[k] = saldo.get(k, 0) + ((mc.qtd or 0) if mc.movimento == 'Saída' else -(mc.qtd or 0))
    return [(m, c, q) for (m, c), q in sorted(saldo.items(), reverse=True) if q > 0]


@consulta_bp.route('/pessoa/<path:pid>/kit', methods=['POST'])
@exige('lancar')
def devolver_kit(pid):
    """A pessoa devolveu só o mouse ou o teclado (não usa): volta ao saldo do EC, sem mexer no notebook."""
    from datetime import date as _d
    from flask import g
    from app.models import MovConsumivel
    p = db.session.get(Pessoa, pid) or abort(404)
    mov_id, cons = request.form.get('mov_id', ''), request.form.get('consumivel', '')
    alvo = [x for x in kit_da_pessoa(pid) if str(x[0]) == mov_id and x[1] == cons]
    if not alvo:
        flash('Esse acessório não consta mais com a pessoa.', 'danger')
    else:
        db.session.add(MovConsumivel(data=_d.today().isoformat(), consumivel=cons, site='EC', movimento='Entrada', qtd=1,
                                     destino=p.nome, resp=g.usuario.nome, mov_id=int(mov_id),
                                     obs=f'Devolução avulsa do kit por {p.nome} (entrega Nº {mov_id})'))
        db.session.commit()
        registrar_log('kit devolvido', f'{p.id} {p.nome}: {cons} (Nº {mov_id})')
        flash(f'{cons} voltou ao estoque do EC.', 'success')
    return redirect(url_for('consulta.pessoa', pid=pid))


@consulta_bp.route('/historico')
@exige('ver')
def historico():
    f = {k: request.args.get(k, '') for k in ('q', 'tipo', 'de', 'ate', 'resp')}
    qy = Movimentacao.query
    if f['q']:
        like = f"%{f['q']}%"
        qy = qy.filter(or_(Movimentacao.item.ilike(like), Movimentacao.linha.ilike(like), Movimentacao.nome.ilike(like),
                           Movimentacao.matricula.ilike(like), Movimentacao.chamado.ilike(like), Movimentacao.obs.ilike(like)))
    if f['tipo']:
        qy = qy.filter(Movimentacao.tipo == f['tipo'])
    if f['de']:
        qy = qy.filter(Movimentacao.data >= f['de'])
    if f['ate']:
        qy = qy.filter(Movimentacao.data <= f['ate'])
    if f['resp']:
        qy = qy.filter(Movimentacao.resp == f['resp'])
    pag = qy.order_by(Movimentacao.id.desc()).paginate(page=_pagina(), per_page=100, error_out=False)
    return render_template('historico.html', pag=pag, f=f, tipos=TIPOS)


@consulta_bp.route('/emprestimos')
@exige('ver')
def emprestimos():
    pool = (Item.query.filter(Item.finalidade == 'Pool de empréstimo', Item.situacao != 'Baixada')
            .order_by(Item.situacao.desc(), Item.prazo).all())
    fora = Item.query.filter(Item.situacao == 'Emprestado', Item.finalidade != 'Pool de empréstimo').all()
    acess = (EmprestimoAcessorio.query.filter(EmprestimoAcessorio.devolvido.is_(None))
             .order_by(EmprestimoAcessorio.prazo).all())
    cobertas = [m for m in Manutencao.query.filter(Manutencao.substituto.isnot(None)).all() if m.aberta]
    return render_template('emprestimos.html', pool=pool, fora=fora, acess=acess, cobertas=cobertas,
                           hoje=date.today().isoformat())


@consulta_bp.route('/contratos')
@exige('ver')
def contratos():
    hoje = date.today()
    em90 = (hoje + timedelta(days=90)).isoformat()
    cts = Contrato.query.order_by(Contrato.fim).all()
    from sqlalchemy import func
    locados = dict(db.session.query(Item.fornecedor, func.count()).filter(Item.propriedade == 'Locado',
                   Item.situacao != 'Baixada').group_by(Item.fornecedor))
    garantias = (Item.query.filter(Item.garantia.isnot(None), Item.garantia <= em90, Item.garantia >= hoje.isoformat(),
                                   Item.situacao != 'Baixada').order_by(Item.garantia).all())
    return render_template('contratos.html', cts=cts, locados=locados, garantias=garantias, hoje=hoje.isoformat())

@consulta_bp.route('/itens/novo', methods=['GET', 'POST'])
@exige('lancar')
def item_novo():
    """Cadastro de ATIVO (notebook, celular, monitor...): cria o item e lança a Entrada no estoque."""
    from flask import g
    from app.estoque import CAMPOS_ITEM, cadastrar_item
    from app.models import Compra
    d = {k: (request.form.get(k) or '').strip() for k, _r in CAMPOS_ITEM}
    if request.method == 'POST':
        ok, msg = cadastrar_item(d, g.usuario.nome)
        if ok:
            registrar_log('item cadastrado', msg)
            flash(msg, 'success')
            return redirect(url_for('consulta.item', codigo=d['codigo'].strip()))
        flash(msg, 'danger')
    return render_template('item_novo.html', d=d, campos=CAMPOS_ITEM, opcoes={
        'categoria': CATEGORIAS, 'fabricante': FABRICANTES, 'propriedade': PROPRIEDADES, 'finalidade': FINALIDADES,
        'site': SITES, 'compativel': ['Dell', 'Lenovo', 'Ambos'],
        'pedido': [c.compra for c in Compra.query.filter(Compra.status != 'Cancelado').order_by(Compra.id.desc())]})


