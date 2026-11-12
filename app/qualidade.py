"""Qualidade do cadastro: o que está errado ou faltando, com o caminho para resolver.

Cada achado tem um porquê (o que quebra se ficar assim) e um botão que leva direto ao lugar de corrigir.
Nada aqui bloqueia nada: é o sistema apontando, não travando."""
import re
import unicodedata
from collections import defaultdict

from flask import url_for

from app import db
from app.models import Item, Linha, Movimentacao, Pessoa

LIMITE = 12          # quantos exemplos cada achado mostra


def _chave(nome):
    s = unicodedata.normalize('NFKD', str(nome or '')).encode('ascii', 'ignore').decode().upper()
    return ' '.join(re.sub(r'[^A-Z0-9 ]', ' ', s).split())      # dígitos contam: FTCTRN0001 ≠ FTCTRN0002


def _itens(n):
    return f'{n} {"itens" if n != 1 else "item"}'


def _achado(id_, titulo, porque, linhas, grave=False):
    return dict(id=id_, titulo=titulo, porque=porque, n=len(linhas), linhas=linhas[:LIMITE],
                mais=max(0, len(linhas) - LIMITE), grave=grave)


def _pessoa(p, extra=''):
    return dict(texto=f'{p.nome} · {p.id}' + (f' · {extra}' if extra else ''),
                href=url_for('consulta.pessoa', pid=p.id), botao='Abrir cadastro')


def _item(it, extra=''):
    return dict(texto=f'{it.codigo} · {it.categoria or ""} {it.modelo or ""}'.strip() + (f' · {extra}' if extra else ''),
                href=url_for('consulta.item', codigo=it.codigo), botao='Abrir cadastro')


def pessoas_duplicadas():
    por_nome = defaultdict(list)
    for p in Pessoa.query.filter(Pessoa.situacao != 'Desligado'):
        k = _chave(p.nome)
        if k:
            por_nome[k].append(p)
    linhas = []
    for k, ps in sorted(por_nome.items()):
        if len(ps) > 1:
            com = {p.id: Item.query.filter(Item.matricula == p.id,
                                           Item.situacao.in_(('Em uso', 'Emprestado', 'Reservada'))).count() for p in ps}
            linhas.append(dict(texto=ps[0].nome + ' → ' + ' · '.join(f'{p.id} ({_itens(com[p.id])})'
                                                                     for p in ps),
                               href=url_for('consulta.pessoas', q=ps[0].nome), botao='Comparar'))
    return _achado('dup', 'Pessoas com o mesmo nome', 'Entregar para a matrícula errada é o erro mais caro: o item fica '
                   'com quem não está. Confira e deixe só a matrícula certa ativa.', linhas, grave=True)


def pessoas_sem_cc():
    ps = (db.session.query(Pessoa).join(Item, Item.matricula == Pessoa.id)
          .filter(Pessoa.situacao != 'Desligado', (Pessoa.cc.is_(None)) | (Pessoa.cc == ''),
                  Item.situacao.in_(('Em uso', 'Emprestado', 'Reservada'))).distinct().order_by(Pessoa.nome).all())
    return _achado('cc', 'Pessoas com item mas sem centro de custo',
                   'O CC do lançamento vem do cadastro da pessoa. Sem ele, o termo e o rateio saem sem centro de custo.',
                   [_pessoa(p) for p in ps])


def pessoas_a_confirmar():
    ps = Pessoa.query.filter(Pessoa.situacao != 'Desligado', Pessoa.tipo == 'A confirmar').order_by(Pessoa.nome).all()
    return _achado('tipo', 'Pessoas com o tipo "A confirmar"',
                   'O tipo (CLT, terceiro, posto) decide o texto do termo e a empresa que assina.',
                   [_pessoa(p, p.empresa or 'sem empresa') for p in ps])


def itens_sem_hostname():
    its = Item.query.filter(Item.categoria.in_(('Notebook', 'Desktop')), Item.situacao != 'Baixada',
                            (Item.hostname.is_(None)) | (Item.hostname == '')).order_by(Item.codigo).all()
    return _achado('host', 'Notebooks e desktops sem hostname',
                   'O hostname é o que liga a máquina ao ativo do Service Desk. Sem ele, a entrega não atualiza o ativo lá.',
                   [_item(it) for it in its])


def itens_sem_tag():
    its = Item.query.filter(Item.categoria.in_(('Notebook', 'Desktop', 'Monitor')), Item.situacao != 'Baixada',
                            (Item.tag.is_(None)) | (Item.tag == '')).order_by(Item.codigo).all()
    return _achado('tag', 'Itens sem service tag / nº de série',
                   'A service tag é o que identifica a máquina na garantia e no chamado do fabricante.',
                   [_item(it) for it in its])


def itens_sem_movimentacao():
    its = Item.query.filter(Item.situacao == 'Sem movimentação').order_by(Item.codigo).all()
    return _achado('semmov', 'Itens que nunca tiveram lançamento',
                   'Vieram da planilha sem histórico: ninguém sabe se estão no estoque, com alguém ou sumidos. '
                   'Lance a Entrada no estoque ou a entrega que faltou.',
                   [dict(texto=f'{it.codigo} · {it.categoria or ""} {it.modelo or ""}'.strip(),
                         href=url_for('lancar.grade', item=it.codigo), botao='Lançar') for it in its])


def linhas_sem_aparelho():
    ls = Linha.query.filter(Linha.situacao == 'Em uso', (Linha.aparelho.is_(None)) | (Linha.aparelho == '')).order_by(
        Linha.numero).all()
    return _achado('linha', 'Linhas em uso sem aparelho registrado',
                   'Sem saber em que aparelho a linha está, não dá para conferir consumo nem pedir bloqueio com segurança.',
                   [dict(texto=f'{ln.numero} · {ln.com_quem or "sem pessoa"}', href=url_for('linhas.ficha', numero=ln.numero),
                         botao='Abrir linha') for ln in ls])


def lancamentos_sem_data():
    ms = Movimentacao.query.filter((Movimentacao.data.is_(None)) | (Movimentacao.data == '')).order_by(
        Movimentacao.id.desc()).all()
    return _achado('semdata', 'Lançamentos sem data',
                   'Vieram assim da planilha. Sem data, o item não entra nos prazos nem nos gráficos por período.',
                   [dict(texto=f'Nº {m.id} · {m.tipo} · {m.item or m.linha or ""} · {m.nome or ""}',
                         href=url_for('lancar.lancamento', num=m.id), botao='Pôr a data') for m in ms])


def desligados_com_item():
    r = (db.session.query(Pessoa, db.func.count(Item.codigo)).join(Item, Item.matricula == Pessoa.id)
         .filter(Pessoa.situacao == 'Desligado', Item.situacao.in_(('Em uso', 'Emprestado', 'Reservada')))
         .group_by(Pessoa.id).order_by(Pessoa.nome).all())
    return _achado('desl', 'Desligados ainda com item', 'A pessoa saiu e o equipamento continua no nome dela.',
                   [_pessoa(p, _itens(n)) for p, n in r], grave=True)


CHECKS = [pessoas_duplicadas, desligados_com_item, pessoas_sem_cc, pessoas_a_confirmar, itens_sem_hostname,
          itens_sem_tag, itens_sem_movimentacao, linhas_sem_aparelho, lancamentos_sem_data]


def tudo():
    """Todos os achados com pelo menos 1 ocorrência, os graves primeiro."""
    achados = [c() for c in CHECKS]
    com = [a for a in achados if a['n']]
    com.sort(key=lambda a: (not a['grave'], -a['n']))
    return com, sum(a['n'] for a in achados)


# ------------------------------------------------------------------ linha do tempo do item
ICONE = {'Entrada': ('fa-box-open', 'neutro'), 'Entrega': ('fa-hand-holding-hand', 'ok'),
         'Empréstimo': ('fa-rotate', 'ok'), 'Devolução': ('fa-arrow-rotate-left', 'aviso'),
         'Pedido de devolução': ('fa-bell', 'aviso'), 'Envio ao EC': ('fa-truck', 'aviso'),
         'Preparação': ('fa-screwdriver-wrench', 'neutro'), 'Liberação': ('fa-circle-check', 'ok'),
         'Transferência': ('fa-arrows-left-right', 'neutro'), 'A localizar': ('fa-magnifying-glass', 'erro'),
         'Separar p/ baixa': ('fa-box-archive', 'erro'), 'Baixa': ('fa-ban', 'erro'),
         'Ajuste': ('fa-wrench', 'aviso'), 'Manutenção': ('fa-wrench', 'aviso')}


def linha_do_tempo(movs, manuts):
    """Lançamentos e manutenções do item em uma lista só, do mais novo para o mais antigo."""
    ev = []
    for m in movs:
        ico, cor = ICONE.get(m.tipo, ('fa-circle', 'neutro'))
        det = []
        if m.etapa and m.etapa != 'Entregue':
            det.append(m.etapa.lower())
        if m.motivo:
            det.append(m.motivo.lower())
        if m.acess:
            det.append('com ' + m.acess.lower())
        if m.obs:
            det.append(m.obs)
        ev.append(dict(data=m.data, titulo=m.tipo, ico=ico, cor=cor, quem=m.nome or m.local or '',
                       matricula=m.matricula, detalhe=' · '.join(det)[:160], resp=m.resp,
                       href=url_for('lancar.lancamento', num=m.id), ref=f'Nº {m.id}',
                       termo=m.termo_arquivo and url_for('termo.assinado', num=m.id)))
    for o in manuts:
        ico, cor = ICONE['Manutenção']
        ev.append(dict(data=o.abertura, titulo='Manutenção aberta', ico=ico, cor=cor, quem=o.fornecedor or '',
                       matricula=None, detalhe=' · '.join(x for x in (o.defeito, o.status) if x)[:160], resp=None,
                       href=url_for('manutencao.inicio'), ref=f'OS {o.id}', termo=None))
        if o.retorno:
            ev.append(dict(data=o.retorno, titulo='Manutenção fechada', ico='fa-circle-check', cor='ok',
                           quem=o.fornecedor or '', matricula=None, detalhe=(o.solucao or '')[:160], resp=None,
                           href=url_for('manutencao.inicio'), ref=f'OS {o.id}', termo=None))
    ev.sort(key=lambda e: (e['data'] or '', e['ref']), reverse=True)
    return ev
