"""Solicitações: o trabalho que o Zelo pede a alguém, com prazo — e que pode virar chamado no SD.

Três casos (etapa G do levantamento):
- **recolhimento**: a pessoa saiu e ainda tem equipamento; um pedido com a lista do que recolher;
- **manutencao**: a OS aberta no Zelo vira chamado com o ativo anexado;
- **devolucao**: a devolução foi pedida e ninguém atende.

O que não é óbvio:
- "resolvida" é calculada do estado do Zelo (ver `models.Solicitacao`), nunca digitada;
- uma solicitação em aberto por assunto: pedir de novo o recolhimento da mesma pessoa devolve a
  que já existe em vez de abrir outra — chamado em dobro no SD é ruído que alguém precisa fechar;
- abrir o chamado é sempre um clique de alguém e vai pela fila (`EnvioSD` tipo 'abrir'), nunca
  automático: o SD da MB manda e-mail a cada chamado novo.
"""
import json
from datetime import date, datetime, timedelta

from app import db
from app.models import Item, Manutencao, Pessoa, Solicitacao

TIPOS = {'recolhimento': 'Recolhimento no desligamento', 'manutencao': 'Manutenção',
         'devolucao': 'Cobrança de devolução'}
PRAZO_PADRAO = {'recolhimento': 5, 'manutencao': 10, 'devolucao': 5}


def conf_caso(tipo):
    """A configuração do caso em `sd_chamado_<tipo>`: 'solicitante=..; template=..; categoria=..;
    grupo=..; prazo=..'. Chaves em minúsculas; valor vazio fica de fora."""
    from app import servicedesk as sd
    return {k.lower(): v for k, v in sd._pares(sd.conf(f'sd_chamado_{tipo}')) if v}


def prazo_dias(tipo):
    try:
        return max(1, int(conf_caso(tipo).get('prazo') or PRAZO_PADRAO[tipo]))
    except ValueError:
        return PRAZO_PADRAO[tipo]


def _descr_item(it):
    partes = [f'{it.categoria or "Item"} {it.modelo or ""}'.strip(), f'código {it.codigo}']
    if it.hostname:
        partes.append(f'hostname {it.hostname}')
    if it.tag and it.tag != it.codigo:
        partes.append(f'service tag {it.tag}')
    if it.plaqueta and it.plaqueta != it.codigo:
        partes.append(f'plaqueta {it.plaqueta}')
    return ' — '.join([partes[0], ', '.join(partes[1:])])


def montar(tipo, pessoa=None, item=None, os_id=None):
    """O que a solicitação diz. Devolve (dados, erro); dados tem assunto, descricao, itens e as chaves."""
    if tipo not in TIPOS:
        return None, 'Tipo de solicitação desconhecido'
    if tipo == 'recolhimento':
        from app.desligamento import o_que_tem, total
        p = db.session.get(Pessoa, pessoa or '')
        if not p:
            return None, 'Pessoa não encontrada'
        t = o_que_tem(p.id)
        if not total(t):
            return None, f'Nada consta com {p.nome}: não há o que recolher'
        linhas = [f'{p.nome} ({p.id}) — {p.situacao or ""}{", CC " + p.cc if p.cc else ""}'
                  f'{", site " + p.site if p.site else ""}.', '', 'Recolher:']
        linhas += [f'- {_descr_item(it)}' for it in t['itens']]
        linhas += [f'- linha {ln.numero} ({ln.operadora or "operadora?"})' for ln in t['linhas']]
        linhas += [f'- {cons} (saiu do EC na entrega Nº {mov})' for mov, cons, _q in t['kit']]
        linhas += [f'- acessório EA-{ea.id:04d}: {ea.consumivel}' for ea in t['acess']]
        return {'tipo': tipo, 'pessoa': p.id, 'item': None, 'os_id': None,
                'itens': [it.codigo for it in t['itens']],
                'assunto': f'Recolhimento de equipamentos — {p.nome} ({p.id})',
                'descricao': '\n'.join(linhas)}, ''
    if tipo == 'manutencao':
        os_ = db.session.get(Manutencao, int(os_id)) if str(os_id or '').isdigit() else None
        if not os_ or not os_.aberta:
            return None, 'Ocorrência não encontrada ou já fechada'
        it = db.session.get(Item, os_.item)
        if not it:
            return None, 'O item da ocorrência não existe mais'
        linhas = [f'OS {os_.id} aberta no Zelo em {os_.abertura or "?"}.', f'Equipamento: {_descr_item(it)}.',
                  f'Defeito: {os_.defeito or "(não informado)"}.']
        if it.com_quem:
            linhas.append(f'Com: {it.com_quem}{" (" + it.matricula + ")" if it.matricula else ""}.')
        if os_.fornecedor:
            linhas.append(f'Fornecedor: {os_.fornecedor}{" caso " + os_.caso if os_.caso else ""}.')
        return {'tipo': tipo, 'pessoa': it.matricula, 'item': it.codigo, 'os_id': os_.id, 'itens': [it.codigo],
                'assunto': f'Manutenção OS {os_.id}: {it.categoria or ""} {it.codigo} — {(os_.defeito or "")[:80]}'.strip(),
                'descricao': '\n'.join(linhas)}, ''
    it = db.session.get(Item, item or '')
    if not it:
        return None, 'Item não encontrado'
    if it.situacao != 'Pendente devolução':
        return None, f'{it.codigo} não está com devolução pendente (está {it.situacao})'
    linhas = [f'Devolução pedida e ainda não feita desde {it.desde or "?"}.', f'Equipamento: {_descr_item(it)}.',
              f'Com: {it.com_quem or "?"}{" (" + it.matricula + ")" if it.matricula else ""}.']
    return {'tipo': tipo, 'pessoa': it.matricula, 'item': it.codigo, 'os_id': None, 'itens': [it.codigo],
            'assunto': f'Devolução pendente: {it.categoria or ""} {it.codigo} com {it.com_quem or "?"}',
            'descricao': '\n'.join(linhas)}, ''


def em_aberto(tipo, pessoa=None, item=None, os_id=None):
    """A solicitação não cancelada e não resolvida que já existe para o mesmo assunto, se houver."""
    q = Solicitacao.query.filter(Solicitacao.tipo == tipo, Solicitacao.cancelada_em.is_(None))
    if tipo == 'recolhimento':
        q = q.filter(Solicitacao.pessoa == pessoa)
    elif tipo == 'manutencao':
        q = q.filter(Solicitacao.os_id == os_id)
    else:
        q = q.filter(Solicitacao.item == item)
    for s in q.order_by(Solicitacao.id.desc()):
        if not resolvida(s):
            return s
    return None


def criar(tipo, resp, pessoa=None, item=None, os_id=None):
    """Cria a solicitação (ou devolve a que já está aberta). Devolve (solicitação, nova?, erro)."""
    dados, erro = montar(tipo, pessoa, item, os_id)
    if erro:
        return None, False, erro
    ja = em_aberto(tipo, dados['pessoa'], dados['item'], dados['os_id'])
    if ja:
        return ja, False, ''
    s = Solicitacao(tipo=tipo, pessoa=dados['pessoa'], item=dados['item'], os_id=dados['os_id'],
                    itens=json.dumps(dados['itens']), assunto=dados['assunto'][:200], descricao=dados['descricao'],
                    prazo=(date.today() + timedelta(days=prazo_dias(tipo))).isoformat(),
                    criado_em=datetime.now().isoformat(timespec='seconds'), criado_por=resp)
    db.session.add(s)
    db.session.commit()
    return s, True, ''


def itens_de(s):
    try:
        return [c for c in json.loads(s.itens or '[]') if isinstance(c, str)]
    except ValueError:
        return []


def resolvida(s):
    """Sai do estado do Zelo agora, não de uma marca guardada."""
    if s.tipo == 'recolhimento':
        from app.desligamento import o_que_tem, total
        return not total(o_que_tem(s.pessoa))
    if s.tipo == 'manutencao':
        os_ = db.session.get(Manutencao, s.os_id) if s.os_id else None
        return not os_ or not os_.aberta
    it = db.session.get(Item, s.item) if s.item else None
    return not it or it.situacao != 'Pendente devolução'


def situacao(s, hoje=None):
    if s.cancelada_em:
        return 'Cancelada'
    if resolvida(s):
        return 'Resolvida'
    if s.prazo and s.prazo < (hoje or date.today().isoformat()):
        return 'Atrasada'
    return 'Aberta'


def cancelar(s, resp, motivo):
    if s.cancelada_em:
        return False, 'Já estava cancelada'
    if not (motivo or '').strip():
        return False, 'Diga o motivo do cancelamento'
    s.cancelada_em, s.cancelada_por = datetime.now().isoformat(timespec='seconds'), resp
    s.motivo_cancel = motivo.strip()[:200]
    db.session.commit()
    return True, f'S-{s.id} cancelada'


def atrasadas():
    hoje = date.today().isoformat()
    return sum(1 for s in Solicitacao.query.filter(Solicitacao.cancelada_em.is_(None), Solicitacao.prazo < hoje)
               if not resolvida(s))


def a_avisar():
    """Resolvidas no Zelo que têm chamado e ainda não ganharam a nota de resolução."""
    q = Solicitacao.query.filter(Solicitacao.chamado.isnot(None), Solicitacao.cancelada_em.is_(None),
                                 Solicitacao.nota_resolvida.isnot(True))
    return [s for s in q if resolvida(s)]
