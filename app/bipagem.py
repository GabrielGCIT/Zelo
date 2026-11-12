"""Bipagem: uma ação, muitos itens.

O leitor de mão é um teclado — ele digita o que está no código de barras e dá Enter. Então a
tela de bipagem é só um campo que não perde o foco e uma fila que cresce. Cada bipe refaz a
conferência da fila inteira pelo mesmo motor dos lançamentos (`app.lancamento`), de modo que
nenhuma regra é reimplementada aqui: o que o balcão vê bipando é o que veria digitando.

A mesma fila atende a seleção em lote da lista de Itens — só muda a porta de entrada.

Dois detalhes que fazem a fila funcionar de verdade:

- os campos comuns (recebido por, mouse/teclado, para quem) valem por item, não por fila: o
  motor recusa "Recebido por" em celular, então a fila só manda esse campo para os itens em
  que ele cabe. Assim dá para bipar notebook e celular na mesma devolução;
- `conferir` recebe a aba livre (`lancamento.ABA_LIVRE`): a aba só serve para o motor barrar
  ação de outra guia da grade, e aqui quem limita as ações é a própria lista MODOS.
"""
from app import db
from app.lancamento import ABA_LIVRE as ABA
from app.lancamento import conferir, gravar
from app.models import Item

# modo → (título, ícone, ação do motor, campos comuns, explicação)
MODOS = {
    'devolver': ('Devolver', 'fa-rotate-left', 'Devolver', ['receb_por', 'motivo', 'chamado', 'obs'],
                 'Bipe tudo que está chegando no balcão. Notebook vai para a preparação; o resto volta ao estoque.'),
    'entregar': ('Entregar', 'fa-hand-holding', 'Entregar agora', ['para', 'chamado', 'tecnico', 'acess', 'obs'],
                 'Tudo que você bipar vai para a mesma pessoa, já entregue.'),
    'reservar': ('Reservar', 'fa-bookmark', 'Reservar', ['para', 'chamado', 'tecnico', 'acess', 'obs'],
                 'Separa os equipamentos para a pessoa; a entrega você confirma em Acompanhar.'),
    'ec': ('Enviado ao EC', 'fa-truck', 'Enviado ao EC', ['chamado', 'obs'],
           'Saiu da unidade para o EC e ainda não chegou: fica em trânsito.'),
    'pedir': ('Pedir devolução', 'fa-bell', 'Pedir devolução', ['motivo', 'chamado', 'obs'],
              'Cobra a devolução de quem está com o equipamento.'),
    'estoque': ('Entrada no estoque', 'fa-boxes-stacked', 'Entrada no estoque', ['obs'],
                'Equipamento que apareceu e não estava com ninguém volta ao estoque.'),
    'site': ('Enviar para outro site', 'fa-dolly', 'Enviar para outro site', ['destino'],
             'Transferência entre sites: o item fica em trânsito até a entrada no destino.'),
    'baixa': ('Separar para baixa', 'fa-trash-can', 'Separar para baixa', ['motivo', 'obs'],
              'Separa o que vai ser descartado; a baixa em si é lançada depois.'),
    'conferir': ('Conferir prateleira', 'fa-clipboard-check', None, ['site'],
                 'Não grava nada: compara o que você bipou com o que o Zelo diz que está nesse site.'),
}
# campo comum → itens em que ele cabe (o motor recusa nos outros)
SO_CABE = {
    'receb_por': lambda it: it.categoria == 'Notebook' and it.finalidade != 'Pool de empréstimo',
    'acess': lambda it: it.categoria == 'Notebook',
}


def modo_ok(modo):
    return modo if modo in MODOS else 'devolver'


def _item(it):
    return {'codigo': it.codigo, 'categoria': it.categoria, 'modelo': it.modelo, 'plaqueta': it.plaqueta,
            'tag': it.tag, 'hostname': it.hostname, 'situacao': it.situacao, 'com_quem': it.com_quem,
            'site': it.site, 'pool': it.finalidade == 'Pool de empréstimo'}


def _comum(modo, comum):
    """Só os campos comuns que o modo usa, já limpos."""
    return {k: (str((comum or {}).get(k) or '').strip()) for k in MODOS[modo][3]}


def linha_do_item(modo, it, comum):
    """O que a fila manda ao motor para este item: a ação do modo + os campos comuns que cabem nele."""
    c = _comum(modo, comum)
    d = {'acao': MODOS[modo][2], 'item': it.codigo}
    for k, v in c.items():
        if not v or k in ('site',):
            continue
        if k == 'destino':
            d['obs'] = v                       # o motor lê o site de destino na observação
        elif k in SO_CABE and not SO_CABE[k](it):
            continue
        else:
            d[k] = v
    return d


def _resolver(codigos):
    """Códigos lidos → (lista de (lido, item ou None), repetidos). Mantém a ordem do bipe."""
    from app.routes.consulta import achar_item
    vistos, saida, repetidos = set(), [], set()
    for lido in codigos:
        lido = str(lido or '').strip()
        if not lido:
            continue
        it = achar_item(lido)
        if it and it.codigo in vistos:
            repetidos.add(lido)
            saida.append((lido, it, True))
            continue
        if it:
            vistos.add(it.codigo)
        saida.append((lido, it, False))
    return saida, repetidos


def fila(modo, codigos, comum):
    """Confere a fila inteira e devolve o que a tela mostra, sem gravar nada."""
    modo = modo_ok(modo)
    lidos, _rep = _resolver(codigos)
    if modo == 'conferir':
        return _prateleira(lidos, _comum(modo, comum).get('site', ''))
    alvos = [(lido, it) for lido, it, rep in lidos if it and not rep]
    res = conferir([linha_do_item(modo, it, comum) for _l, it in alvos], ABA) if alvos else []
    por_codigo = {it.codigo: r for (_l, it), r in zip(alvos, res)}
    linhas, resumo = [], {'ok': 0, 'aviso': 0, 'erro': 0, 'total': 0}
    for lido, it, rep in lidos:
        if not it:
            linhas.append({'lido': lido, 'item': None, 'status': 'erro', 'msg': 'Não encontrei esse código no Zelo'})
        elif rep:
            linhas.append({'lido': lido, 'item': _item(it), 'status': 'repetido', 'msg': 'Já está na fila'})
        else:
            r = por_codigo.get(it.codigo)
            linhas.append({'lido': lido, 'item': _item(it), 'status': (r.status or 'erro') if r else 'erro',
                           'msg': (r.msg if r else 'Nada a lançar')})
        s = linhas[-1]['status']
        if s in resumo:
            resumo[s] += 1
        if s != 'repetido':
            resumo['total'] += 1
    return {'modo': modo, 'acao': MODOS[modo][2], 'linhas': linhas, 'resumo': resumo, 'faltando': None, 'esperado': None}


def gravar_fila(modo, codigos, comum, resp):
    """Grava num lote só as linhas que passaram. Devolve (quantas, lote, retorno do fila())."""
    modo = modo_ok(modo)
    if modo == 'conferir':
        return 0, None, fila(modo, codigos, comum)
    lidos, _rep = _resolver(codigos)
    alvos = [it for _l, it, rep in lidos if it and not rep]
    if not alvos:
        return 0, None, fila(modo, codigos, comum)
    res, n, lote = gravar([linha_do_item(modo, it, comum) for it in alvos], ABA, resp)
    saida = {'modo': modo, 'acao': MODOS[modo][2], 'resumo': {'ok': 0, 'aviso': 0, 'erro': 0, 'total': len(alvos)},
             'faltando': None, 'esperado': None, 'linhas': []}
    movs = []
    for it, r in zip(alvos, res):
        gravada = r.status in ('ok', 'aviso')
        saida['resumo'][r.status if r.status in saida['resumo'] else 'erro'] += 1
        saida['linhas'].append({'lido': it.codigo, 'item': _item(it), 'status': r.status or 'erro', 'msg': r.msg,
                                'gravada': gravada, 'nums': [m.id for m in r.movs if m.id]})
        movs += [m for m in r.movs if m.id] if gravada else []
    return n, lote, dict(saida, movs=movs)


def _prateleira(lidos, site):
    """Conferência de prateleira: o que você bipou × o que o Zelo diz que está em estoque nesse site."""
    esperado = {}
    if site:
        esperado = {i.codigo: i for i in Item.query.filter(Item.situacao == 'Em estoque', Item.site == site).all()}
    linhas, resumo = [], {'ok': 0, 'aviso': 0, 'erro': 0, 'total': 0}
    bipados = set()
    for lido, it, rep in lidos:
        if not it:
            linhas.append({'lido': lido, 'item': None, 'status': 'erro', 'msg': 'Não encontrei esse código no Zelo'})
        elif rep:
            linhas.append({'lido': lido, 'item': _item(it), 'status': 'repetido', 'msg': 'Já está na fila'})
        else:
            bipados.add(it.codigo)
            if it.situacao != 'Em estoque':
                m = f'Está como {it.situacao}' + (f' com {it.com_quem}' if it.com_quem else '') + ', e está aqui na prateleira'
                linhas.append({'lido': lido, 'item': _item(it), 'status': 'aviso', 'msg': m})
            elif site and it.site != site:
                linhas.append({'lido': lido, 'item': _item(it), 'status': 'aviso',
                               'msg': f'O Zelo diz que está em {it.site or "site não informado"}'})
            else:
                linhas.append({'lido': lido, 'item': _item(it), 'status': 'ok',
                               'msg': 'Confere com o Zelo' if site else
                                      'Em estoque — escolha o site para conferir a prateleira inteira'})
        s = linhas[-1]['status']
        if s in resumo:
            resumo[s] += 1
        if s != 'repetido':
            resumo['total'] += 1
    faltando = [_item(i) for c, i in sorted(esperado.items()) if c not in bipados] if site else None
    return {'modo': 'conferir', 'acao': None, 'linhas': linhas, 'resumo': resumo, 'faltando': faltando,
            'esperado': len(esperado) if site else None}


def codigos_de_itens(codigos):
    """Para a seleção em lote da lista de Itens: valida os códigos e devolve os que existem."""
    return [c for c in dict.fromkeys(codigos) if db.session.get(Item, c)]
