"""Regras de situação: as mesmas fórmulas da planilha, em Python.

Situação do item = o que o ÚLTIMO lançamento que o afeta diz, com duas exceções:
- ocorrência de manutenção aberta → "Manutenção" (por cima de tudo);
- notebook de uso definitivo devolvido a partir da data do fluxo → "Devolvido"
  (vai para a preparação antes de voltar ao estoque).
"""
from app import db
from app.models import Item, Linha, Manutencao, Movimentacao, cfg

# Tipo → situação do item / da linha (tTipos da planilha). Entrega e Empréstimo saem pela etapa.
SIT_ITEM_TIPO = {
    'Entrada': 'Em estoque', 'Pedido de devolução': 'Pendente devolução', 'Envio ao EC': 'Em trânsito para o EC',
    'Devolução': 'Em estoque', 'Preparação': 'Em preparação', 'Liberação': 'Em estoque',
    'Transferência': 'Em transferência', 'Separar p/ baixa': 'Aguardando baixa', 'Baixa': 'Baixada',
    'A localizar': 'A localizar',
}
SIT_LINHA_TIPO = {
    'Entrega': 'Em uso', 'Empréstimo': 'Em uso', 'Devolução': 'Livre', 'Ativar linha': 'Em uso',
    'Desativar linha': 'Livre', 'Cancelar linha': 'Cancelada', 'Baixa': 'Livre',
}
TIPOS = list(SIT_ITEM_TIPO) + ['Entrega', 'Empréstimo', 'Ativar linha', 'Desativar linha', 'Cancelar linha']
COM_QUEM_SIT = ('Em uso', 'Reservada', 'Emprestado', 'Pendente devolução', 'Em trânsito para o EC')


def sit_item_da_mov(m, categoria=None, finalidade=None):
    """Como o item fica depois deste lançamento ('' = o lançamento não mexe no item)."""
    if not m.item:
        return ''
    t = m.tipo
    if t in ('Entrega', 'Empréstimo'):
        if m.etapa == 'Entregue':
            return 'Em uso' if t == 'Entrega' else 'Emprestado'
        return 'Em estoque' if m.etapa == 'Cancelado' else 'Reservada'
    if (t == 'Devolução' and categoria == 'Notebook' and finalidade != 'Pool de empréstimo'
            and (m.data or '') >= (cfg('fluxo_preparacao') or '9999')):
        return 'Devolvido'
    return SIT_ITEM_TIPO.get(t, '')


def sit_linha_da_mov(m):
    if not m.linha:
        return ''
    if m.tipo in ('Entrega', 'Empréstimo') and m.etapa == 'Cancelado':
        return 'Livre'
    return SIT_LINHA_TIPO.get(m.tipo, '')


def recalcular_item(item, manut_abertas=None, movs=None):
    """Atualiza o cache do item a partir do Histórico. `movs`/`manut_abertas` são atalhos para recálculo em massa."""
    if movs is None:
        movs = Movimentacao.query.filter_by(item=item.codigo).order_by(Movimentacao.id).all()
    ult, sit = None, ''
    for m in movs:
        s = sit_item_da_mov(m, item.categoria, item.finalidade)
        if s:
            ult, sit = m, s
    if manut_abertas is None:
        aberta = Manutencao.query.filter(Manutencao.item == item.codigo,
                                         ~Manutencao.status.in_(['Concluída', 'Sem conserto'])).first() is not None
    else:
        aberta = item.codigo in manut_abertas
    sit_hist = sit or 'Sem movimentação'
    item.situacao = 'Manutenção' if aberta else sit_hist
    com = ult is not None and (sit_hist in COM_QUEM_SIT and (not aberta or sit_hist in ('Em uso', 'Emprestado')))
    item.ultima_mov_id = ult.id if ult else None
    item.com_quem = ((ult.nome or ult.local) if com else None)
    item.matricula = ult.matricula if com else None
    item.desde = ult.data if ult else None
    item.termo = ult.termo if com else None
    item.prazo = ult.prazo if (ult and item.situacao == 'Emprestado') else None
    item.etapa = ult.etapa if (ult and item.situacao == 'Reservada') else None
    if item.categoria == 'Notebook' and item.situacao == 'Em estoque' and item.finalidade != 'Pool de empréstimo':
        item.kit = 'Completo' if ult and ult.tipo == 'Liberação' else 'A conferir'
    else:
        item.kit = None


def recalcular_linha(linha, movs=None):
    if movs is None:
        movs = Movimentacao.query.filter_by(linha=linha.numero).order_by(Movimentacao.id).all()
    ult, sit = None, ''
    for m in movs:
        s = sit_linha_da_mov(m)
        if s:
            ult, sit = m, s
    linha.situacao = sit or 'Livre'
    linha.ultima_mov_id = ult.id if ult else None
    em_uso = linha.situacao == 'Em uso'
    linha.com_quem = (ult.nome or ult.local) if em_uso else None
    linha.matricula = ult.matricula if em_uso else None
    linha.aparelho = ult.item if em_uso else None
    linha.desde = ult.data if ult else None


def recalcular_tudo():
    """Recalcula todos os itens e linhas (importação, correção em massa)."""
    from collections import defaultdict
    por_item, por_linha = defaultdict(list), defaultdict(list)
    for m in Movimentacao.query.order_by(Movimentacao.id).all():
        if m.item:
            por_item[m.item].append(m)
        if m.linha:
            por_linha[m.linha].append(m)
    abertas = {m.item for m in Manutencao.query.all() if m.aberta}
    for it in Item.query.all():
        recalcular_item(it, abertas, por_item.get(it.codigo, []))
    for ln in Linha.query.all():
        recalcular_linha(ln, por_linha.get(ln.numero, []))
    db.session.commit()


def tocar(itens=(), linhas=()):
    """Recalcula só o que um lançamento mexeu."""
    for c in {c for c in itens if c}:
        it = db.session.get(Item, c)
        if it:
            recalcular_item(it)
    for n in {n for n in linhas if n}:
        ln = db.session.get(Linha, n)
        if ln:
            recalcular_linha(ln)
