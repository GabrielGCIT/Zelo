"""Espelho do lançamento: a conferência em tempo real do QUE vai acontecer e COM QUEM.

Não bloqueia nada (quem bloqueia é a Conferência, em app.lancamento). O espelho mostra, enquanto a
pessoa digita, quem é a pessoa encontrada (nome, matrícula, centro de custo, site, o que já está com
ela), qual é o aparelho (modelo, tag, situação, com quem está) e aponta os erros comuns de digitação:
homônimo, pessoa nova sem querer, pessoa que já tem um notebook, centro de custo vazio, item de outro
site, chamado já usado para outra pessoa, devolução do item errado, data muito para trás.
"""
import re
import unicodedata
from datetime import date

from app import db
from app.lancamento import ACOES, achar_item, achar_pessoa, so_digitos
from app.models import Item, Linha, Movimentacao, Pessoa

SAIDA = {'Entrega', 'Empréstimo'}


def _palavras(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().upper()
    return [w for w in re.sub(r'[^A-Z ]', ' ', s).split() if len(w) > 2 and w not in ('DOS', 'DAS', 'DES')]


def _cartao_pessoa(p):
    com_ela = Item.query.filter(Item.matricula == p.id, Item.situacao.in_(('Em uso', 'Emprestado', 'Reservada'))).all()
    linhas = Linha.query.filter(Linha.matricula == p.id, Linha.situacao == 'Em uso').all()
    return {'id': p.id, 'nome': p.nome, 'tipo': p.tipo, 'cc': p.cc, 'site': p.site, 'cargo': p.cargo, 'email': p.email,
            'situacao': p.situacao,
            'tem': [f'{i.categoria} {i.modelo or ""} ({i.codigo}, {i.situacao.lower()})'.replace('  ', ' ') for i in com_ela],
            'linhas': [ln.numero for ln in linhas], '_itens': com_ela}


def _cartao_item(it):
    return {'codigo': it.codigo, 'categoria': it.categoria, 'modelo': it.modelo, 'fabricante': it.fabricante, 'tag': it.tag,
            'imei': it.imei1, 'site': it.site, 'situacao': it.situacao, 'com_quem': it.com_quem, 'matricula': it.matricula,
            'finalidade': it.finalidade, 'linha': it.linha_atual}


def parecidos(nome, excluir=None, limite=4):
    """Pessoas ativas com pelo menos 2 palavras do nome em comum (primeiro nome incluído)."""
    ws = _palavras(nome)
    if len(ws) < 2:
        return []
    cand = Pessoa.query.filter(Pessoa.situacao != 'Desligado', Pessoa.nome.ilike(f'%{ws[0]}%')).limit(300).all()
    out = []
    for p in cand:
        if p.id == excluir:
            continue
        pw = _palavras(p.nome)
        if pw and pw[0] == ws[0] and len(set(ws) & set(pw)) >= 2:
            out.append(p)
    return out[:limite]


def espelho(d, hoje=None):
    """d: uma linha da grade. Devolve {'item', 'pessoa', 'linha', 'nova', 'resumo', 'atencao': [...]}."""
    d = {k: str(v or '').strip() for k, v in (d or {}).items()}
    hoje = hoje or date.today().isoformat()
    acao = d.get('acao', '')
    tipo = ACOES[acao][0] if acao in ACOES else ''
    precisa = ACOES[acao][3] if acao in ACOES else False
    at = []
    out = {'item': None, 'pessoa': None, 'linha': None, 'nova': None, 'chamado': None, 'resumo': '', 'atencao': at}

    it = achar_item(d['item']) if d.get('item') else None
    if it:
        out['item'] = _cartao_item(it)
    ln = None
    if d.get('linha') and d['linha'].lower() != 'fica':
        ln = db.session.get(Linha, so_digitos(d['linha']))
        if ln:
            out['linha'] = {'numero': ln.numero, 'operadora': ln.operadora, 'situacao': ln.situacao, 'com_quem': ln.com_quem,
                            'aparelho': ln.aparelho, 'cc': ln.cc}

    p = None
    if precisa and d.get('para'):
        p, nova, _erro = achar_pessoa(d['para'])
        if p:
            out['pessoa'] = _cartao_pessoa(p)
        elif nova:
            out['nova'] = nova
            sim = parecidos(nova['nome'])
            at.append('Pessoa NOVA será cadastrada (' + ('CLT, matrícula ' + nova['id'] if nova.get('id') else 'terceiro') + ')'
                      + (': confira se não é ' + '; '.join(f'{x.nome} · {x.id}' for x in sim) if sim else
                         '. Confira a grafia: não achei ninguém parecido'))
    elif not precisa and it and it.matricula:
        p = db.session.get(Pessoa, it.matricula)
        if p:
            out['pessoa'] = _cartao_pessoa(p)

    # ------------------------------------------------ pessoa
    if p and precisa:
        cp = out['pessoa']
        if p.situacao and p.situacao != 'Ativo':
            at.append(f'{p.nome} está como {p.situacao} em Pessoas')
        if not p.cc:
            at.append(f'{p.nome} está sem centro de custo em Pessoas: o lançamento vai sem CC')
        sim = parecidos(p.nome, excluir=p.id)
        if sim:
            at.append('Há nomes parecidos: ' + '; '.join(f'{x.nome} · {x.id}' + (f' (CC {x.cc})' if x.cc else '') for x in sim)
                      + f'. Confirme que é a matrícula {p.id}')
        if it and tipo in SAIDA:
            mesma = [i for i in cp['_itens'] if i.categoria == it.categoria and i.codigo != it.codigo]
            if mesma and acao != 'Renovar empréstimo':
                at.append(f'{p.nome} já tem {len(mesma)} {it.categoria.lower()}(s): ' + ', '.join(f'{i.codigo} {i.modelo or ""}'.strip() for i in mesma)
                          + '. Se é troca, lance a devolução do antigo')
            if it.site and p.site and it.site not in ('EC', p.site):
                at.append(f'O item está cadastrado no site {it.site} e a pessoa é de {p.site}')
        if ln and tipo in SAIDA and ln.matricula and ln.matricula != p.id and ln.situacao == 'Em uso':
            at.append(f'A linha {ln.numero} está com {ln.com_quem}')
        if acao == 'Transferir para outra pessoa' and it and it.matricula == p.id:
            at.append('O item já está com essa pessoa')

    # ------------------------------------------------ item
    if it:
        if acao in ('Devolver', 'Pedir devolução', 'Devolver empréstimo') and it.com_quem:
            at.append(f'Quem devolve: {it.com_quem} ({it.matricula}). Confira a etiqueta do aparelho na mão: {it.codigo}'
                      + (f' / tag {it.tag}' if it.tag else ''))
        if tipo in SAIDA and it.categoria in ('Celular', 'Tablet') and ln and ln.aparelho and ln.aparelho != it.codigo:
            at.append(f'A linha {ln.numero} está registrada no aparelho {ln.aparelho}, não no {it.codigo}')
        if it.kit == 'A conferir' and tipo in SAIDA and it.categoria == 'Notebook':
            at.append('Notebook sem preparação registrada (kit a conferir): confira fonte, mouse e teclado antes de entregar')

    # ------------------------------------------------ chamado no Service Desk
    from app import servicedesk as sd
    if d.get('chamado') and sd.configurado():
        c = sd.chamado(d['chamado'])
        out['chamado'] = c
        if c and c.get('inexistente'):
            at.append(f'O chamado {d["chamado"]} não existe no Service Desk')
        elif c and c.get('erro'):
            at.append('Não consegui consultar o chamado no Service Desk agora (o lançamento grava mesmo assim)')
        elif c:
            if c['status'].lower() in ('closed', 'fechado', 'cancelled', 'cancelado'):
                at.append(f'O chamado {c["id"]} está {c["status"]}')
            alvo = p if (p and precisa) else None
            if alvo and c['solicitante']:
                mesmo = (alvo.email and c['email'] and alvo.email.lower() == c['email'].lower()) or \
                        (alvo.user and c['login'] and alvo.user.lower() == c['login'].lower()) or \
                        len(set(_palavras(alvo.nome)) & set(_palavras(c['solicitante']))) >= 2
                if not mesmo:
                    at.append(f'O chamado {c["id"]} foi aberto por {c["solicitante"]}, e quem recebe é {alvo.nome}. '
                              'Confira (pode ter sido aberto pelo gestor)')

    # ------------------------------------------------ chamado e data
    if d.get('chamado'):
        q = Movimentacao.query.filter(Movimentacao.chamado == d['chamado'])
        pid = p.id if p else (out['nova'] or {}).get('id')
        outros = [m for m in q.limit(20) if m.matricula and pid and m.matricula != pid]
        if outros:
            m = outros[0]
            at.append(f'O chamado {d["chamado"]} já foi usado no Nº {m.id} para {m.nome}')
    if d.get('data'):
        try:
            dias = (date.fromisoformat(hoje) - date.fromisoformat(d['data'])).days
            if dias > 7:
                at.append(f'Data de {dias} dias atrás: lançamento retroativo')
        except ValueError:
            pass

    # ------------------------------------------------ resumo em uma frase
    quem = (out['pessoa'] or {}).get('nome') or (out['nova'] or {}).get('nome')
    cc = (out['pessoa'] or {}).get('cc')
    oque = f'{it.categoria} {it.modelo or ""} {it.codigo}'.replace('  ', ' ') if it else (f'linha {ln.numero}' if ln else '')
    if acao and oque:
        if precisa and quem:
            out['resumo'] = f'{acao}: {oque} → {quem}' + (f' (CC {cc})' if cc else ' (sem CC)')
        elif not precisa:
            out['resumo'] = f'{acao}: {oque}' + (f' (hoje com {it.com_quem})' if it and it.com_quem else '')
    if out['pessoa']:
        out['pessoa'].pop('_itens', None)
    return out
