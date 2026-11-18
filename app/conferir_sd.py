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
from datetime import date, datetime

from app import db
from app.models import Item, Pessoa, cfg
from app.servicedesk import COM_PESSOA, host_curto

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
    'so_zelo': ('Só no Zelo', 'Máquina com hostname aqui que o Service Desk não conhece: ou está sem agente, ou falta cadastrar lá. Monitor, celular e acessório não entram nesta conta — nunca estiveram no SD. '
                'Notebook, desktop e thin client em uso ficam na Cobertura do agente, acima.'),
}

# Cobertura do agente. Só estas categorias recebem o agente do SDP; monitor, celular e o resto
# nunca vão aparecer lá sozinhos, e cobrar agente deles seria ruído.
CATEGORIAS_AGENTE = ('Notebook', 'Desktop', 'Thin client')
# Máquina parada no armazém não é varrida, e isso é normal: só cobra de quem está em uso.
EM_USO = ('Em uso', 'Emprestado')
# situação do Zelo → estado equivalente no Service Desk
# O mapa situação → estado mora em app.servicedesk (ESTADO_PADRAO + sd_estados), não aqui: esta tela
# tem que acusar exatamente a divergência que a sincronização sabe corrigir.


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


def _data(v):
    """Data do SDP → 'AAAA-MM-DD', ou '' se não der para ler.

    O SDP guarda data como epoch em milissegundos (`warranty_expiry: 1813046399000` num ativo real
    da MB), às vezes embrulhada em {'value': ..., 'display_value': ...}. Aceita também texto já no
    formato ISO, para o caso de este build entregar diferente na listagem.
    """
    if isinstance(v, dict):
        v = v.get('value') or v.get('display_value')
    s = str(v or '').strip()
    if s.isdigit():
        n = int(s)
        try:
            return datetime.fromtimestamp(n / 1000 if n > 10 ** 11 else n).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ''
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s)
    return m.group(1) if m else ''


def login_curto(v):
    """'REYES\\gabriel', 'gabriel@mb.com' e 'Gabriel' → 'gabriel'.

    O agente grava o último usuário com o domínio na frente; o login que veio do Service Desk na
    importação de pessoas pode vir com ou sem. Comparar os dois crus acusaria divergência em todo
    mundo.
    """
    s = str(v or '').strip().lower()
    return s.rsplit('\\', 1)[-1].split('@', 1)[0].strip()


def do_sd(a):
    """O que o Zelo entende de um ativo do Service Desk."""
    return {
        # Dado do agente. `campos_agente` diz se o Service Desk ENTREGOU esses campos para este
        # ativo, mesmo vazios: sem isso, "nenhum ativo tem varredura" e "este build não devolve
        # varredura na listagem" ficariam iguais na tela, e o segundo esconderia o problema todo.
        'varredura': _data(a.get('last_scan_success_time')),
        'logado': _campo(a, 'last_logged_user'),
        'campos_agente': 'last_scan_success_time' in a or 'last_logged_user' in a,
        'id': _campo(a, 'id'),
        'hostname': _campo(a, 'name'),
        # `org_serial_number` entra na lista porque é onde a service tag mora no build da MB
        # (ver CLAUDE.md): lendo só `serial_number` esta tela acha que o SD não tem tag nenhuma.
        'tag': _campo(a, 'serial_number', 'org_serial_number', 'service_tag'),
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
            por_host.setdefault(host_curto(i.hostname), []).append(i)
        if i.tag:
            por_tag.setdefault(_up(i.tag), []).append(i)
        if i.plaqueta:
            por_plaq.setdefault(_up(i.plaqueta), []).append(i)
    return itens, por_host, por_tag, por_plaq


def _casar(s, por_host, por_tag, por_plaq):
    """Acha o item do Zelo: hostname, depois service tag, depois plaqueta.

    Devolve (item, repetidos). Quando a chave aponta para mais de um item do Zelo, não escolhe:
    isso é cadastro duplicado aqui dentro, e a tela precisa dizer isso em vez de inventar um par.

    O hostname casa pelo nome curto: o agente põe o domínio no nome do ativo, a planilha não.
    """
    for chave, indice in ((host_curto(s['hostname']), por_host), (_up(s['tag']), por_tag),
                          (_up(s['plaqueta']), por_plaq)):
        achados = indice.get(chave) if chave else None
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
        # O hostname vem do SD com domínio; o que entra no Zelo, e o que se compara, é o nome curto.
        # Comparado cru, toda máquina com agente cairia em "Dado diferente", e marcar a linha
        # gravaria o domínio no cadastro — que nenhum outro item do Zelo tem.
        do_lado = {campo: (host_curto(s[de]) if campo == 'hostname' else s[de]) for campo, de in DO_SD}
        norm = {campo: (host_curto if campo == 'hostname' else _up) for campo, _de in DO_SD}
        faltam = [(campo, do_lado[campo]) for campo, _de in DO_SD
                  if do_lado[campo] and not (getattr(it, campo) or '').strip()]
        difere = [(campo, (getattr(it, campo) or ''), do_lado[campo]) for campo, _de in DO_SD
                  if do_lado[campo] and (getattr(it, campo) or '').strip()
                  and norm[campo](getattr(it, campo)) != norm[campo](do_lado[campo])]
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
    # Máquina em uso também fica de fora: ela é o assunto da Cobertura do agente, que diz há quanto
    # tempo foi entregue — listar as duas vezes só dobraria o trabalho de quem lê.
    for it in itens:
        if (it.codigo not in casados and (it.hostname or '').strip() and it.situacao != 'Baixada'
                and not _espera_agente(it)):
            linhas.append(dict(sd=None, item=_item(it), caso='so_zelo', faltam=[], difere=[], campos={}))
    resumo = {k: sum(1 for x in linhas if x['caso'] == k) for k in GRUPOS}
    resumo['total'] = len(linhas)
    resumo['no_sd'] = len(ativos)
    return linhas, resumo


def duplicados(ativos):
    """Ativos repetidos DENTRO do Service Desk — a mesma máquina cadastrada duas vezes lá.

    Diferente do grupo 'repetido', que é duplicidade no Zelo. Serve para duas coisas:

    1. ler o teste do agente sem depender de olho: criado o ativo pelo Zelo e forçada a varredura,
       ou o agente fundiu com o registro (1 ativo) ou criou outro (2);
    2. a limpeza da base que o Gabriel quer fazer — no SDP isso se resolve em Actions → Reconcile,
       que mantém o mais novo e carrega fornecedor, custo e PO do registro manual.

    Só agrupa por service tag e hostname: plaqueta repetida no SD é comum e legítima (etiqueta
    reaproveitada), e acusá-la encheria a tela de ruído.
    """
    grupos = []
    for rotulo, chave in (('service tag', 'tag'), ('hostname', 'hostname')):
        por_chave = {}
        for s in ativos:
            # pelo nome curto: 'LMB123' criado pelo Zelo e 'lmb123.reyesholdings.com' criado pelo
            # agente são a mesma máquina duas vezes — exatamente a duplicata que esta lista procura
            v = host_curto(s.get(chave)) if chave == 'hostname' else _up(s.get(chave))
            if v:
                por_chave.setdefault(v, []).append(s)
        for v, iguais in sorted(por_chave.items()):
            if len(iguais) > 1:
                grupos.append({'por': rotulo, 'chave': iguais[0][chave], 'ativos': iguais})
    # uma máquina com tag E hostname repetidos apareceria duas vezes; vale a mais específica
    vistos, saida = set(), []
    for g in grupos:
        ids = tuple(sorted(a['id'] for a in g['ativos']))
        if ids not in vistos:
            vistos.add(ids)
            saida.append(g)
    return saida


# ------------------------------------------------------------------ cobertura do agente
def _espera_agente(it):
    """Máquina que deveria estar no Service Desk pelo agente: categoria que recebe agente, em uso,
    e com alguma chave para casar (sem hostname nem tag, nenhuma busca acharia)."""
    return (it.categoria in CATEGORIAS_AGENTE and it.situacao in EM_USO
            and bool((it.hostname or '').strip() or (it.tag or '').strip()))


def _dias_cfg(chave, padrao):
    try:
        return max(1, int(cfg(chave)))
    except (TypeError, ValueError):
        return padrao


def _dias_desde(iso, hoje):
    try:
        return (hoje - date.fromisoformat((iso or '')[:10])).days
    except ValueError:
        return None


def cobertura(ativos, hoje=None):
    """Onde o agente do SDP não está fazendo o trabalho dele. Três perguntas:

    - **Entregue e sem agente**: máquina em uso que o SD não conhece, ou só conhece por cadastro
      manual (nunca varrida). O agente não vem na imagem do Windows e é instalado à mão; máquina
      formatada ou nova sem ele é invisível para o SD, e só o Zelo sabe que ela foi entregue.
    - **Agente parou de ver**: a última varredura é velha numa máquina que o Zelo diz estar em uso
      — formatada, perdida, parada numa gaveta ou fora da rede há semanas.
    - **Quem usa difere**: o último login que o agente viu não é de quem o Zelo diz estar com a
      máquina. É o sinal mais forte de cadastro errado, e por isso não corrige nada: mostra.

    Login de varredura velha não conta: quem usou a máquina há dois meses não diz quem está com ela.
    Devolve um dicionário com as três listas e o que a tela precisa para explicar o que faltou.
    """
    hoje = hoje or date.today()
    dias_sem = _dias_cfg('dias_sem_agente', 7)
    dias_scan = _dias_cfg('dias_agente_sumido', 30)
    veio_agente = any(s.get('campos_agente') for s in ativos)
    itens, por_host, por_tag, por_plaq = _indices()
    casado = {}
    for s in ativos:
        if not s['hostname'] and not s['tag']:
            continue
        it, _rep = _casar(s, por_host, por_tag, por_plaq)
        if it:
            casado.setdefault(it.codigo, s)

    sem_agente, parou, quem_usa, sem_login, aguardando = [], [], [], 0, 0
    for it in itens:
        if not _espera_agente(it):
            continue
        s = casado.get(it.codigo)
        dias = _dias_desde(it.desde, hoje)
        # Cadastro no SD sem nenhuma varredura é registro manual: o agente nunca esteve lá. Só dá
        # para afirmar isso quando a listagem entrega os campos do agente.
        nunca_varrida = bool(s) and veio_agente and not s['varredura']
        if s is None or nunca_varrida:
            if dias is not None and dias < dias_sem:
                aguardando += 1          # o Suporte ainda pode estar instalando
                continue
            sem_agente.append(dict(item=_item(it), dias=dias, sd=s,
                                   motivo='só cadastro manual no SD, nunca varrida' if s else 'não está no SD'))
            continue
        idade = _dias_desde(s['varredura'], hoje)
        if idade is not None and idade > dias_scan:
            parou.append(dict(item=_item(it), sd=s, dias=idade))

    logins = {p.id: login_curto(p.user) for p in Pessoa.query.filter(Pessoa.user.isnot(None), Pessoa.user != '')}
    por_codigo = {x.codigo: x for x in itens}
    for codigo, s in casado.items():
        if not s['logado']:
            continue
        idade = _dias_desde(s['varredura'], hoje)
        if idade is not None and idade > dias_scan:
            continue
        it = por_codigo.get(codigo)
        # em manutenção e em preparação quem faz login é o técnico, e isso é o trabalho dele
        if not it or it.situacao in ('Baixada', 'Manutenção', 'Em preparação'):
            continue
        visto = login_curto(s['logado'])
        if it.situacao in COM_PESSOA and it.matricula:
            do_zelo = logins.get(it.matricula, '')
            if not do_zelo:
                sem_login += 1           # sem o login da pessoa não há o que comparar
                continue
            if do_zelo != visto:
                quem_usa.append(dict(item=_item(it), sd=s, login_zelo=do_zelo, login_sd=visto))
        elif it.situacao not in COM_PESSOA:
            # o Zelo diz que ninguém está com ela, e alguém fez login recente
            quem_usa.append(dict(item=_item(it), sd=s, login_zelo='', login_sd=visto))

    sem_agente.sort(key=lambda x: (x['dias'] is None, x['dias'] if x['dias'] is not None else 0))
    parou.sort(key=lambda x: -x['dias'])
    quem_usa.sort(key=lambda x: x['item']['codigo'])
    return dict(sem_agente=sem_agente, parou=parou, quem_usa=quem_usa, sem_login=sem_login,
                aguardando=aguardando, veio_agente=veio_agente, dias_sem=dias_sem, dias_scan=dias_scan)


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
    from app import servicedesk as sd
    # o mesmo mapa que a sincronização usa, inclusive o que foi customizado em `sd_estados`: dois
    # mapas separados divergiriam, e a tela acusaria divergência que a fila não corrige.
    esperado = sd.mapa_estados().get(it.situacao or '')
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
            s = dict(e.get('sd') or {})
            # o cadastro do Zelo guarda o nome curto, como a planilha sempre guardou
            s['hostname'] = host_curto(s.get('hostname'))
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
