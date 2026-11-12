"""Lembretes: o que precisa de alguém hoje, em ordem de urgência.

A fila (Minha fila) lista tudo que está em aberto; isso responde "o que tem para fazer".
Lembrete é outra coisa: é o que já passou do ponto e está cobrando. A diferença é o TEMPO —
reserva de ontem é rotina, reserva de três semanas é problema. Por isso cada lembrete tem um
prazo próprio e só aparece depois dele.

Aparece no alto do Painel e como número ao lado de Minha fila: a cobrança é na tela, toda vez que
alguém abre o Zelo. É de propósito que não há disparo por fora — avisar fica onde o trabalho já
acontece, sem mais um canal para manter.

Cada lembrete é um dicionário com: chave, titulo, n, porque (por que isso importa), url,
acao (o rótulo do botão) e urgencia ('alta' | 'media' | 'baixa'). n == 0 não entra na lista.
"""
from datetime import date, timedelta

from flask import url_for
from sqlalchemy import func

from app import db
from app.models import (Consumivel, Contrato, EmprestimoAcessorio, EnvioSD, Item, Manutencao, Movimentacao, Pessoa, cfg)

# prazo (em dias) a partir do qual cada coisa passa a cobrar — ajustável em Configurações
PRAZOS_PADRAO = {'reserva': 3, 'devolucao': 7, 'preparacao': 5, 'termo': 7, 'pendencia': 7, 'os': 15, 'assinatura': 3}
ORDEM = {'alta': 0, 'media': 1, 'baixa': 2}


def _dias(chave):
    v = cfg(f'lembrete_{chave}')
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return PRAZOS_PADRAO[chave]


def _ate(dias):
    return (date.today() - timedelta(days=dias)).isoformat()


def tudo():
    """Todos os lembretes com contagem > 0, do mais urgente ao menos. Devolve (lista, total)."""
    hoje = date.today().isoformat()
    em7 = (date.today() + timedelta(days=7)).isoformat()
    L = []

    def add(chave, titulo, n, porque, url, acao, urgencia):
        if n:
            L.append(dict(chave=chave, titulo=titulo, n=n, porque=porque, url=url, acao=acao, urgencia=urgencia))

    # --- empréstimos
    add('emprestimo_vencido', 'Empréstimo vencido',
        Item.query.filter(Item.situacao == 'Emprestado', Item.prazo.isnot(None), Item.prazo < hoje).count(),
        'O prazo acabou e a máquina do pool não voltou: ela não está disponível para a próxima emergência.',
        url_for('consulta.emprestimos'), 'Cobrar ou renovar', 'alta')
    add('emprestimo_vence', 'Empréstimo vencendo em 7 dias',
        Item.query.filter(Item.situacao == 'Emprestado', Item.prazo.isnot(None), Item.prazo >= hoje,
                          Item.prazo <= em7).count(),
        'Avise agora e você renova no prazo, em vez de cobrar depois de vencido.',
        url_for('consulta.emprestimos'), 'Ver prazos', 'media')
    add('acessorio_vencido', 'Acessório emprestado vencido',
        EmprestimoAcessorio.query.filter(EmprestimoAcessorio.devolvido.is_(None), EmprestimoAcessorio.prazo.isnot(None),
                                         EmprestimoAcessorio.prazo < hoje).count(),
        'Fonte, mouse e headset emprestados com prazo estourado continuam baixados do estoque do EC.',
        url_for('painel.fila'), 'Ver na fila', 'media')

    # --- fluxo travado
    d = _dias('devolucao')
    add('devolucao_atrasada', f'Devolução pedida há mais de {d} dias',
        Item.query.filter(Item.situacao.in_(('Pendente devolução', 'Em trânsito para o EC')),
                          Item.desde.isnot(None), Item.desde < _ate(d)).count(),
        'Equipamento cobrado e não devolvido é o que mais se perde: quanto mais tempo passa, menos gente lembra onde está.',
        url_for('painel.fila'), 'Cobrar', 'alta')
    d = _dias('reserva')
    add('reserva_parada', f'Reserva parada há mais de {d} dias',
        Item.query.filter(Item.situacao == 'Reservada', Item.desde.isnot(None), Item.desde < _ate(d)).count(),
        'Máquina reservada não entra no estoque e não está com ninguém: ou entrega, ou libera.',
        url_for('acompanhar.inicio'), 'Abrir o quadro', 'media')
    d = _dias('preparacao')
    add('preparacao_parada', f'Preparação parada há mais de {d} dias',
        Item.query.filter(Item.situacao.in_(('Devolvido', 'Em preparação')), Item.desde.isnot(None),
                          Item.desde < _ate(d)).count(),
        'Devolvido que não é preparado não volta para o estoque, e aí falta máquina para a próxima admissão.',
        url_for('acompanhar.inicio') + '#preparacao', 'Preparar', 'media')
    add('transito_antigo', 'Transferência entre sites sem chegada',
        Item.query.filter(Item.situacao == 'Em transferência', Item.desde.isnot(None), Item.desde < _ate(15)).count(),
        'Saiu de um site e ninguém deu entrada no destino há mais de 15 dias.',
        url_for('consulta.itens', situacao='Em transferência'), 'Ver itens', 'media')
    add('a_localizar', 'Equipamento a localizar',
        Item.query.filter(Item.situacao == 'A localizar').count(),
        'Item sem paradeiro conhecido. Cada um aqui é um ativo que o inventário vai cobrar.',
        url_for('consulta.itens', situacao='A localizar'), 'Ver itens', 'alta')

    # --- termo e pendências
    d = _dias('termo')
    add('termo_pendente', f'Termo não assinado há mais de {d} dias',
        Item.query.filter(Item.situacao.in_(('Em uso', 'Emprestado')), Item.termo == 'Pendente',
                          Item.desde.isnot(None), Item.desde < _ate(d)).count(),
        'Sem termo assinado não há documento ligando o equipamento à pessoa.',
        url_for('acompanhar.inicio'), 'Ver entregas', 'alta')
    add('assinatura_parada', f'Assinatura pedida há mais de {_dias("assinatura")} dias', _assinaturas_paradas(),
        'O link de assinatura foi gerado e ninguém assinou. Sem as duas vias o termo não fecha e o ativo não é liberado.',
        url_for('painel.fila') + '#assinaturas', 'Ver quem falta', 'media')
    add('pendencia_antiga', f'Lançamento incompleto há mais de {_dias("pendencia")} dias',
        _pendencias_antigas(_dias('pendencia')),
        'Campo que ficou para depois e ninguém voltou para preencher. Depois de um mês, ninguém lembra o que era.',
        url_for('painel.fila'), 'Completar', 'media')

    # --- pessoas
    add('desligado_com_item', 'Desligado ainda com equipamento', _desligados(),
        'A pessoa saiu e o equipamento continua no nome dela. É a maior fonte de perda de ativo.',
        url_for('desligar.lista'), 'Devolver tudo', 'alta')

    # --- manutenção
    d = _dias('os')
    add('os_parada', f'Ocorrência aberta há mais de {d} dias',
        sum(1 for m in Manutencao.query.filter(Manutencao.abertura.isnot(None), Manutencao.abertura < _ate(d)).all()
            if m.aberta),
        'OS que não anda costuma estar esperando resposta do fornecedor — cobre o caso.',
        url_for('manutencao.inicio'), 'Abrir manutenção', 'media')

    # --- integração
    add('sd_erro', 'Envio ao Service Desk com erro',
        EnvioSD.query.filter(EnvioSD.status == 'Erro').count(),
        'O termo ou o ativo não chegaram ao chamado. O lançamento está certo no Zelo; falta só reenviar.',
        url_for('admin.servicedesk'), 'Reenviar', 'alta')

    # --- estoque e contratos
    add('estoque_minimo', 'Consumível abaixo do mínimo', _abaixo_do_minimo(),
        'Sem mouse e teclado na prateleira, a próxima admissão sai incompleta.',
        url_for('estoque.consumiveis'), 'Ver consumíveis', 'media')
    aviso = int(cfg('aviso_contrato_dias') or 90)
    add('contrato_vence', f'Contrato vencendo em {aviso} dias',
        Contrato.query.filter(Contrato.fim.isnot(None), Contrato.fim >= hoje,
                              Contrato.fim <= (date.today() + timedelta(days=aviso)).isoformat()).count(),
        'Renovação de locação não se resolve na semana do vencimento.',
        url_for('consulta.contratos'), 'Ver contratos', 'baixa')
    add('garantia_vence', 'Garantia vencendo em 90 dias',
        Item.query.filter(Item.situacao != 'Baixada', Item.garantia.isnot(None), Item.garantia >= hoje,
                          Item.garantia <= (date.today() + timedelta(days=90)).isoformat()).count(),
        'Defeito encontrado antes do fim da garantia é troca; depois, é compra.',
        url_for('consulta.contratos'), 'Ver garantias', 'baixa')

    L.sort(key=lambda x: (ORDEM[x['urgencia']], -x['n']))
    return L, sum(x['n'] for x in L)


def _assinaturas_paradas():
    from app.models import Assinatura
    corte = _ate(_dias('assinatura'))
    return (Assinatura.query.filter(Assinatura.assinado.is_(None), Assinatura.cancelado.is_(None),
                                    Assinatura.criado < corte).count())


def _pendencias_antigas(dias):
    from app.pendencias import abertas
    corte = _ate(dias)
    return sum(1 for m, _t in abertas(None, limite=400) if (m.data or '9999') < corte)


def _desligados():
    return (db.session.query(func.count(func.distinct(Item.matricula)))
            .join(Pessoa, Pessoa.id == Item.matricula)
            .filter(Pessoa.situacao == 'Desligado',
                    Item.situacao.in_(('Em uso', 'Emprestado', 'Reservada', 'Pendente devolução'))).scalar() or 0)


def _abaixo_do_minimo():
    from app.estoque import saldos
    sal = saldos()
    return sum(1 for c in Consumivel.query.filter(Consumivel.minimo.isnot(None), Consumivel.minimo > 0).all()
               if sal.get(c.nome, {}).get('EC', 0) < c.minimo)


def quantos_para(nome):
    """Número ao lado de "Minha fila": o que está no nome da pessoa e já passou do prazo."""
    from app.pendencias import abertas
    corte = _ate(_dias('pendencia'))
    n = sum(1 for m, _t in abertas(nome, limite=400) if (m.data or '9999') < corte)
    n += (Item.query.join(Movimentacao, Movimentacao.id == Item.ultima_mov_id)
          .filter(Item.situacao == 'Emprestado', Item.prazo.isnot(None), Item.prazo < date.today().isoformat(),
                  Movimentacao.resp == nome).count())
    return n


def alta(lista=None):
    """Só os urgentes — para a faixa do alto do Painel."""
    L = lista if lista is not None else tudo()[0]
    return [x for x in L if x['urgencia'] == 'alta']


# A barra lateral mostra o número em TODA tela, e a conta percorre o Histórico. Um cache curto
# resolve: o balcão não precisa do número ao segundo, e assim nenhuma tela paga por ele.
_CACHE = {'em': None, 'v': (0, 0)}
VALIDADE = 60                                   # segundos


def contagem(agora=None):
    """(quantos lembretes, quantos urgentes), recalculado no máximo uma vez por minuto."""
    from time import monotonic
    t = agora if agora is not None else monotonic()
    if _CACHE['em'] is None or t - _CACHE['em'] >= VALIDADE:
        L, _n = tudo()
        _CACHE['v'] = (len(L), sum(1 for x in L if x['urgencia'] == 'alta'))
        _CACHE['em'] = t
    return _CACHE['v']


def esquecer():
    """Invalida o cache — usado pelos testes e depois de um lançamento em lote."""
    _CACHE['em'] = None
