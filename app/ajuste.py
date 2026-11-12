"""Ajuste de cadastro: corrigir o que a planilha trouxe errado, sem inventar uma movimentação.

O Histórico ganha um lançamento do tipo "Ajuste" dizendo como a coisa REALMENTE está — quem está com
o item, em que situação ele está e em que aparelho a linha está. Fica registrado quem ajustou e por quê.
"""
from datetime import date, datetime

from app import db
from app.lancamento import achar_pessoa, so_digitos
from app.models import COM_PESSOA, SITUACOES, SITUACOES_LINHA, Item, Linha, Movimentacao, Pessoa
from app.regras import tocar

# Situações que o ajuste pode declarar (as que a vida real produz; o resto vem de lançamento de verdade)
SIT_AJUSTE = ['Em uso', 'Emprestado', 'Em estoque', 'Reservada', 'Pendente devolução', 'Em trânsito para o EC',
              'Em transferência', 'A localizar', 'Aguardando baixa', 'Baixada']
MOTIVOS_AJUSTE = ['Cadastro errado na planilha', 'Item conferido fisicamente', 'Linha conferida na operadora',
                  'Troca de responsável não lançada', 'Devolução não lançada', 'Entrega não lançada', 'Outro']


def _nome(p):
    return p.nome if isinstance(p, Pessoa) else (p or {}).get('nome')


def _id(p):
    return p.id if isinstance(p, Pessoa) else (p or {}).get('id')


def atual(it, ln):
    """Como o Zelo acha que está hoje."""
    d = {}
    if it:
        d['situacao'] = it.situacao
        d['quem'] = it.com_quem or ''
        d['matricula'] = it.matricula or ''
        d['linha'] = it.linha_atual or ''
    if ln:
        d['sit_linha'] = ln.situacao
        d['linha_quem'] = ln.com_quem or ''
        d['linha_aparelho'] = ln.aparelho or ''
    return d


def conferir(it, ln, d):
    """Devolve (erro, mudancas). mudancas = lista de 'campo: antes → depois'."""
    if not it and not ln:
        return 'Informe o item ou a linha', []
    sit = (d.get('situacao') or '').strip()
    validas = SIT_AJUSTE if it else SITUACOES_LINHA
    if not sit:
        return 'Escolha como a situação realmente está', []
    if sit not in validas:
        return 'Situação inválida para um ajuste', []
    if not (d.get('motivo') or '').strip():
        return 'Diga por que está ajustando (fica no Histórico)', []
    pessoa, nova, erro = (None, None, None)
    precisa = (sit in COM_PESSOA or sit == 'Emprestado') if it else (sit == 'Em uso')
    if (d.get('para') or '').strip():
        pessoa, nova, erro = achar_pessoa(d['para'])
        if erro:
            return erro, []
    if precisa and not (pessoa or nova):
        return f'"{sit}" é com alguém: informe com quem o item está de verdade', []
    if not precisa and (pessoa or nova):
        return f'"{sit}" não fica com ninguém: deixe "Com quem" vazio', []
    data = (d.get('data') or '').strip() or date.today().isoformat()
    try:
        if data > date.today().isoformat():
            return 'Data no futuro', []
    except TypeError:
        return 'Data inválida', []
    mud = []
    a = atual(it, ln)
    if it:
        if a['situacao'] != sit:
            mud.append(f'situação: {a["situacao"]} → {sit}')
        novo_quem = _nome(pessoa or nova) or ''
        if (a['quem'] or '') != novo_quem:
            mud.append(f'com quem: {a["quem"] or "ninguém"} → {novo_quem or "ninguém"}')
        if ln and a.get('linha', '') != ln.numero:
            mud.append(f'linha no aparelho: {a.get("linha") or "nenhuma"} → {ln.numero}')
    elif ln:
        if a['sit_linha'] != sit:
            mud.append(f'situação da linha: {a["sit_linha"]} → {sit}')
        novo_quem = _nome(pessoa or nova) or ''
        if (a['linha_quem'] or '') != novo_quem:
            mud.append(f'com quem: {a["linha_quem"] or "ninguém"} → {novo_quem or "ninguém"}')
    if not mud:
        return 'Nada mudaria: o cadastro já está assim', []
    return None, mud


def gravar(it, ln, d, resp):
    """Grava o ajuste. Devolve (ok, mensagem, movimentacao)."""
    erro, mud = conferir(it, ln, d)
    if erro:
        return False, erro, None
    sit = d['situacao'].strip()
    pessoa, nova, _e = achar_pessoa(d['para']) if (d.get('para') or '').strip() else (None, None, None)
    if nova:
        from app.lancamento import proximo_id_pessoa
        nova['id'] = nova['id'] or proximo_id_pessoa('T')
        db.session.add(Pessoa(situacao='Ativo', **nova))
    alvo = pessoa or nova
    m = Movimentacao(data=(d.get('data') or '').strip() or date.today().isoformat(), tipo='Ajuste',
                     item=it.codigo if it else None, linha=ln.numero if ln else None, etapa=sit,
                     matricula=_id(alvo), nome=_nome(alvo), cc=(pessoa.cc if isinstance(pessoa, Pessoa) else None),
                     motivo=d['motivo'].strip(), resp=resp,
                     obs=('; '.join(mud) + (' · ' + d['obs'].strip() if (d.get('obs') or '').strip() else ''))[:500],
                     reg_em=datetime.now().isoformat(timespec='seconds'))
    db.session.add(m)
    if it and ln:
        it.linha_atual = ln.numero      # campo de cadastro: o ajuste também corrige aqui
    db.session.flush()
    tocar([it.codigo if it else None], [ln.numero if ln else None])
    db.session.commit()
    return True, 'Ajuste registrado: ' + '; '.join(mud), m


def achar(codigo, numero):
    from app.routes.consulta import achar_item
    it = achar_item(codigo) if codigo else None
    n = so_digitos(numero or '')
    ln = db.session.get(Linha, n) if len(n) == 11 else None
    return it, ln
