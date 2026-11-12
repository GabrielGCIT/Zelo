"""Trazer do Service Desk o que ele sabe melhor — hoje, o e-mail das pessoas.

Por que isto existe: o Zelo precisa do e-mail para achar a pessoa como usuário no Service Desk
na hora de atribuir o ativo. Sem e-mail, ele tenta pelo nome exato e só aceita se for único — com
homônimo ou grafia diferente, o ativo não é atribuído e o envio fica com erro na fila. Hoje a
imensa maioria das pessoas do Zelo está sem e-mail, então isso é o gargalo real da integração.

A base do Service Desk vem do AD, que não é confiável em cargo, centro de custo e matrícula
(decisão do Gabriel). Por isso só nome, e-mail e login atravessam, e nada mais.

O cuidado que faz a diferença: o Zelo tem matrícula como chave, o Service Desk não tem. O
casamento é por e-mail e, na falta dele, por nome exato — e SÓ quando esse nome é único dos dois
lados. Nome repetido não vira palpite: vira uma escolha na tela. E nada é sobrescrito: o e-mail só
entra onde está vazio; onde já existe e diverge, o Zelo mostra os dois e espera você decidir.
"""
import re
import unicodedata

from app import db
from app.models import Pessoa

MAX_PAGINAS = 40                  # 40 × 100 = 4.000 usuários; acima disso o Zelo avisa e para
POR_PAGINA = 100
# cada usuário do SD cai em um destes casos
CASOS = {
    'completa': ('Completa o e-mail', 'O Zelo já tem essa pessoa e está sem e-mail. É o que destrava a atribuição de ativo.'),
    'confere': ('Já confere', 'Mesmo e-mail dos dois lados. Nada a fazer.'),
    'conflito': ('E-mail diferente', 'A pessoa já tem outro e-mail no Zelo. Escolha qual vale.'),
    'ambiguo': ('Nome repetido', 'Há mais de uma pessoa com esse nome no Zelo. Diga qual é, ou deixe de fora.'),
    'novo': ('Não está no Zelo', 'Só traga quem realmente recebe equipamento — o cadastro do AD tem muita gente que não interessa.'),
}


def _chave(nome):
    """Nome comparável: sem acento, sem pontuação, maiúsculo e sem espaço sobrando."""
    s = unicodedata.normalize('NFKD', str(nome or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Za-z0-9 ]', ' ', s)).strip().upper()


def _mail(v):
    return str(v or '').strip().lower()


def baixar(limite_paginas=MAX_PAGINAS):
    """Todos os usuários do Service Desk. Devolve (lista, truncou, erro)."""
    from app import servicedesk as sd
    if not sd.configurado():
        return [], False, 'A integração com o Service Desk está desligada ou sem chave.'
    saida, inicio = [], 1
    try:
        for _p in range(limite_paginas):
            pagina, mais = sd.listar_usuarios(inicio, POR_PAGINA)
            saida += pagina
            if not mais or not pagina:
                return saida, False, ''
            inicio += POR_PAGINA
        return saida, True, ''
    except sd.ErroSD as e:
        return saida, False, str(e)


def conferir(usuarios):
    """Casa os usuários do Service Desk com o cadastro do Zelo. Devolve (linhas, resumo)."""
    pessoas = Pessoa.query.all()
    por_email, por_nome = {}, {}
    for p in pessoas:
        if p.email:
            por_email.setdefault(_mail(p.email), []).append(p)
        por_nome.setdefault(_chave(p.nome), []).append(p)

    linhas, vistos = [], set()
    for u in usuarios:
        nome, email = (u.get('name') or '').strip(), _mail(u.get('email_id'))
        if not nome:
            continue
        ch = _chave(nome)
        if (ch, email) in vistos:                     # o SD repete usuário entre páginas às vezes
            continue
        vistos.add((ch, email))
        cand = por_email.get(email) if email else None
        if cand:
            p = cand[0]
            caso = 'confere'
        else:
            mesmos = por_nome.get(ch) or []
            if len(mesmos) == 1:
                p = mesmos[0]
                caso = 'conflito' if (p.email and _mail(p.email) != email) else ('completa' if email else 'confere')
            elif len(mesmos) > 1:
                p, caso = None, 'ambiguo'
            else:
                p, caso = None, 'novo'
        linhas.append({
            'nome': nome, 'email': email, 'login': (u.get('login_name') or '').strip(),
            'ativo_sd': u.get('is_active') is not False, 'caso': caso,
            'pessoa': p.id if p else '', 'pessoa_nome': p.nome if p else '',
            'pessoa_email': (p.email or '') if p else '',
            'pessoa_situacao': (p.situacao or '') if p else '',
            'candidatos': [{'id': x.id, 'nome': x.nome, 'cc': x.cc or '', 'site': x.site or '',
                            'situacao': x.situacao or ''} for x in (por_nome.get(ch) or [])] if caso == 'ambiguo' else [],
        })
    resumo = {k: sum(1 for l in linhas if l['caso'] == k) for k in CASOS}
    resumo['total'] = len(linhas)
    resumo['sem_email_no_zelo'] = Pessoa.query.filter(Pessoa.situacao == 'Ativo',
                                                      (Pessoa.email.is_(None)) | (Pessoa.email == '')).count()
    return linhas, resumo


def aplicar(escolhas, quem):
    """escolhas: [{'pessoa': id, 'email', 'login', 'nome', 'criar': bool}]. Devolve (n, mensagem, detalhes)."""
    from app.auth import registrar_log
    feitos, erros = [], []
    for e in escolhas:
        email, login, nome = _mail(e.get('email')), (e.get('login') or '').strip(), (e.get('nome') or '').strip()
        pid = (e.get('pessoa') or '').strip()
        if e.get('criar'):
            if not nome:
                erros.append('Sem nome: não dá para cadastrar')
                continue
            novo = pid or _id_livre(nome)
            if db.session.get(Pessoa, novo):
                erros.append(f'{nome}: a matrícula {novo} já existe')
                continue
            db.session.add(Pessoa(id=novo, nome=nome, email=email or None, user=login or None,
                                  tipo='A confirmar', situacao='Ativo',
                                  obs=f'Cadastrado a partir do Service Desk por {quem}'))
            feitos.append(f'{nome}: cadastrado como {novo}')
            continue
        p = db.session.get(Pessoa, pid) if pid else None
        if not p:
            erros.append(f'{nome or pid}: não encontrei essa pessoa no Zelo')
            continue
        mudou = []
        if email and _mail(p.email) != email:
            mudou.append(f'e-mail {p.email or "(vazio)"} → {email}')
            p.email = email
        # o login do Zelo veio da planilha e pode ser o certo: só preenche onde está vazio. Trocar
        # um login que já existe é edição de cadastro, feita na ficha da pessoa, não por importação.
        if login and not (p.user or '').strip():
            mudou.append(f'usuário → {login}')
            p.user = login
        if mudou:
            feitos.append(f'{p.nome}: ' + '; '.join(mudou))
        else:
            erros.append(f'{p.nome}: nada a mudar')
    db.session.commit()
    if feitos:
        registrar_log('importação do Service Desk', f'{len(feitos)} pessoa(s) atualizada(s)/cadastrada(s)')
    msg = f'{len(feitos)} pessoa(s) atualizada(s)'
    if erros:
        msg += f'; {len(erros)} sem efeito'
    return len(feitos), msg, feitos + erros


def _id_livre(nome):
    """Matrícula provisória para quem veio do Service Desk e ainda não tem a de verdade."""
    base = 'SD-' + (_chave(nome).replace(' ', '')[:10] or 'PESSOA')
    if not db.session.get(Pessoa, base):
        return base
    for i in range(2, 100):
        if not db.session.get(Pessoa, f'{base}-{i}'):
            return f'{base}-{i}'
    return f'{base}-{db.session.query(Pessoa).count()}'
