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
CHAVES = ('sd_url', 'sd_chave', 'sd_ssl', 'sd_ativo', 'sd_ativos')
TIPOS_ENVIO = ('Entrega', 'Empréstimo', 'Devolução')
NOMES_TIPO = {'chamado': 'Termo + nota', 'ativo': 'Ativo', 'termo': 'Termo assinado'}
_cache = {}            # chamado → (quando, dados)
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


def atualizar_ativo(asset_id, usuario_id, estado):
    return _http('PUT', f'/api/v3/asset_assets/{asset_id}',
                 {'asset_asset': {'user': {'id': str(usuario_id)} if usuario_id else None, 'state': {'name': estado}}})


def acao_ativo(m):
    """('In Use', pessoa) na entrega/empréstimo concluídos; ('In Store', None) na devolução; senão None."""
    if m.tipo in ('Entrega', 'Empréstimo') and m.etapa == 'Entregue':
        return 'In Use'
    if m.tipo == 'Devolução':
        return 'In Store'
    return None


def enviar_ativo(envio, m):
    from app.models import Item, Pessoa
    it = db.session.get(Item, m.item) if m.item else None
    host = (envio.alvo or (it.hostname if it else '') or '').strip().upper()
    if not host:
        raise ErroSD('Item sem hostname no Zelo: não dá para achar o ativo no Service Desk')
    a = achar_ativo(host)
    if not a:
        raise ErroSD(f'Ativo {host} não existe no Service Desk')
    estado = acao_ativo(m)
    uid = None
    if estado == 'In Use':
        p = db.session.get(Pessoa, m.matricula) if m.matricula else None
        u = achar_usuario(p.email if p else None, (p.nome if p else m.nome))
        if not u:
            raise ErroSD(f'{m.nome} não encontrado(a) como usuário no Service Desk')
        uid = u.get('id')
    atualizar_ativo(a['id'], uid, estado)
    aviso = ''
    serial = (a.get('serial_number') or a.get('service_tag') or '')
    if it and it.tag and serial and serial.upper() != it.tag.upper():
        aviso = f' (atenção: service tag no SD {serial} ≠ Zelo {it.tag})'
    return f'{host} → {estado}' + (f' com {m.nome}' if uid else '') + aviso


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
    from app.models import EnvioSD, Item
    novos = []
    for m in movs:
        it = db.session.get(Item, m.item) if m.item else None
        if it and it.hostname and acao_ativo(m):
            e = EnvioSD(mov_id=m.id, tipo='ativo', alvo=it.hostname.upper(), status='Pendente',
                        criado=datetime.now().isoformat(timespec='seconds'), tentativas=0)
            db.session.add(e)
            novos.append(e)
    db.session.commit()
    return [e.id for e in novos]


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
    m = db.session.get(Movimentacao, envio.mov_id)
    try:
        if not configurado():
            raise ErroSD('Integração com o Service Desk desligada ou sem chave')
        if not m:
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
        envio.status, envio.erro, envio.enviado = 'Enviado', None, datetime.now().isoformat(timespec='seconds')
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
