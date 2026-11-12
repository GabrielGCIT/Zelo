"""Busca rápida (Ctrl+K): acha e também faz.

A barra de cima sempre levou a uma página de resultados. Isso resolve "quero ver", mas o balcão
quase nunca quer só ver — quer devolver, entregar, abrir o termo. Aqui cada resultado já vem com
as ações que cabem na situação daquele item, então dá para bipar a plaqueta e devolver sem
passar por tela nenhuma. Também aceita Nº de lançamento e o nome das telas.
"""
import re

from flask import Blueprint, jsonify, request, url_for
from sqlalchemy import or_

from app import db
from app.auth import exige, pode
from app.models import Item, Linha, Movimentacao, Pessoa

busca_bp = Blueprint('busca', __name__)
LIMITE = 6

# telas e ações fixas: (rótulo, ícone, endpoint, permissão, palavras que também encontram)
TELAS = [
    ('Painel', 'fa-gauge', 'painel.inicio', 'ver', 'inicio home visao geral graficos qualidade'),
    ('Minha fila', 'fa-list-check', 'painel.fila', 'ver', 'pendencias minhas tarefas'),
    ('Bipar', 'fa-barcode', 'bipar.inicio', 'lancar', 'codigo de barras leitor devolver em lote prateleira inventario'),
    ('Novo lançamento', 'fa-pen-to-square', 'lancar.grade', 'lancar', 'lancar entregar devolver emprestar reservar'),
    ('Lançamento em lote', 'fa-table-cells', 'lancar.lote', 'lancar', 'grade varios rollout'),
    ('Acompanhar', 'fa-route', 'acompanhar.inicio', 'lancar', 'entregas preparacao reserva termo quadro'),
    ('Assinaturas', 'fa-pen-nib', 'assinar.lista', 'ver',
     'assinar assinatura digital termo caneta dedo link aceite eletronica assinador'),
    ('Manutenção', 'fa-screwdriver-wrench', 'manutencao.inicio', 'lancar', 'os ocorrencia defeito conserto'),
    ('Consumíveis', 'fa-boxes-stacked', 'estoque.consumiveis', 'lancar', 'mouse teclado fonte saldo estoque'),
    ('Cadastrar ativo', 'fa-laptop-medical', 'consulta.item_novo', 'lancar', 'novo item notebook celular monitor cadastro'),
    ('Cadastrar pessoa', 'fa-user-plus', 'lancar.pessoa', 'lancar', 'nova pessoa colaborador terceiro desligar'),
    ('Ajustar cadastro', 'fa-wrench', 'lancar.ajuste', 'lancar', 'corrigir errado planilha quem esta com'),
    ('Desligamentos', 'fa-door-open', 'desligar.lista', 'lancar', 'desligado devolucao saida demissao'),
    ('Itens', 'fa-laptop', 'consulta.itens', 'ver', 'equipamentos parque ativos lista'),
    ('Pessoas', 'fa-users', 'consulta.pessoas', 'ver', 'colaboradores usuarios'),
    ('Linhas', 'fa-sim-card', 'linhas.lista', 'ver', 'chip telefone celular numero claro'),
    ('Histórico', 'fa-clock-rotate-left', 'consulta.historico', 'ver', 'lancamentos movimentacoes auditoria'),
    ('Empréstimos', 'fa-hand-holding', 'consulta.emprestimos', 'ver', 'pool backup prazo'),
    ('Contratos e garantias', 'fa-file-contract', 'consulta.contratos', 'ver', 'locacao locadora vencimento'),
    ('Termo', 'fa-file-signature', 'termo.inicio', 'ver', 'responsabilidade assinatura pdf'),
    ('Conferir linhas', 'fa-scale-balanced', 'linhas.analise', 'lancar', 'easy airwatch analise bloquear'),
    ('Usuários do Zelo', 'fa-user-shield', 'admin.usuarios', 'admin', 'acesso perfil senha'),
    ('Configurações', 'fa-sliders', 'admin.config', 'admin', 'tecnicos prazo minimo'),
    ('Service Desk', 'fa-headset', 'admin.servicedesk', 'admin', 'manageengine api chamado integracao fila'),
    ('Auditoria', 'fa-shoe-prints', 'admin.auditoria', 'admin', 'log quem fez'),
]
_SEM_ACENTO = str.maketrans('áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                            'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC')


def _chave(s):
    return (s or '').translate(_SEM_ACENTO).lower()


def _acoes_item(it):
    from app.lancamento import acoes_possiveis, card_do_item
    if not pode('lancar'):
        return []
    card = card_do_item(it)
    acoes, _recado = acoes_possiveis(it, None, card)
    saida = [{'rotulo': a, 'url': url_for('lancar.grade', card=card, item=it.codigo, acao=a)} for a in acoes[:4]]
    saida.append({'rotulo': 'Ajustar cadastro', 'url': url_for('lancar.ajuste', item=it.codigo)})
    return saida


def _item(it, acoes=True):
    sub = f'{it.situacao or "sem movimentação"}'
    if it.com_quem:
        sub += f' com {it.com_quem}'
    if it.site:
        sub += f' · {it.site}'
    return {'titulo': f'{it.categoria or "Item"} {it.modelo or ""}'.strip(), 'cod': it.codigo, 'sub': sub,
            'url': url_for('consulta.item', codigo=it.codigo), 'acoes': _acoes_item(it) if acoes else []}


def _pessoa(p):
    n_it = Item.query.filter_by(matricula=p.id).count()
    n_ln = Linha.query.filter_by(matricula=p.id, situacao='Em uso').count()
    partes = [p.tipo or '', p.cc or 'sem CC', p.site or '']
    sub = ' · '.join([x for x in partes if x])
    sub += f' · {n_it} item(ns)' + (f', {n_ln} linha(s)' if n_ln else '')
    if p.situacao == 'Desligado':
        sub = 'DESLIGADO · ' + sub
    acoes = []
    if pode('lancar'):
        acoes.append({'rotulo': 'Entregar algo', 'url': url_for('lancar.grade', para=f'{p.nome} · {p.id}')})
        if p.situacao == 'Desligado' and (n_it or n_ln):
            acoes.append({'rotulo': 'Devolver tudo', 'url': url_for('desligar.ficha', pid=p.id)})
    return {'titulo': p.nome, 'cod': p.id, 'sub': sub, 'url': url_for('consulta.pessoa', pid=p.id), 'acoes': acoes}


def _linha(ln):
    sub = f'{ln.operadora or ""} · {ln.situacao or ""}'.strip(' ·')
    if ln.com_quem:
        sub += f' com {ln.com_quem}'
    if ln.aparelho:
        sub += f' · aparelho {ln.aparelho}'
    acoes = [{'rotulo': 'Ajustar cadastro', 'url': url_for('lancar.ajuste', linha=ln.numero)}] if pode('lancar') else []
    return {'titulo': f'Linha {ln.numero}', 'cod': ln.numero, 'sub': sub,
            'url': url_for('linhas.ficha', numero=ln.numero), 'acoes': acoes}


def _mov(m):
    quem = m.nome or m.item or m.linha or ''
    return {'titulo': f'Nº {m.id} · {m.tipo}', 'cod': m.data or '', 'sub': f'{m.item or m.linha or ""} {quem}'.strip(),
            'url': url_for('lancar.lancamento', num=m.id), 'acoes': []}


@busca_bp.route('/api/busca')
@exige('ver')
def api():
    q = (request.args.get('q') or '').strip()
    grupos = []
    if not q:
        return jsonify({'grupos': [_grupo_telas('')], 'q': q})
    from app.routes.consulta import achar_item
    like, dig, k = f'%{q}%', re.sub(r'\D', '', q), _chave(q)

    exato = achar_item(q)
    itens = []
    if exato:
        itens.append(exato)
    for it in Item.query.filter(or_(Item.codigo.ilike(like), Item.plaqueta.ilike(like), Item.tag.ilike(like),
                                    Item.hostname.ilike(like), Item.modelo.ilike(like), Item.imei1.ilike(like),
                                    Item.com_quem.ilike(like))).order_by(Item.codigo).limit(LIMITE + 1).all():
        if not exato or it.codigo != exato.codigo:
            itens.append(it)
    if itens:
        grupos.append({'titulo': 'Itens', 'icone': 'fa-laptop', 'linhas': [_item(i) for i in itens[:LIMITE]]})

    ps = Pessoa.query.filter(or_(Pessoa.nome.ilike(like), Pessoa.id.ilike(like), Pessoa.email.ilike(like),
                                 Pessoa.cpf.ilike(like) if dig else False, Pessoa.jde.ilike(like))) \
        .order_by(Pessoa.situacao.desc(), Pessoa.nome).limit(LIMITE).all()
    if ps:
        grupos.append({'titulo': 'Pessoas', 'icone': 'fa-users', 'linhas': [_pessoa(p) for p in ps]})

    lns = []
    if dig:
        lns = Linha.query.filter(Linha.numero.ilike(f'%{dig}%')).order_by(Linha.numero).limit(LIMITE).all()
    if not lns:
        lns = Linha.query.filter(Linha.com_quem.ilike(like)).limit(LIMITE).all()
    if lns:
        grupos.append({'titulo': 'Linhas', 'icone': 'fa-sim-card', 'linhas': [_linha(x) for x in lns]})

    # Nº de lançamento: com o prefixo "Nº" é sempre isso; sem prefixo, só quando o número não é
    # plaqueta de ninguém — senão toda busca por plaqueta numérica traria um lançamento à toa.
    num = re.fullmatch(r'(n[ºo°]?\s*)?(\d{1,7})', k.strip())
    if num and (num.group(1) or not itens):
        m = db.session.get(Movimentacao, int(num.group(2)))
        if m:
            grupos.append({'titulo': 'Lançamento', 'icone': 'fa-receipt', 'linhas': [_mov(m)]})

    g = _grupo_telas(k)
    if g['linhas']:
        grupos.append(g)
    return jsonify({'grupos': grupos, 'q': q})


def _grupo_telas(k):
    # por palavra, não pela frase inteira: "assinar termo" tem que achar a tela de Assinaturas
    # mesmo que essas duas palavras não estejam grudadas na lista de sinônimos
    palavras = [p for p in k.split() if p]
    linhas = []
    for rotulo, ico, endpoint, perm, extras in TELAS:
        if perm and not pode(perm):
            continue
        texto = _chave(rotulo) + ' ' + extras
        if palavras and not all(p in texto for p in palavras):
            continue
        try:
            u = url_for(endpoint)
        except Exception:
            continue
        linhas.append({'titulo': rotulo, 'cod': '', 'sub': '', 'url': u, 'icone': ico, 'acoes': []})
        if not palavras and len(linhas) >= 8:
            break
    return {'titulo': 'Ir para', 'icone': 'fa-arrow-right', 'linhas': linhas[:8 if not palavras else LIMITE]}
