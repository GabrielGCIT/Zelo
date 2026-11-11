"""Acompanhar: entregas em andamento, preparação dos notebooks devolvidos, links de termo e correções.

Igual à aba Acompanhar da planilha:
- a etapa de uma entrega/empréstimo avança NO PRÓPRIO lançamento (não cria outro);
- cancelar uma reserva devolve o item ao estoque e o kit (mouse/teclado) ao saldo do EC;
- a preparação grava um lançamento "Preparação" (parcial) ou "Liberação" (tudo feito → estoque, kit completo);
  o que não veio na devolução (fonte, mouse, teclado) sai do estoque do EC na liberação.
"""
from datetime import date

from app import db
from app.lancamento import escolher_kit, saldo
from app.models import Item, MovConsumivel, Movimentacao
from app.regras import tocar

ETAPAS_ORDEM = ['Reservado', 'Termo assinado', 'Chamado aberto', 'Entregue']
PASSOS = [('preventiva', 'Preventiva'), ('formatado', 'Formatado'), ('fonte', 'Fonte'), ('mouse', 'Mouse'),
          ('teclado', 'Teclado'), ('embalado', 'Embalado')]


def corrigir(mov, dados, resp):
    """Corrige/avança um lançamento de entrega ou empréstimo. Devolve (ok, mensagem)."""
    if mov.tipo not in ('Entrega', 'Empréstimo'):
        campos = {k: dados.get(k) for k in ('chamado', 'link', 'tecnico') if dados.get(k)}
        if not campos:
            return False, 'Para este tipo de lançamento só dá para corrigir chamado, técnico e link'
        for k, v in campos.items():
            setattr(mov, k, v)
        db.session.commit()
        return True, f'Nº {mov.id} corrigido: ' + ', '.join(campos)
    nova = dados.get('etapa') or ''
    hoje = date.today().isoformat()
    if nova and mov.etapa == 'Entregue' and nova != 'Cancelado':
        return False, 'Já está Entregue: deixe Nova etapa vazia (só corrige termo, datas, chamado, link)'
    if nova and mov.etapa == 'Cancelado':
        return False, 'Lançamento cancelado: faça um lançamento novo'
    if nova and nova not in ETAPAS_ORDEM + ['Cancelado']:
        return False, 'Etapa inválida'
    if nova == 'Cancelado':
        it = db.session.get(Item, mov.item) if mov.item else None
        if mov.etapa == 'Entregue' or (it and it.ultima_mov_id != mov.id):
            return False, 'Só dá para cancelar uma reserva que ainda está em andamento (já entregue: lance Devolver)'
    if not any(dados.get(k) for k in ('etapa', 'data_ass', 'chamado', 'data_ent', 'tecnico', 'link')):
        return False, 'Escolha a nova etapa (ou, para corrigir, preencha só a data ou o chamado certo)'
    for k in ('data_ass', 'data_ent'):
        if dados.get(k) and dados[k] > hoje:
            return False, 'Data no futuro'
    mudou = []
    if nova:
        if nova == 'Termo assinado' and mov.termo != 'Assinado' and mov.termo != 'Dispensado':
            mov.termo = 'Assinado'
            mov.data_ass = dados.get('data_ass') or mov.data_ass or hoje
            mudou.append('termo assinado')
        if nova == 'Entregue':
            mov.data_ent = dados.get('data_ent') or hoje
        if nova == 'Cancelado':
            # o kit reservado volta ao saldo do EC
            for mc in MovConsumivel.query.filter_by(mov_id=mov.id, movimento='Saída').all():
                db.session.add(MovConsumivel(data=hoje, consumivel=mc.consumivel, site='EC', movimento='Entrada', qtd=mc.qtd,
                                             destino=mc.destino, resp=resp, mov_id=mov.id,
                                             obs=f'Volta do kit: entrega Nº {mov.id} cancelada'))
        mov.etapa = nova
        mudou.append(f'etapa {nova}')
    elif dados.get('data_ass') and mov.termo != 'Assinado':
        mov.termo, mov.data_ass = 'Assinado', dados['data_ass']
        mudou.append('termo assinado')
    for k in ('data_ass', 'chamado', 'data_ent', 'tecnico', 'link'):
        if dados.get(k) and getattr(mov, k) != dados[k]:
            setattr(mov, k, dados[k])
            mudou.append(k.replace('_', ' '))
    if dados.get('termo') in ('Pendente', 'Assinado', 'Dispensado') and mov.termo != dados['termo']:
        mov.termo = dados['termo']
        mudou.append(f'termo {mov.termo}')
    tocar([mov.item], [mov.linha])
    db.session.commit()
    return True, f'Nº {mov.id}: ' + ', '.join(dict.fromkeys(mudou))


def ultima_preparacao(item):
    """Última Preparação depois da devolução (para continuar de onde parou) e a própria devolução."""
    movs = Movimentacao.query.filter_by(item=item.codigo).order_by(Movimentacao.id.desc()).all()
    prep, dev = None, None
    for m in movs:
        if m.tipo == 'Preparação' and prep is None and dev is None:
            prep = m
        if m.tipo == 'Devolução':
            dev = m
            break
    return prep, dev


def marcas_de(m):
    """As marcas de preparação ficam na Observação ('Preparação: Preventiva ✓ · Fonte ✓')."""
    o = (m.obs or '') if m else ''
    return {k: (f'{rot} ✓' in o) for k, rot in PASSOS}


def preparar(item, dados, resp):
    """Grava a chegada e a preparação. dados: veio_fonte/veio_mouse/veio_teclado (Sim/Não), estado, as 6 marcas,
    preparado_por e liberar ('Sim' = volta ao estoque mesmo sem todas as marcas).

    Enquanto não libera, a mesma linha de Preparação é atualizada (o quadro salva a cada clique, sem criar uma
    linha no Histórico por marcação). Nada aqui é obrigatório: o que não foi informado fica em branco."""
    if item.situacao not in ('Devolvido', 'Em preparação'):
        return False, f'O item está {item.situacao}: não está na preparação'
    prep, dev = ultima_preparacao(item)
    base = prep or dev
    for k, col in (('veio_fonte', 'fonte_dev'), ('veio_mouse', 'mouse_dev'), ('veio_teclado', 'teclado_dev'), ('estado', 'estado')):
        if not dados.get(k):
            dados[k] = (getattr(base, col) if base else None) or None
    dados['preparado_por'] = dados.get('preparado_por') or resp
    marcas = {k: dados.get(k) == 'Sim' for k, _r in PASSOS}
    tudo = all(marcas.values()) or dados.get('liberar') == 'Sim'
    pulou = [rot for k, rot in PASSOS if not marcas[k]] if tudo else []
    hoje = date.today().isoformat()
    obs = 'Preparação: ' + ' · '.join(filter(None, [
        'chegou com avaria' if dados['estado'] == 'Com avaria' else '',
        *[f'{rot} ✓' for k, rot in PASSOS if marcas[k]],
        ('liberado sem: ' + ', '.join(pulou)) if pulou else '']))
    kit = []
    if tudo:
        # só completa do estoque o que foi dito que NÃO veio e que a pessoa marcou como conferido
        falta = []
        if dados['veio_fonte'] == 'Não' and marcas['fonte']:
            n = f'Fonte de notebook – {item.fabricante or "Dell"}'
            if saldo(n) <= 0:
                return False, f'Sem saldo de {n} no EC para completar o kit (desmarque Fonte para liberar sem)'
            falta.append(n)
        km, erro = escolher_kit(item.fabricante, dados['veio_mouse'] == 'Não' and marcas['mouse'],
                                dados['veio_teclado'] == 'Não' and marcas['teclado'], {})
        if erro:
            return False, erro + ' para completar o kit (desmarque Mouse/Teclado para liberar sem)'
        kit = falta + km
    campos = dict(obs=obs, fonte_dev=dados['veio_fonte'], mouse_dev=dados['veio_mouse'], teclado_dev=dados['veio_teclado'],
                  estado=dados['estado'], receb_por=dados['preparado_por'])
    if not tudo and prep:
        for k, v in campos.items():
            setattr(prep, k, v)
        db.session.commit()
        return True, 'Em preparação (salvo)'
    m = Movimentacao(data=hoje, tipo='Liberação' if tudo else 'Preparação', item=item.codigo, resp=resp,
                     acess='; '.join(kit) if kit else None, **campos)
    db.session.add(m)
    db.session.flush()
    for k in kit:
        db.session.add(MovConsumivel(data=hoje, consumivel=k, site='EC', movimento='Saída', qtd=1, destino=item.codigo,
                                     resp=resp, mov_id=m.id, obs=f'Completar kit do {item.codigo} (Nº {m.id})'))
    tocar([item.codigo])
    db.session.commit()
    if tudo:
        return True, ('Volta ao estoque' + (' (sem: ' + ', '.join(pulou) + ')' if pulou else ' com kit completo')
                      + (f' · baixa EC: {"; ".join(kit)}' if kit else ''))
    return True, 'Em preparação (salvo)'
