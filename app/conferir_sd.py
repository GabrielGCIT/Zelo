"""Ativos: o que o Service Desk tem, o que o Zelo tem, e onde os dois discordam.

Duas perguntas que na prática são a mesma busca, então moram na mesma tela:

1. o que existe lá e não existe aqui (importar), e o que o SD sabe e o cadastro do Zelo não tem;
2. onde os dois discordam — quem está com a máquina, em que estado ela está, qual é a service tag.

A segunda é a que mais vale e ninguém faz hoje: é o inventário. Por isso esta tela não corrige
nada sozinha. Ela mostra a divergência e deixa você dizer quem está certo, porque a regra de dono
dos campos não decide tudo: o SD descreve bem a máquina (hostname, serial, modelo), mas quem está
com ela e em que estado é o Zelo que sabe, e cada caso tem exceção.

Regra de dono acordada com o Gabriel:
- Service Desk manda em: hostname, service tag/serial, modelo e fabricante;
- Zelo manda em: com quem está, situação, plaqueta, CC, site, finalidade, contrato, garantia.
"""
import re
import unicodedata

from app import db
from app.models import Item

MAX_PAGINAS = 60                  # 60 × 100 = 6.000 ativos
POR_PAGINA = 100

GRUPOS = {
    'novo': ('Falta no Zelo', 'Existe no Service Desk e não aqui. Traga só o que é equipamento de verdade.'),
    'completa': ('Completa o cadastro', 'O Zelo já tem o item e está sem algum dado que o SD tem. Preenche só o que está vazio.'),
    'quem': ('Quem está com ele difere', 'O Service Desk diz uma pessoa e o Zelo diz outra. Um dos dois está desatualizado.'),
    'estado': ('Situação difere', 'Em uso de um lado e em estoque do outro, ou parecido.'),
    'divergente': ('Dado diferente', 'Service tag ou modelo diferentes entre os dois. Confira antes de mexer.'),
    'repetido': ('Cadastro repetido no Zelo', 'O mesmo hostname, service tag ou plaqueta está em mais de um item aqui. '
                 'Resolva a duplicidade antes: enquanto houver duas, o Zelo não tem como saber qual é a do Service Desk.'),
    'confere': ('Confere', 'Nada a fazer.'),
    'so_zelo': ('Só no Zelo', 'Máquina com hostname aqui que o Service Desk não conhece: ou está sem agente, ou falta cadastrar lá. Monitor, celular e acessório não entram nesta conta — nunca estiveram no SD.'),
}
# situação do Zelo → estado equivalente no Service Desk
EQUIVALE = {
    'Em uso': 'In Use', 'Emprestado': 'In Use', 'Em estoque': 'In Store', 'Reservada': 'In Store',
    'Devolvido': 'In Store', 'Em preparação': 'In Store', 'Manutenção': 'In Repair', 'Baixada': 'Expired',
}


def _up(v):
    return re.sub(r'\s+', '', str(v or '')).upper()


def _chave_nome(v):
    s = unicodedata.normalize('NFKD', str(v or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Za-z0-9 ]', ' ', s)).strip().upper()


def _campo(a, *nomes):
    """O primeiro campo que existir, aceitando objeto {'name': ...}. Os nomes mudam por build."""
    for n in nomes:
        v = a.get(n)
        if isinstance(v, dict):
            v = v.get('name') or v.get('id')
        if v not in (None, '', []):
            return str(v).strip()
    return ''


def do_sd(a):
    """O que o Zelo entende de um ativo do Service Desk."""
    return {
        'id': _campo(a, 'id'),
        'hostname': _campo(a, 'name'),
        'tag': _campo(a, 'serial_number', 'service_tag'),
        'plaqueta': _campo(a, 'asset_tag', 'barcode'),
        'modelo': _campo(a, 'product'),
        'tipo': _campo(a, 'product_type'),
        'estado': _campo(a, 'state'),
        'usuario': _campo(a, 'user'),
        'site': _campo(a, 'site'),
        'garantia': _campo(a, 'warranty_expiry', 'expiry_date'),
        'fornecedor': _campo(a, 'vendor'),
    }


def baixar(limite_paginas=MAX_PAGINAS):
    """Todos os ativos do Service Desk, já traduzidos. Devolve (lista, truncou, erro)."""
    from app import servicedesk as sd
    if not sd.configurado():
        return [], False, 'A integração com o Service Desk está desligada ou sem chave.'
    saida, inicio = [], 1
    try:
        for _p in range(limite_paginas):
            pagina, mais = sd.listar_ativos(inicio, POR_PAGINA)
            saida += [do_sd(a) for a in pagina]
            if not mais or not pagina:
                return saida, False, ''
            inicio += POR_PAGINA
        return saida, True, ''
    except sd.ErroSD as e:
        return saida, False, str(e)


def _indices():
    itens = Item.query.all()
    por_host, por_tag, por_plaq = {}, {}, {}
    for i in itens:
        if i.hostname:
            por_host.setdefault(_up(i.hostname), []).append(i)
        if i.tag:
            por_tag.setdefault(_up(i.tag), []).append(i)
        if i.plaqueta:
            por_plaq.setdefault(_up(i.plaqueta), []).append(i)
    return itens, por_host, por_tag, por_plaq


def _casar(s, por_host, por_tag, por_plaq):
    """Acha o item do Zelo: hostname, depois service tag, depois plaqueta.

    Devolve (item, repetidos). Quando a chave aponta para mais de um item do Zelo, não escolhe:
    isso é cadastro duplicado aqui dentro, e a tela precisa dizer isso em vez de inventar um par.
    """
    for valor, indice in ((s['hostname'], por_host), (s['tag'], por_tag), (s['plaqueta'], por_plaq)):
        achados = indice.get(_up(valor)) if valor else None
        if not achados:
            continue
        if len(achados) == 1:
            return achados[0], []
        return None, achados
    return None, []


# campo do Zelo ← campo do SD, só onde o SD é dono
DO_SD = [('hostname', 'hostname'), ('tag', 'tag'), ('modelo', 'modelo')]


def conferir(ativos):
    """Compara a lista do Service Desk com o parque do Zelo. Devolve (linhas, resumo)."""
    itens, por_host, por_tag, por_plaq = _indices()
    linhas, casados = [], set()
    for s in ativos:
        if not s['hostname'] and not s['tag']:
            continue
        it, repetidos = _casar(s, por_host, por_tag, por_plaq)
        if repetidos:
            for x in repetidos:
                casados.add(x.codigo)
            linhas.append(dict(sd=s, item=None, caso='repetido', faltam=[], difere=[], campos={},
                               repetidos=[_item(x) for x in repetidos]))
            continue
        if not it:
            linhas.append(dict(sd=s, item=None, caso='novo', faltam=[], difere=[], campos={}))
            continue
        casados.add(it.codigo)
        faltam = [(campo, s[de]) for campo, de in DO_SD if s[de] and not (getattr(it, campo) or '').strip()]
        difere = [(campo, (getattr(it, campo) or ''), s[de]) for campo, de in DO_SD
                  if s[de] and (getattr(it, campo) or '').strip() and _up(getattr(it, campo)) != _up(s[de])]
        caso = 'confere'
        if _quem_difere(it, s):
            caso = 'quem'
        elif _estado_difere(it, s):
            caso = 'estado'
        elif difere:
            caso = 'divergente'
        elif faltam:
            caso = 'completa'
        linhas.append(dict(sd=s, item=_item(it), caso=caso, faltam=faltam, difere=difere,
                           # o que a tela manda de volta se a linha for marcada
                           campos=(dict(faltam) if caso == 'completa' else {c: novo for c, _a, novo in difere}),
                           quem_zelo=(it.com_quem or ''), quem_sd=s['usuario'],
                           estado_zelo=(it.situacao or ''), estado_sd=s['estado']))
    # só entra aqui quem tem hostname: é máquina com agente, que o Service Desk deveria conhecer.
    # Monitor, celular e acessório nunca estiveram lá, e listá-los faria a tela virar ruído.
    for it in itens:
        if it.codigo not in casados and (it.hostname or '').strip() and it.situacao != 'Baixada':
            linhas.append(dict(sd=None, item=_item(it), caso='so_zelo', faltam=[], difere=[], campos={}))
    resumo = {k: sum(1 for x in linhas if x['caso'] == k) for k in GRUPOS}
    resumo['total'] = len(linhas)
    resumo['no_sd'] = len(ativos)
    return linhas, resumo


def _item(it):
    return {'codigo': it.codigo, 'categoria': it.categoria or '', 'modelo': it.modelo or '',
            'hostname': it.hostname or '', 'tag': it.tag or '', 'plaqueta': it.plaqueta or '',
            'situacao': it.situacao or '', 'com_quem': it.com_quem or '', 'site': it.site or ''}


def _quem_difere(it, s):
    """Pessoa diferente dos dois lados. Nome vazio de um lado não conta como divergência."""
    if not s['usuario'] or not it.com_quem:
        return False
    return _chave_nome(s['usuario']) != _chave_nome(it.com_quem)


def _estado_difere(it, s):
    esperado = EQUIVALE.get(it.situacao or '')
    if not esperado or not s['estado']:
        return False
    return _up(s['estado']) != _up(esperado)


# ------------------------------------------------------------------ aplicar
def aplicar(escolhas, quem):
    """escolhas: [{'codigo', 'campos': {campo: valor}, 'criar': bool, 'sd': {...}}]. (n, msg, detalhes)."""
    from app.auth import registrar_log
    from app.estoque import cadastrar_item
    feitos, erros = [], []
    for e in escolhas:
        if e.get('criar'):
            s = e.get('sd') or {}
            codigo = (e.get('codigo') or s.get('plaqueta') or s.get('tag') or s.get('hostname') or '').strip()
            if not codigo:
                erros.append('Ativo do SD sem hostname nem service tag: não dá para cadastrar')
                continue
            if db.session.get(Item, codigo):
                erros.append(f'{codigo}: já existe no Zelo')
                continue
            ok, msg = cadastrar_item({'codigo': codigo, 'categoria': e.get('categoria') or 'Notebook',
                                      'modelo': s.get('modelo') or s.get('tipo') or 'A confirmar',
                                      'hostname': s.get('hostname') or '', 'tag': s.get('tag') or '',
                                      'plaqueta': s.get('plaqueta') or '', 'site': e.get('site') or ''}, quem)
            if ok:
                novo = db.session.get(Item, codigo)
                novo.origem = 'Service Desk'
                # cadastrar põe em estoque; se o SD diz que está com alguém, isso tem que ser dito
                if s.get('usuario'):
                    msg += f'. Atenção: o Service Desk diz que está com {s["usuario"]} — ' \
                           'lance a entrega ou use Ajustar cadastro'
            (feitos if ok else erros).append(f'{codigo}: {msg}')
            continue
        it = db.session.get(Item, (e.get('codigo') or '').strip())
        if not it:
            erros.append(f'{e.get("codigo")}: não encontrei esse item no Zelo')
            continue
        mudou = []
        for campo, valor in (e.get('campos') or {}).items():
            if campo not in {c for c, _d in DO_SD} or not str(valor or '').strip():
                continue
            antes = (getattr(it, campo) or '').strip()
            if _up(antes) == _up(valor):
                continue
            setattr(it, campo, str(valor).strip())
            mudou.append(f'{campo} {antes or "(vazio)"} → {valor}')
        if mudou:
            feitos.append(f'{it.codigo}: ' + '; '.join(mudou))
        else:
            erros.append(f'{it.codigo}: nada a mudar')
    db.session.commit()
    if feitos:
        registrar_log('conferência com o Service Desk', f'{len(feitos)} item(ns) atualizado(s)/cadastrado(s)')
    msg = f'{len(feitos)} item(ns) atualizado(s)'
    if erros:
        msg += f'; {len(erros)} sem efeito'
    return len(feitos), msg, feitos + erros
