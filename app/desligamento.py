"""Desligamento: uma fila só para devolver tudo que a pessoa tem.

Quando alguém sai, o que estava com ela está espalhado: notebook, celular, linha, mouse e
teclado que saíram do EC, acessório emprestado com termo próprio. Hoje isso é devolvido em
quatro telas diferentes, e é por aí que escapa equipamento. Esta fila junta tudo e devolve de
uma vez, no mesmo motor dos lançamentos.

Linha que está dentro de um aparelho em devolução vem junto sozinha (o motor já faz isso), por
isso ela aparece amarrada ao aparelho e não como item separado da fila.
"""
from datetime import date

from app import db
from app.lancamento import ABA_LIVRE, gravar
from app.models import EmprestimoAcessorio, Item, Linha, MovConsumivel, Movimentacao, Pessoa

SIT_COM_PESSOA = ('Em uso', 'Emprestado', 'Reservada', 'Pendente devolução', 'Em trânsito para o EC')
# o que fazer com uma linha que não está em aparelho devolvido
ACOES_LINHA = ['Devolver', 'Desativar linha', 'Deixar com a pessoa']


def o_que_tem(pid):
    """Tudo que ainda consta com a pessoa, separado por natureza."""
    from app.routes.consulta import kit_da_pessoa
    itens = (Item.query.filter(Item.matricula == pid, Item.situacao.in_(SIT_COM_PESSOA))
             .order_by(Item.categoria, Item.codigo).all())
    nos_aparelhos = {i.codigo: None for i in itens}
    linhas = Linha.query.filter(Linha.matricula == pid, Linha.situacao == 'Em uso').order_by(Linha.numero).all()
    soltas = []
    for ln in linhas:
        if ln.aparelho in nos_aparelhos:
            nos_aparelhos[ln.aparelho] = ln
        else:
            soltas.append(ln)
    acess = (EmprestimoAcessorio.query.filter(EmprestimoAcessorio.matricula == pid,
                                              EmprestimoAcessorio.devolvido.is_(None))
             .order_by(EmprestimoAcessorio.id).all())
    return {'itens': itens, 'linha_do_item': nos_aparelhos, 'linhas': soltas, 'kit': kit_da_pessoa(pid), 'acess': acess}


def total(t):
    return len(t['itens']) + len(t['linhas']) + len(t['kit']) + len(t['acess'])


def pendentes():
    """Pessoas desligadas que ainda constam com alguma coisa, mais quem tem devolução pedida."""
    com_coisa = {}
    for pid, in db.session.query(Item.matricula).filter(Item.matricula.isnot(None),
                                                        Item.situacao.in_(SIT_COM_PESSOA)).distinct():
        com_coisa[pid] = True
    for pid, in db.session.query(Linha.matricula).filter(Linha.matricula.isnot(None),
                                                         Linha.situacao == 'Em uso').distinct():
        com_coisa[pid] = True
    for pid, in db.session.query(EmprestimoAcessorio.matricula).filter(EmprestimoAcessorio.devolvido.is_(None),
                                                                       EmprestimoAcessorio.matricula.isnot(None)).distinct():
        com_coisa[pid] = True
    if not com_coisa:
        return []
    ps = Pessoa.query.filter(Pessoa.id.in_(list(com_coisa)), Pessoa.situacao == 'Desligado').order_by(Pessoa.nome).all()
    saida = []
    for p in ps:
        t = o_que_tem(p.id)
        if total(t):
            saida.append({'p': p, 't': t, 'n': total(t),
                          'desde': _desligado_desde(p.id)})
    return saida


def _desligado_desde(pid):
    """A data do pedido de devolução por desligamento, que é quando o Zelo soube da saída."""
    m = (Movimentacao.query.filter(Movimentacao.matricula == pid, Movimentacao.tipo == 'Pedido de devolução',
                                   Movimentacao.motivo == 'Desligamento').order_by(Movimentacao.id.desc()).first())
    return m.data if m else None


def devolver_tudo(p, escolhas, resp):
    """Devolve o que foi marcado. escolhas: {itens:[cod], linhas:{numero: ação}, kit:[(mov_id, consumível)], acess:[id]}.

    Devolve (ok, mensagem, detalhes[], lançamentos gravados) — os lançamentos vão para a fila do
    Service Desk como os de qualquer outra tela.
    """
    hoje = date.today().isoformat()
    t = o_que_tem(p.id)
    feitos, erros = [], []

    quer_item = [c for c in (escolhas.get('itens') or []) if any(i.codigo == c for i in t['itens'])]
    linhas_quer = {n: a for n, a in (escolhas.get('linhas') or {}).items()
                   if any(l.numero == n for l in t['linhas']) and a in ACOES_LINHA and a != 'Deixar com a pessoa'}
    pedidos = ([{'acao': 'Devolver', 'item': c, 'motivo': 'Desligamento',
                 'receb_por': escolhas.get('receb_por') or '', 'obs': escolhas.get('obs') or ''} for c in quer_item]
               + [{'acao': a, 'linha': n, 'motivo': 'Desligamento', 'obs': escolhas.get('obs') or ''}
                  for n, a in linhas_quer.items()])
    # "Recebido por" só vale em devolução de notebook; nos outros o motor recusa o campo
    for d in pedidos:
        if d.get('receb_por'):
            it = db.session.get(Item, d['item'])
            if not (it and it.categoria == 'Notebook' and it.finalidade != 'Pool de empréstimo'):
                d['receb_por'] = ''
    movs = []
    if pedidos:
        res, n, _lote = gravar(pedidos, ABA_LIVRE, resp)
        for d, r in zip(pedidos, res):
            alvo = d.get('item') or f'linha {d.get("linha")}'
            if r.status in ('ok', 'aviso'):
                feitos.append(f'{alvo}: {r.msg}')
                movs += [x for x in r.movs if x.id]
            else:
                erros.append(f'{alvo}: {r.msg}')

    for mov_id, cons in (escolhas.get('kit') or []):
        if not any(str(m) == str(mov_id) and c == cons for m, c, _q in t['kit']):
            erros.append(f'{cons}: já não consta com a pessoa')
            continue
        db.session.add(MovConsumivel(data=hoje, consumivel=cons, site='EC', movimento='Entrada', qtd=1, destino=p.nome,
                                     resp=resp, mov_id=int(mov_id),
                                     obs=f'Devolução no desligamento de {p.nome} (entrega Nº {mov_id})'))
        feitos.append(f'{cons}: voltou ao estoque do EC')

    for eid in (escolhas.get('acess') or []):
        ea = db.session.get(EmprestimoAcessorio, int(eid)) if str(eid).isdigit() else None
        if not ea or ea.devolvido or ea.matricula != p.id:
            erros.append(f'EA-{eid}: não encontrado ou já devolvido')
            continue
        ea.devolvido, ea.receb = hoje, escolhas.get('receb_por') or resp
        ea.obs_dev = 'Devolução no desligamento'
        db.session.add(MovConsumivel(data=hoje, consumivel=ea.consumivel, site='EC', movimento='Entrada', qtd=ea.qtd,
                                     destino=ea.nome, resp=resp, obs=f'Devolução EA-{ea.id:04d} (desligamento)'))
        feitos.append(f'EA-{ea.id:04d}: {ea.consumivel} devolvido')
    db.session.commit()

    if not feitos and not erros:
        return False, 'Nada marcado para devolver.', [], []
    resta = total(o_que_tem(p.id))
    msg = f'{len(feitos)} devolução(ões) registrada(s)'
    msg += f'; {len(erros)} não deu(deram)' if erros else ''
    msg += '. Nada mais consta com a pessoa.' if not resta else f'. Ainda constam {resta} item(ns).'
    # as devoluções daqui valem como qualquer outra: avisam o chamado e soltam o ativo no Service Desk
    return bool(feitos), msg, feitos + erros, movs
