"""Pendências: o que ficou sem preencher num lançamento. Nada disso bloqueia a gravação; o sistema cobra
depois, na fila de quem lançou, até alguém completar. A lista é calculada na hora (some quando preenche)."""
from app import db
from app.models import Item, Movimentacao, cfg

ROTULO = {'chamado': 'Nº do chamado', 'tecnico': 'Técnico', 'termo': 'Termo assinado', 'receb_por': 'Recebido por',
          'arquivo': 'Arquivo do termo', 'solucao': 'O que foi feito'}
EDITAVEIS = [('data', 'Data', 'date'), ('chamado', 'Nº do chamado', 'text'), ('tecnico', 'Técnico', 'tecnico'),
             ('termo', 'Termo', 'termo'), ('data_ass', 'Data da assinatura', 'date'), ('data_ent', 'Data da entrega', 'date'),
             ('receb_por', 'Recebido por', 'recebido'), ('motivo', 'Motivo', 'text'),
             ('obs', 'Observação', 'text')]


def pendencias(m, item=None):
    """Lista de chaves pendentes do lançamento (ver ROTULO)."""
    p = []
    if m.tipo in ('Entrega', 'Empréstimo') and m.etapa != 'Cancelado':
        if not m.chamado:
            p.append('chamado')
        if not m.tecnico:
            p.append('tecnico')
        if m.etapa == 'Entregue' and m.termo == 'Pendente':
            p.append('termo')
        elif m.termo == 'Assinado' and not m.termo_arquivo and not m.link:
            p.append('arquivo')
    elif m.tipo == 'Devolução' and m.item:
        it = item or db.session.get(Item, m.item)
        if it and it.categoria == 'Notebook' and it.finalidade != 'Pool de empréstimo' and not m.receb_por:
            p.append('receb_por')
    return p


def texto(m, item=None):
    return [ROTULO[k] for k in pendencias(m, item)]


def abertas(resp=None, limite=300):
    """[(mov, [rótulos])] dos lançamentos desde o início do fluxo novo que ainda têm pendência."""
    desde = cfg('fluxo_preparacao') or '2026-11-05'
    q = Movimentacao.query.filter(Movimentacao.tipo.in_(('Entrega', 'Empréstimo', 'Devolução')), Movimentacao.data >= desde)
    if resp:
        q = q.filter(Movimentacao.resp == resp)
    movs = q.order_by(Movimentacao.id.desc()).limit(2000).all()
    itens = {i.codigo: i for i in Item.query.filter(Item.codigo.in_({m.item for m in movs if m.item})).all()} if movs else {}
    out = []
    for m in movs:
        t = texto(m, itens.get(m.item))
        if t:
            out.append((m, t))
            if len(out) >= limite:
                break
    return out


def editar(m, novos, quem):
    """Corrige campos de um lançamento. Devolve a lista 'campo: antes → depois' (vazia = nada mudou)."""
    from app.regras import tocar
    mudou = []
    for k, rot, _t in EDITAVEIS:
        if k not in novos:
            continue
        v = (novos[k] or '').strip() or None
        if k == 'data' and not v:
            continue
        if getattr(m, k) != v:
            mudou.append(f'{rot}: {getattr(m, k) or "(vazio)"} → {v or "(vazio)"}')
            setattr(m, k, v)
    if mudou:
        if m.termo == 'Assinado' and not m.data_ass:
            m.data_ass = m.data
        db.session.flush()
        tocar([m.item], [m.linha])
        db.session.commit()
    return mudou


def pode_desfazer(m):
    """Só o último lançamento do item (e da linha): desfazer um do meio deixaria o histórico incoerente."""
    if m.item:
        ult = Movimentacao.query.filter_by(item=m.item).order_by(Movimentacao.id.desc()).first()
        if ult and ult.id != m.id:
            return False
    if m.linha:
        ult = Movimentacao.query.filter_by(linha=m.linha).order_by(Movimentacao.id.desc()).first()
        if ult and ult.id != m.id:
            return False
    return True


def desfazer(m):
    from app.models import EnvioSD, MovConsumivel
    from app.regras import tocar
    item, linha = m.item, m.linha
    MovConsumivel.query.filter_by(mov_id=m.id).delete()
    EnvioSD.query.filter(EnvioSD.mov_id == m.id, EnvioSD.status != 'Enviado').delete()
    db.session.delete(m)
    db.session.flush()
    tocar([item], [linha])
    db.session.commit()
