"""Integração com o ServiceDesk Plus on-premises (API v3).

O que faz:
- consulta o chamado (solicitante, assunto, status) para a conferência em tempo real;
- depois de um lançamento com Nº de chamado, anexa o PDF do termo ao chamado e grava uma nota.

Princípios:
- o Zelo funciona sem o Service Desk: se não estiver configurado ou estiver fora do ar, o lançamento
  grava normalmente e o envio fica pendente em "Envios ao Service Desk", com Reenviar;
- a chave de API fica só no banco do servidor (Administração → Service Desk), nunca aparece na tela;
- só usuário e nome vêm do Service Desk (o cadastro do AD não é fonte confiável de cargo, CC etc.).

A nota da API v3 não aceita anexo: o PDF vai como anexo do chamado (PUT /requests/{id}/upload, campo
input_file) e a nota cita o nome do arquivo.
"""
import json
import re
import ssl
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from app import db
from app.models import Config

ACCEPT = 'application/vnd.manageengine.sdp.v3+json'
CHAVES = ('sd_url', 'sd_chave', 'sd_ssl', 'sd_ativo', 'sd_ativos', 'sd_estados', 'sd_anexar_ativo',
          'sd_criar_ativo', 'sd_tipos', 'sd_campos_zelo')
TIPOS_ENVIO = ('Entrega', 'Empréstimo', 'Devolução')
NOMES_TIPO = {'chamado': 'Termo + nota', 'ativo': 'Ativo', 'termo': 'Termo assinado'}
_cache = {}            # chamado → (quando, dados)
_modulos = {}          # tipos de produto do SD: {'quando', 'lista'}
CACHE_SEG = 300

# Transporte trocável nos testes: f(metodo, url, headers, corpo_bytes) → (status, texto)
transporte = None


def conf(chave):
    c = db.session.get(Config, chave)
    return c.valor if c and c.valor else ''


def salvar_conf(valores):
    for k, v in valores.items():
        if k not in CHAVES:
            continue
        c = db.session.get(Config, k)
        if c is None:
            db.session.add(Config(chave=k, valor=v))
        else:
            c.valor = v
    db.session.commit()
    _cache.clear()
    _modulos.clear()          # trocar de Service Desk troca a lista de tipos


def configurado():
    return bool(conf('sd_url') and conf('sd_chave') and conf('sd_ativo') == 'Sim')


class ErroSD(Exception):
    pass


def _http(metodo, caminho, dados=None, arquivo=None, timeout=10):
    url = conf('sd_url').rstrip('/') + caminho
    h = {'authtoken': conf('sd_chave'), 'Accept': ACCEPT}
    corpo = None
    if arquivo:
        nome, conteudo, tipo = arquivo
        fronteira = uuid.uuid4().hex
        corpo = (f'--{fronteira}\r\nContent-Disposition: form-data; name="input_file"; filename="{nome}"\r\n'
                 f'Content-Type: {tipo}\r\n\r\n').encode() + conteudo + f'\r\n--{fronteira}--\r\n'.encode()
        h['Content-Type'] = f'multipart/form-data; boundary={fronteira}'
    elif dados is not None:
        q = urllib.parse.urlencode({'input_data': json.dumps(dados, ensure_ascii=False)})
        if metodo == 'GET':
            url += '?' + q
        else:
            corpo = q.encode()
            h['Content-Type'] = 'application/x-www-form-urlencoded'
    if transporte:
        st, texto = transporte(metodo, url, h, corpo)
    else:
        ctx = None
        if url.startswith('https') and conf('sd_ssl') == 'Ignorar':
            ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, data=corpo, headers=h, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                st, texto = r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            st, texto = e.code, e.read().decode('utf-8', 'replace')
        except Exception as e:  # rede, DNS, certificado
            raise ErroSD(f'Sem conexão com o Service Desk: {e}') from e
    try:
        j = json.loads(texto) if texto else {}
    except ValueError:
        raise ErroSD(f'Resposta inesperada do Service Desk (HTTP {st})')
    rs = j.get('response_status') or {}
    if isinstance(rs, list):          # listagens devolvem response_status como lista
        rs = rs[0] if rs else {}
    if st >= 400 or rs.get('status') == 'failed':
        msgs = [m.get('message') or m.get('field') or '' for m in rs.get('messages', [])] if isinstance(rs, dict) else []
        raise ErroSD(f'Service Desk recusou (HTTP {st}): ' + ('; '.join(x for x in msgs if x) or texto[:200]))
    return j


# ------------------------------------------------------------------ leitura
def chamado(numero):
    """{'id', 'assunto', 'status', 'solicitante', 'email', 'login'} ou None se não existir. Cache de 5 min."""
    n = ''.join(c for c in str(numero or '') if c.isdigit())
    if not n or not configurado():
        return None
    c = _cache.get(n)
    if c and time.time() - c[0] < CACHE_SEG:
        return c[1]
    try:
        r = _http('GET', f'/api/v3/requests/{n}', timeout=5).get('request') or {}
    except ErroSD as e:
        if 'HTTP 404' in str(e) or ('not' in str(e).lower() and 'found' in str(e).lower()):
            _cache[n] = (time.time(), {'id': n, 'inexistente': True})
            return _cache[n][1]
        return {'id': n, 'erro': str(e)}
    sol = r.get('requester') or {}
    d = {'id': n, 'assunto': r.get('subject') or '', 'status': (r.get('status') or {}).get('name') or '',
         'solicitante': sol.get('name') or '', 'email': sol.get('email_id') or '', 'login': sol.get('login_name') or ''}
    _cache[n] = (time.time(), d)
    return d


def testar():
    """Usado no botão Testar conexão: lista 1 chamado."""
    j = _http('GET', '/api/v3/requests', {'list_info': {'row_count': 1}}, timeout=8)
    return len(j.get('requests') or [])


# ------------------------------------------------------------------ escrita
def anexar(numero, nome, conteudo, tipo='application/pdf'):
    return _http('PUT', f'/api/v3/requests/{numero}/upload', arquivo=(nome, conteudo, tipo), timeout=30)


def nota(numero, texto):
    return _http('POST', f'/api/v3/requests/{numero}/notes',
                 {'note': {'description': texto, 'show_to_requester': False, 'mark_first_response': False,
                           'add_to_linked_requests': False}})


def anexar_ativo_ao_chamado(numero, hostname):
    """Põe o equipamento DENTRO do chamado, não só na nota.

    É a resposta ao que a Giselly quer — o ativo aparecendo no chamado do solicitante — sem
    customizar o Service Desk. Lê os ativos que já estão no chamado e acrescenta, em vez de
    mandar só o novo: o PUT substitui a lista inteira, então mandar um apagaria os outros.
    Devolve (ok, recado). Nunca levanta erro: a nota e o termo valem mesmo se isto não passar.
    """
    host = (hostname or '').strip().upper()
    if not host:
        return False, ''
    try:
        r = _http('GET', f'/api/v3/requests/{numero}', timeout=10).get('request') or {}
        atuais = [a for a in (r.get('assets') or []) if isinstance(a, dict)]
        if any((a.get('name') or '').strip().upper() == host for a in atuais):
            return True, f'{host} já estava no chamado'
        lista = [{'id': a['id']} if a.get('id') else {'name': a.get('name')} for a in atuais]
        lista.append({'name': host})
        _http('PUT', f'/api/v3/requests/{numero}', {'request': {'assets': lista}}, timeout=15)
        return True, f'{host} anexado ao chamado'
    except ErroSD as e:
        return False, f'não deu para anexar o ativo ao chamado ({e})'


def texto_nota(m, it, arquivo):
    oque = f'{it.categoria} {it.modelo or ""} {it.codigo}'.replace('  ', ' ') if it else (f'linha {m.linha}' if m.linha else '')
    verbo = {'Entrega': 'Entregue' if m.etapa == 'Entregue' else f'Entrega registrada ({m.etapa})',
             'Empréstimo': 'Emprestado', 'Devolução': 'Devolvido'}.get(m.tipo, m.tipo)
    quem = f'{m.nome or ""}' + (f' ({m.matricula})' if m.matricula else '') + (f', CC {m.cc}' if m.cc else '')
    linhas = [f'[Zelo] {verbo}: {oque}' + (f' → {quem}' if m.tipo != 'Devolução' else f' por {quem}'),
              f'Lançamento Nº {m.id}, registrado por {m.resp or ""}.']
    if m.prazo and m.tipo == 'Empréstimo':
        linhas.append(f'Devolução prevista: {m.prazo[8:10]}/{m.prazo[5:7]}/{m.prazo[:4]}.')
    if arquivo:
        linhas.append(f'Termo anexado ao chamado: {arquivo} (termo {m.termo.lower() if m.termo else "a assinar"}).')
    return '<br>'.join(linhas)


# ------------------------------------------------------------------ ativos (usuário e estado)
# Provado no laboratório (SDP 16): PUT /api/v3/asset_assets/{id} com {"asset_asset": {...}} edita usuário e estado.
# O formato em lote (?ids=) devolve "Internal Error" nesse build: não usar.
def ativos_ligado():
    return configurado() and conf('sd_ativos') == 'Sim'


def anexar_ativo_ligado():
    return configurado() and conf('sd_anexar_ativo') == 'Sim'


def _busca(campo, valor, linhas=5):
    return {'list_info': {'row_count': linhas, 'search_criteria': {'field': campo, 'condition': 'is', 'value': valor}}}


def listar_ativos(inicio=1, linhas=100):
    """Uma página de ativos do Service Desk. Devolve (lista, tem_mais).

    De propósito sem `fields_required`: os nomes de campo variam entre build e tipo de produto, e
    pedir uma lista errada derruba a chamada inteira. Vem tudo e o Zelo lê o que reconhece.
    """
    j = _http('GET', '/api/v3/asset_assets',
              {'list_info': {'row_count': linhas, 'start_index': inicio, 'get_total_count': True}}, timeout=25)
    info = j.get('list_info') or {}
    return (j.get('asset_assets') or []), bool(info.get('has_more_rows'))


def achar_ativo(hostname):
    r = _http('GET', '/api/v3/asset_assets', _busca('name', hostname))
    lst = r.get('asset_assets') or []
    return lst[0] if lst else None


def listar_usuarios(inicio=1, linhas=100):
    """Uma página de usuários do Service Desk. Devolve (lista, tem_mais).

    Só nome, e-mail e login: cargo, CC e matrícula do AD não são fonte confiável (decisão do
    Gabriel), e pedir menos campo deixa a listagem bem mais leve.
    """
    j = _http('GET', '/api/v3/users',
              {'list_info': {'row_count': linhas, 'start_index': inicio, 'get_total_count': True,
                             'fields_required': ['id', 'name', 'email_id', 'login_name', 'is_active']}},
              timeout=20)
    info = j.get('list_info') or {}
    return (j.get('users') or []), bool(info.get('has_more_rows'))


def achar_usuario(email=None, nome=None):
    """Id do usuário no Service Desk: pelo e-mail; senão pelo nome exato (só se for único)."""
    if email:
        try:
            u = _http('GET', '/api/v3/users', _busca('email_id', email)).get('users') or []
            if u:
                return u[0]
        except ErroSD:
            pass
    if nome:
        u = _http('GET', '/api/v3/users', _busca('name', nome)).get('users') or []
        if len(u) == 1:
            return u[0]
        if len(u) > 1:
            raise ErroSD(f'Há {len(u)} usuários "{nome}" no Service Desk: cadastre o e-mail da pessoa no Zelo')
    return None


def atualizar_ativo(asset_id, usuario_id, estado, extra=None):
    """Um ativo por chamada: o formato em lote (?ids=) devolve 'Internal Error' neste build.

    Estado vazio não entra no corpo — mandar um estado nulo faria o SDP recusar a chamada inteira,
    e há situação do Zelo que de propósito não mexe no estado (ver ESTADO_PADRAO).

    `extra` são os campos de que o Zelo é dono (ver CAMPOS_ZELO). Só vêm quando `sd_campos_zelo`
    está ligado, porque num ativo que já existe eles sobrescrevem o que alguém pôs à mão no SD —
    e isso é uma decisão, não um detalhe.
    """
    corpo = {'user': {'id': str(usuario_id)} if usuario_id else None}
    if estado:
        corpo['state'] = {'name': estado}
    corpo.update(extra or {})
    return _http('PUT', f'/api/v3/asset_assets/{asset_id}', {'asset_asset': corpo})


# Situação do item no Zelo → estado do ativo no Service Desk.
#
# O estado sai da SITUAÇÃO ATUAL do item, não do tipo de lançamento. É a diferença entre cobrir
# dois casos (entrega e devolução) e cobrir o ciclo inteiro: manutenção, baixa e até uma correção
# feita pelo Ajustar cadastro passam a chegar no Service Desk sem código novo.
#
# Situação que não está aqui não mexe no estado — só no usuário. É de propósito: trânsito e
# "a localizar" não têm equivalente nos estados que vêm de fábrica no SDP, e inventar um nome que
# não existe lá faria a chamada falhar. Quem tiver estado próprio ajusta em `sd_estados`.
ESTADO_PADRAO = {
    'Em uso': 'In Use', 'Emprestado': 'In Use', 'Pendente devolução': 'In Use',
    'Em estoque': 'In Store', 'Reservada': 'In Store', 'Devolvido': 'In Store', 'Em preparação': 'In Store',
    'Manutenção': 'In Repair', 'Baixada': 'Expired',
}
# situação em que o ativo continua no nome de alguém
COM_PESSOA = ('Em uso', 'Emprestado', 'Pendente devolução', 'Reservada')


def mapa_estados():
    """O mapa em vigor. `sd_estados` sobrepõe o padrão: 'Situação=Estado;Situação=Estado'."""
    mapa = dict(ESTADO_PADRAO)
    for par in (conf('sd_estados') or '').split(';'):
        sit, _s, est = par.partition('=')
        sit, est = sit.strip(), est.strip()
        if sit:
            mapa[sit] = est or None           # sem estado à direita = não mexer nessa situação
    return mapa


def acao_ativo(m, it=None):
    """O estado que o ativo deve ter no Service Desk, pela situação atual do item. None = não mexer."""
    from app.models import Item
    it = it or (db.session.get(Item, m.item) if (m is not None and m.item) else None)
    if not it:
        return None
    return mapa_estados().get(it.situacao or '')


# Categoria no Zelo → tipo de produto no Service Desk. Só o que existe de fábrica no SDP; o que
# não está aqui vai sem tipo, e o SDP resolve (ou recusa, e o erro aparece na fila). Editável em
# `sd_tipos` para quem renomeou os tipos.
TIPO_PADRAO = {
    'Notebook': 'Laptop', 'Desktop': 'Workstation', 'Thin client': 'Workstation',
    'Monitor': 'Monitor', 'Dock station': 'Docking Station', 'Celular': 'Mobile',
    'Tablet': 'Tablet', 'Coletor': 'Handheld', 'Telefone IP': 'IP Phone', 'Impressora': 'Printer',
}


def mapa_tipos():
    """O mapa em vigor. `sd_tipos` sobrepõe o padrão: 'Categoria=Tipo;Categoria=Tipo'."""
    mapa = dict(TIPO_PADRAO)
    for par in (conf('sd_tipos') or '').split(';'):
        cat, _s, tp = par.partition('=')
        cat, tp = cat.strip(), tp.strip()
        if cat:
            mapa[cat] = tp or None
    return mapa


# Os campos que o Zelo escreve num ativo que JÁ existe. Hostname, service tag, modelo e o que a
# máquina diz de si mesma ficam de fora de propósito: o agente descreve melhor que digitação, e a
# regra de dono (ver PLANO.md) é o que impede os dois lados de ficarem trocando dado.
CAMPOS_ZELO = ('asset_tag', 'site', 'vendor', 'warranty_expiry')


def criar_ativo_ligado():
    return ativos_ligado() and conf('sd_criar_ativo') == 'Sim'


def campos_zelo_ligado():
    return ativos_ligado() and conf('sd_campos_zelo') == 'Sim'


def corpo_do_item(it, estado=None):
    """O que o Zelo manda sobre um ativo — só os campos de que ELE é dono.

    Hostname, service tag, modelo, SO, memória: quem descreve melhor é o agente, então o Zelo não
    escreve nada disso num ativo que já existe (ver `atualizar_ativo`). Na CRIAÇÃO é diferente: o
    ativo não existe, ninguém descreveu nada, e mandar hostname e tag é o que faz o agente casar
    com este registro depois em vez de duplicar.

    Campo vazio fica fora do corpo: no SDP mandar nulo num campo é diferente de não mandar o campo,
    e o primeiro apaga o que estiver lá.
    """
    c = {}
    if (it.hostname or '').strip():
        c['name'] = it.hostname.strip().upper()
    if (it.tag or '').strip():
        c['serial_number'] = it.tag.strip()
    if (it.plaqueta or '').strip():
        c['asset_tag'] = it.plaqueta.strip()
    if (it.site or '').strip():
        c['site'] = {'name': it.site.strip()}
    if (it.fornecedor or '').strip():
        c['vendor'] = {'name': it.fornecedor.strip()}
    if (it.garantia or '').strip():
        c['warranty_expiry'] = {'value': it.garantia.strip()}
    tipo = mapa_tipos().get(it.categoria or '')
    if tipo:
        c['product_type'] = {'name': tipo}
    if estado:
        c['state'] = {'name': estado}
    return c


def listar_modulos(recarregar=False):
    """Os módulos de ativo do Service Desk — um por tipo de produto, cada um com o SEU endereço.

    `/api/v3/asset_assets` **não cria** ativo: a ManageEngine separou um endereço por tipo de
    produto (`asset_computers`, `asset_access_points`, ...), e o nome de cada um vem daqui, no campo
    `api_plural_name`. Por isso o Zelo pergunta em vez de carregar uma lista fixa: os tipos variam
    entre build e entre instalação, e lista fixa é exatamente o que devolve
    "Cannot add asset under Asset product type".
    """
    agora = time.time()
    if not recarregar and _modulos.get('quando', 0) + 1800 > agora:
        return _modulos['lista']
    j = _http('GET', '/api/v3/requests/assets/module', timeout=20)
    lista = j.get('module') or j.get('modules') or []
    lista = [m for m in lista if isinstance(m, dict) and m.get('api_plural_name')]
    _modulos.update(quando=agora, lista=lista)
    return lista


def _nome(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip().lower()


def modulo_do_tipo(tipo):
    """O módulo cujo nome bate com o tipo de produto pedido. None se não achar."""
    alvo = _nome(tipo)
    if not alvo:
        return None
    mods = listar_modulos()
    for campo in ('display_name', 'api_name', 'internal_name'):
        for m in mods:
            if _nome(m.get(campo)) == alvo:
                return m
    return None


def criar_ativo(it, estado=None):
    """Cria o ativo no Service Desk a partir do cadastro do Zelo. Devolve o ativo criado.

    Um por chamada, como toda escrita neste build. Não tenta adivinhar o `product` (o modelo
    precisa existir como produto cadastrado no SDP, e inventar um faria a chamada falhar inteira):
    o tipo de produto basta para o ativo nascer, e o resto o agente completa quando chegar.
    """
    corpo = corpo_do_item(it, estado)
    if not corpo.get('name'):
        raise ErroSD('Item sem hostname no Zelo: o ativo no Service Desk é identificado pelo nome')
    tipo = (corpo.get('product_type') or {}).get('name')
    if not tipo:
        raise ErroSD(f'Categoria "{it.categoria}" sem tipo de produto: a criação precisa de um '
                     '(ajuste o mapa de tipos em Administração → Service Desk)')
    mod = modulo_do_tipo(tipo)
    if not mod:
        nomes = ', '.join(sorted({m.get('display_name') or m.get('api_name') or ''
                                  for m in listar_modulos()} - {''}))
        raise ErroSD(f'O tipo de produto "{tipo}" não existe no seu Service Desk.'
                     + (f' Os que existem: {nomes}' if nomes else ''))
    # cada tipo tem seu endereço e sua chave no corpo: asset_computers → {'asset_computer': {...}}
    plural = mod['api_plural_name']
    chave = mod.get('api_name') or plural.rstrip('s')
    j = _http('POST', f'/api/v3/{plural}', {chave: corpo}, timeout=20)
    novo = j.get(chave) or j.get('asset_asset') or {}
    if isinstance(novo, list):
        novo = novo[0] if novo else {}
    if not novo.get('id'):
        raise ErroSD('O Service Desk aceitou a chamada mas não devolveu o ativo criado')
    return novo


def apagar_ativo(asset_id):
    """Apaga UM ativo. Só para o ativo de teste do diagnóstico.

    Nunca para ativo de verdade: apagar um ativo com agente instalado desinstala o agente da
    máquina ou joga o host na lista de exclusão do SDP, e ele não volta sozinho na varredura.
    """
    return _http('DELETE', f'/api/v3/asset_assets/{asset_id}', timeout=15)


def diagnostico_criacao():
    """Prova, no Service Desk de verdade, se o Zelo consegue criar ativo — e com quais campos.

    A documentação pública e este build não batem (`/api/v3/assets` × `/api/v3/asset_assets`, lote
    que devolve "Internal Error"), então não dá para prometer a criação em massa de 3203 itens com
    base em documentação. Isto cria UM ativo de teste, confere o que voltou campo por campo, e
    apaga em seguida. Devolve (ok, linhas) — `linhas` é o relatório, mesmo quando falha.
    """
    from types import SimpleNamespace
    marca = f'ZELO-TESTE-{uuid.uuid4().hex[:6].upper()}'
    falso = SimpleNamespace(hostname=marca, tag=f'TAG{uuid.uuid4().hex[:7].upper()}',
                            plaqueta='TESTE-ZELO', categoria='Notebook', site='', fornecedor='',
                            garantia='')
    enviado = corpo_do_item(falso, 'In Store')
    linhas = [f'Ativo de teste: {marca}']
    # Primeiro o que existe NESTE Service Desk: sem isso, um erro de criação não diz se o problema
    # é o endereço, o tipo de produto ou um campo.
    try:
        mods = listar_modulos(recarregar=True)
        linhas.append(f'Tipos de produto no seu Service Desk ({len(mods)}), com o endereço de cada um:')
        for m in sorted(mods, key=lambda x: _nome(x.get('display_name'))):
            cat = (m.get('category') or {}).get('display_name') if isinstance(m.get('category'), dict) else m.get('category')
            linhas.append(f'  {m.get("display_name") or m.get("api_name")}'
                          f' → /api/v3/{m["api_plural_name"]}' + (f'  [{cat}]' if cat else ''))
    except ErroSD as e:
        linhas += [f'Não deu para listar os tipos de produto: {e}',
                   'Sem essa lista o Zelo não sabe em qual endereço criar: /api/v3/asset_assets não cria ativo.']
        return False, linhas
    try:
        novo = criar_ativo(falso, 'In Store')
    except ErroSD as e:
        linhas += [f'A criação FALHOU: {e}',
                   'Campos mandados: ' + ', '.join(sorted(enviado)),
                   'Se a recusa citar um TIPO, acerte o mapa de tipos acima com um nome da lista.',
                   'Se citar um CAMPO, me diga qual que eu tiro do corpo da chamada.']
        return False, linhas
    linhas.append(f'Criado com id {novo.get("id")}. Conferindo o que o Service Desk guardou:')
    visto = {}
    try:
        visto = achar_ativo(marca) or {}
    except ErroSD:
        pass
    def _valor(v):
        return (v.get('name') or v.get('value') or '') if isinstance(v, dict) else (v or '')
    for campo in sorted(enviado):
        mandado, guardado = _valor(enviado[campo]), _valor((visto or novo).get(campo))
        bate = str(mandado).strip().upper() == str(guardado).strip().upper()
        linhas.append(f'  {"OK  " if bate else "NÃO "} {campo}: mandei "{mandado}"'
                      + ('' if bate else f', guardou "{guardado}"'))
    try:
        apagar_ativo(novo['id'])
        linhas.append('Ativo de teste apagado.')
    except ErroSD as e:
        linhas.append(f'ATENÇÃO: não deu para apagar o ativo de teste ({e}). Apague {marca} à mão.')
    return True, linhas


def enviar_ativo(envio, m):
    """Atualiza usuário e estado do ativo. Funciona sem lançamento: manutenção e ajuste de cadastro
    mudam a situação do item sem gerar movimentação, e o estado no Service Desk tem que acompanhar."""
    from app.models import Item, Pessoa
    it = db.session.get(Item, m.item) if (m is not None and m.item) else None
    if not it and envio.alvo:
        it = Item.query.filter(Item.hostname.ilike(envio.alvo)).first()
    host = (envio.alvo or (it.hostname if it else '') or '').strip().upper()
    if not host:
        raise ErroSD('Item sem hostname no Zelo: não dá para achar o ativo no Service Desk')
    estado = acao_ativo(m, it)
    a = achar_ativo(host)
    nasceu = ''
    if not a:
        if not (it and criar_ativo_ligado()):
            raise ErroSD(f'Ativo {host} não existe no Service Desk')
        a = criar_ativo(it, estado)
        nasceu = ' (cadastrado agora)'
    extra = {k: v for k, v in corpo_do_item(it).items() if k in CAMPOS_ZELO} \
        if (it and not nasceu and campos_zelo_ligado()) else None
    # quem está com o ativo sai do CADASTRO do item, não do lançamento: assim uma correção pelo
    # Ajustar cadastro chega ao Service Desk igual a uma entrega.
    uid, quem = None, ''
    if it and it.situacao in COM_PESSOA and it.matricula:
        p = db.session.get(Pessoa, it.matricula)
        quem = (p.nome if p else it.com_quem) or ''
        u = achar_usuario(p.email if p else None, quem)
        if not u:
            raise ErroSD(f'{quem or it.matricula} não encontrado(a) como usuário no Service Desk')
        uid = u.get('id')
    atualizar_ativo(a['id'], uid, estado, extra)
    aviso = ''
    serial = (a.get('serial_number') or a.get('service_tag') or '')
    if it and it.tag and serial and serial.upper() != it.tag.upper():
        aviso = f' (atenção: service tag no SD {serial} ≠ Zelo {it.tag})'
    return (f'{host}{nasceu} → {estado or "estado inalterado"}'
            + (f' com {quem}' if uid else ' (sem usuário)') + aviso)


def enviar_termo_assinado(envio, m):
    """Anexa ao chamado o termo ASSINADO guardado no Zelo e grava a nota apontando para ele."""
    from app.termo_arquivo import MIME, caminho
    c = caminho(m)
    if not c:
        raise ErroSD('O termo assinado não está mais guardado no Zelo')
    ext = c.rsplit('.', 1)[-1].lower()
    nome = f'Termo_assinado_Zelo_{m.id}.{ext}'
    if not envio.anexo_ok:
        with open(c, 'rb') as fh:
            anexar(envio.chamado, nome, fh.read(), MIME.get(ext, 'application/octet-stream'))
        envio.anexo_ok = True
    nota(envio.chamado, f'[Zelo] Termo ASSINADO do lançamento Nº {m.id} anexado ao chamado: {nome}')
    return f'{nome} anexado ao chamado {envio.chamado}'


def enfileirar_termo(movs):
    """Envio do termo assinado para os lançamentos que já têm chamado e arquivo guardado."""
    from app.models import EnvioSD
    novos = []
    for m in movs:
        if not (m.chamado and m.termo_arquivo):
            continue
        n = ''.join(c for c in m.chamado if c.isdigit())
        if not n:
            continue
        ja = EnvioSD.query.filter_by(mov_id=m.id, tipo='termo', chamado=n, status='Enviado').first()
        if ja:
            continue
        e = EnvioSD(mov_id=m.id, tipo='termo', chamado=n, alvo=m.termo_arquivo, status='Pendente',
                    criado=datetime.now().isoformat(timespec='seconds'), tentativas=0)
        db.session.add(e)
        novos.append(e)
    db.session.commit()
    return [e.id for e in novos]


def enfileirar_ativos(movs):
    """Um envio por ativo tocado. Sem repetir o mesmo host: num lote de bipagem o mesmo item pode
    aparecer em mais de um lançamento, e mandar duas vezes o mesmo estado é só gastar chamada."""
    from app.models import EnvioSD, Item
    novos, vistos = [], set()
    pendentes = {e.alvo for e in EnvioSD.query.filter(EnvioSD.tipo == 'ativo',
                                                      EnvioSD.status == 'Pendente').all()}
    for m in movs:
        it = db.session.get(Item, m.item) if m.item else None
        if not (it and (it.hostname or '').strip()):
            continue
        host = it.hostname.strip().upper()
        if host in vistos or host in pendentes:
            continue
        vistos.add(host)
        e = EnvioSD(mov_id=m.id, tipo='ativo', alvo=host, status='Pendente',
                    criado=datetime.now().isoformat(timespec='seconds'), tentativas=0)
        db.session.add(e)
        novos.append(e)
    db.session.commit()
    return [e.id for e in novos]


def enfileirar_item(app_, codigo):
    """Avisa o Service Desk do estado de UM item, sem lançamento por trás.

    Manutenção e Ajustar cadastro mudam a situação do item direto (uma abre ocorrência, o outro
    corrige o que veio errado da planilha) e não geram movimentação — mas o ativo no Service Desk
    tem que acompanhar do mesmo jeito.
    """
    from app.models import EnvioSD, Item
    if not ativos_ligado():
        return 0
    it = db.session.get(Item, codigo) if isinstance(codigo, str) else codigo
    if not (it and (it.hostname or '').strip()):
        return 0
    host = it.hostname.strip().upper()
    if EnvioSD.query.filter(EnvioSD.tipo == 'ativo', EnvioSD.status == 'Pendente', EnvioSD.alvo == host).first():
        return 0
    e = EnvioSD(mov_id=None, tipo='ativo', alvo=host, status='Pendente',
                criado=datetime.now().isoformat(timespec='seconds'), tentativas=0)
    db.session.add(e)
    db.session.commit()
    processar(app_, [e.id])
    return 1


def enfileirar(movs):
    """Cria os envios para os lançamentos que têm chamado. Não envia (ver processar)."""
    from app.models import EnvioSD
    novos = []
    for m in movs:
        if m.chamado and m.tipo in TIPOS_ENVIO and ''.join(c for c in m.chamado if c.isdigit()):
            e = EnvioSD(mov_id=m.id, tipo='chamado', chamado=''.join(c for c in m.chamado if c.isdigit()), status='Pendente',
                        criado=datetime.now().isoformat(timespec='seconds'), tentativas=0)
            db.session.add(e)
            novos.append(e)
    db.session.commit()
    return [e.id for e in novos]


def enviar(envio):
    """Anexa o termo e grava a nota de UM envio. Atualiza o status; não levanta exceção."""
    from app.models import Item, Movimentacao
    from app.routes.termo import montar
    from app.termo_pdf import gerar_pdf
    envio.tentativas = (envio.tentativas or 0) + 1
    m = db.session.get(Movimentacao, envio.mov_id) if envio.mov_id else None
    try:
        if not configurado():
            raise ErroSD('Integração com o Service Desk desligada ou sem chave')
        if not m and envio.tipo != 'ativo':
            raise ErroSD('Lançamento não existe mais (foi desfeito)')
        if envio.tipo == 'termo':
            envio.erro = enviar_termo_assinado(envio, m)
            envio.status, envio.enviado = 'Enviado', datetime.now().isoformat(timespec='seconds')
            db.session.commit()
            return True
        if envio.tipo == 'ativo':
            if not ativos_ligado():
                raise ErroSD('Atualização de ativos desligada')
            envio.erro = enviar_ativo(envio, m)
            envio.status, envio.enviado = 'Enviado', datetime.now().isoformat(timespec='seconds')
            db.session.commit()
            return True
        it = db.session.get(Item, m.item) if m.item else None
        arquivo = None
        d, _erro = montar(str(m.id))
        if d and d.get('tipo') != 'Sem termo' and not envio.anexo_ok:
            arquivo = f'Termo_Zelo_{m.id}.pdf'
            anexar(envio.chamado, arquivo, gerar_pdf(d))
            envio.anexo_ok = True
        elif envio.anexo_ok:
            arquivo = f'Termo_Zelo_{m.id}.pdf'
        nota(envio.chamado, texto_nota(m, it, arquivo))
        recado = None
        if anexar_ativo_ligado() and it and (it.hostname or '').strip():
            _ok, recado = anexar_ativo_ao_chamado(envio.chamado, it.hostname)
        envio.status, envio.erro = 'Enviado', recado or None
        envio.enviado = datetime.now().isoformat(timespec='seconds')
    except ErroSD as e:
        envio.status, envio.erro = 'Erro', str(e)[:300]
    except Exception as e:  # nunca derruba o lançamento
        envio.status, envio.erro = 'Erro', f'Falha inesperada: {e}'[:300]
    db.session.commit()
    return envio.status == 'Enviado'


def processar(app, ids):
    """Envia em segundo plano, para o clique em Registrar não esperar o Service Desk."""
    from app.models import EnvioSD

    def _enviar_todos():
        for i in ids:
            e = db.session.get(EnvioSD, i)
            if e and e.status != 'Enviado':
                enviar(e)

    def _rodar():
        with app.app_context():
            _enviar_todos()
            db.session.remove()
    if app.config.get('TESTING'):
        _enviar_todos()
    else:
        threading.Thread(target=_rodar, daemon=True).start()


def enfileirar_tudo(app, movs):
    """Chamado pelas telas depois de gravar: termo+nota (se tem chamado) e usuário/estado do ativo (se ligado)."""
    if not configurado():
        return 0
    ids = enfileirar(movs)
    ids += enfileirar_termo(movs)
    if ativos_ligado():
        ids += enfileirar_ativos(movs)
    if ids:
        processar(app, ids)
    return len(ids)
