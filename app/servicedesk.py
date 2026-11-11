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
CHAVES = ('sd_url', 'sd_chave', 'sd_ssl', 'sd_ativo')
TIPOS_ENVIO = ('Entrega', 'Empréstimo', 'Devolução')
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
    if st >= 400 or (j.get('response_status') or {}).get('status') == 'failed':
        rs = j.get('response_status') or {}
        if isinstance(rs, list):
            rs = rs[0] if rs else {}
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


def enfileirar(movs):
    """Cria os envios para os lançamentos que têm chamado. Não envia (ver processar)."""
    from app.models import EnvioSD
    novos = []
    for m in movs:
        if m.chamado and m.tipo in TIPOS_ENVIO and ''.join(c for c in m.chamado if c.isdigit()):
            e = EnvioSD(mov_id=m.id, chamado=''.join(c for c in m.chamado if c.isdigit()), status='Pendente',
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
