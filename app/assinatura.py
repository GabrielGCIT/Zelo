"""Assinatura digital do termo — duas vias, presencial ou por link.

O termo de responsabilidade só vale com duas assinaturas: a de quem recebe o equipamento e a de
quem responde pela empresa (é essa que libera o ativo). Antes, as duas saíam no papel; aqui cada
uma vira um pedido com link próprio, e o pedido serve para os dois casos sem mudar de tela:

- presencial: abre o link no tablet e a pessoa assina ali, com caneta ou com o dedo;
- a distância: manda o link para quem assina pela empresa, que abre de onde estiver.

Assinar no papel continua valendo: quem anexar o termo digitalizado fecha os pedidos em aberto
(`app.termo_arquivo`), porque as duas vias já estão no documento que foi guardado.

O que dá peso à via não é o desenho — é o registro: quem assinou, quando, de qual endereço e o
hash do texto do termo naquele instante. Se alguém corrigir o lançamento depois, o hash deixa de
bater e o Zelo mostra que o papel assinado não é mais o que está na tela.
"""
import hashlib
import io
import secrets
from datetime import date, datetime, timedelta

from flask import url_for

from app import db
from app.models import Assinatura, Movimentacao, cfg, cfg_lista

PAPEIS = ('colaborador', 'empresa')
ROTULO = {'colaborador': 'Colaborador(a)', 'empresa': 'Pela empresa'}
MAX_PNG = 400 * 1024                 # um traço de assinatura não passa disso
MIN_TINTA = 120                      # pixels com tinta: abaixo disso é risco acidental ou tela em branco
PNG_MAGICO = b'\x89PNG\r\n\x1a\n'


# ------------------------------------------------------------------ identidade do termo
def hash_do_termo(d):
    """sha256 do conteúdo do termo. Muda se o lançamento for corrigido depois de assinado."""
    partes = [str(d.get(k) or '') for k in ('num', 'tipo', 'titulo', 'nome', 'matricula_fmt', 'equipamento', 'linha',
                                            'acessorios', 'periodo', 'chamado', 'abertura', 'p1', 'p2', 'obs', 'fecho')]
    return hashlib.sha256('\x1f'.join(partes).encode('utf-8')).hexdigest()


def codigo(a):
    """Código curto de conferência, impresso no PDF. Vem do token, que não aparece no documento."""
    return hashlib.sha256((a.token or '').encode()).hexdigest()[:10].upper()


def termo_do_lancamento(m):
    from app.routes.termo import montar
    d, _erro = montar(str(m.id))
    return d


# ------------------------------------------------------------------ pedidos
def quem_assina(m, papel):
    """Nome sugerido para a via."""
    if papel == 'colaborador':
        return m.nome or m.local or ''
    lista = cfg_lista('assinantes_empresa')
    return lista[0] if lista else (cfg('empresa') or '')


def vias(m):
    """{papel: assinatura ativa ou None} — a cancelada não conta."""
    todas = (Assinatura.query.filter(Assinatura.mov_id == m.id, Assinatura.cancelado.is_(None))
             .order_by(Assinatura.id.desc()).all())
    saida = {p: None for p in PAPEIS}
    for a in todas:
        if a.papel in saida and saida[a.papel] is None:
            saida[a.papel] = a
    return saida


def pedir(m, papel, nome=None, quem='', contato='', dias=None):
    """Cria (ou refaz) o pedido de uma via. Devolve (assinatura, mensagem)."""
    if papel not in PAPEIS:
        return None, 'Via desconhecida'
    if m.tipo not in ('Entrega', 'Empréstimo', 'Devolução'):
        return None, 'Esse tipo de lançamento não tem termo para assinar'
    atual = vias(m)[papel]
    if atual and atual.assinado:
        return atual, 'Essa via já está assinada'
    if atual:                                   # ainda pendente: refaz com token novo
        atual.cancelado = datetime.now().isoformat(timespec='seconds')
        atual.motivo = 'Link refeito'
    d = int(dias or cfg('dias_link_assinatura') or 7)
    a = Assinatura(mov_id=m.id, papel=papel, nome=(nome or quem_assina(m, papel)).strip(),
                   matricula=m.matricula if papel == 'colaborador' else None, contato=(contato or '').strip() or None,
                   token=secrets.token_urlsafe(32), criado=datetime.now().isoformat(timespec='seconds'),
                   criado_por=quem, expira=(date.today() + timedelta(days=max(1, d))).isoformat())
    db.session.add(a)
    db.session.commit()
    return a, ('Link de assinatura gerado' if not atual else 'Link refeito: o anterior deixou de valer')


def cancelar(a, motivo, quem=''):
    a.cancelado = datetime.now().isoformat(timespec='seconds')
    a.motivo = (motivo or 'Cancelado')[:150] + (f' por {quem}' if quem else '')
    db.session.commit()


def fechar_pendentes(m, motivo):
    """Usado quando o termo é resolvido por fora (digitalizado anexado)."""
    n = 0
    for a in Assinatura.query.filter(Assinatura.mov_id == m.id, Assinatura.assinado.is_(None),
                                     Assinatura.cancelado.is_(None)).all():
        a.cancelado = datetime.now().isoformat(timespec='seconds')
        a.motivo = motivo[:150]
        n += 1
    if n:
        db.session.commit()
    return n


LOCAIS = ('127.0.0.1', 'localhost', '::1', '0.0.0.0')


def link(a, externo=True):
    """O link que vai para quem assina.

    Com `url_base` configurado, o endereço sai sempre no nome que a rede conhece. Sem ele, sai o
    endereço que o navegador está usando — e aí, se alguém abrir o Zelo no próprio servidor, o
    link copiado só funciona naquela máquina. `local()` existe para avisar disso na tela.
    """
    caminho = url_for('assinar.pagina', token=a.token)
    base = (cfg('url_base') or '').strip().rstrip('/')
    if base:
        return base + caminho
    return url_for('assinar.pagina', token=a.token, _external=externo)


def local(url):
    """True se o endereço só funciona na máquina onde o Zelo está rodando."""
    from urllib.parse import urlparse
    return (urlparse(url or '').hostname or '') in LOCAIS


# ------------------------------------------------------------------ abrir e assinar
def abrir(token):
    """(assinatura, lançamento, erro) para a página pública."""
    a = Assinatura.query.filter_by(token=(token or '').strip()).first()
    if not a:
        return None, None, 'Este link não existe. Confira se foi copiado inteiro.'
    m = db.session.get(Movimentacao, a.mov_id)
    if not m:
        return a, None, 'O lançamento deste termo não existe mais.'
    if a.cancelado:
        return a, m, f'Este link foi cancelado ({a.motivo or "sem motivo registrado"}). Peça um novo à equipe de TI.'
    if a.assinado:
        return a, m, ''                       # já assinada: a página mostra o comprovante
    if a.expira and a.expira < date.today().isoformat():
        return a, m, 'Este link venceu. Peça um novo à equipe de TI.'
    return a, m, ''


def _png_valido(dados):
    """(bytes, erro). Recusa o que não for PNG, o que for grande demais e a tela em branco."""
    if not dados:
        return None, 'Assine no quadro antes de confirmar'
    if isinstance(dados, str):
        cab, _sep, b64 = dados.partition(',')
        if 'image/png' not in cab or not b64:
            return None, 'Formato de assinatura não aceito'
        import base64
        try:
            dados = base64.b64decode(b64, validate=True)
        except Exception:                      # noqa: BLE001
            return None, 'Não consegui ler o desenho da assinatura'
    if not dados.startswith(PNG_MAGICO):
        return None, 'Formato de assinatura não aceito'
    if len(dados) > MAX_PNG:
        return None, 'Assinatura grande demais'
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(dados))
        im.verify()
        im = Image.open(io.BytesIO(dados)).convert('RGBA')
        if im.width > 2400 or im.height > 1200:
            return None, 'Assinatura com tamanho fora do esperado'
        # o quadro manda PNG com fundo transparente, então tinta = pixel opaco. Se vier um PNG
        # sem transparência (outro navegador, outra ferramenta), vale o pixel escuro.
        alfa = im.getchannel('A').histogram()
        if alfa[255] == im.width * im.height:
            tinta = sum(im.convert('L').histogram()[:160])
        else:
            tinta = sum(alfa[41:])
        if tinta < MIN_TINTA:
            return None, 'O quadro está praticamente em branco: assine antes de confirmar'
    except (ImportError, ModuleNotFoundError):
        pass                                   # sem Pillow, fica a conferência dos bytes
    except Exception:                          # noqa: BLE001
        return None, 'Não consegui ler o desenho da assinatura'
    return dados, None


def assinar(a, m, desenho, nome_confirmado, ip='', agente=''):
    """Grava a via. Devolve (ok, mensagem, fechou_o_termo)."""
    if a.assinado:
        return False, 'Esta via já foi assinada', False
    if a.cancelado:
        return False, 'Este link foi cancelado', False
    nome = (nome_confirmado or '').strip()
    if len(nome) < 3:
        return False, 'Escreva o seu nome completo', False
    png, erro = _png_valido(desenho)
    if erro:
        return False, erro, False
    d = termo_do_lancamento(m)
    a.traco = png
    a.assinante = nome[:150]
    a.assinado = datetime.now().isoformat(timespec='seconds')
    a.ip = (ip or '')[:45]
    a.agente = (agente or '')[:200]
    a.hash_termo = hash_do_termo(d) if d else None
    db.session.commit()
    fechou = False
    if completo(m):
        fechou = fechar(m)[0]
    return True, 'Assinatura registrada', fechou


def completo(m):
    v = vias(m)
    return all(v[p] and v[p].assinado for p in PAPEIS)


def conferir(m):
    """Avisos sobre as vias já assinadas (termo alterado depois da assinatura)."""
    d = termo_do_lancamento(m)
    agora = hash_do_termo(d) if d else None
    fora = [a for a in vias(m).values() if a and a.assinado and a.hash_termo and agora and a.hash_termo != agora]
    if not fora:
        return []
    quem = ', '.join(a.assinante or a.nome for a in fora)
    return [f'O termo foi alterado depois de assinado por {quem}. Colha as assinaturas de novo ou desfaça a correção.']


# ------------------------------------------------------------------ fechamento
def fechar(m):
    """Com as duas vias assinadas: gera o PDF, guarda como termo assinado e manda ao chamado."""
    from app.regras import tocar
    from app.termo_arquivo import guardar_bytes
    from app.termo_pdf import gerar_pdf
    if not completo(m):
        return False, 'Ainda falta uma das vias'
    d = termo_do_lancamento(m)
    if not d:
        return False, 'Não consegui montar o termo deste lançamento'
    pdf = gerar_pdf(d, assinaturas=[vias(m)[p] for p in PAPEIS])
    guardar_bytes(m, pdf, 'pdf')
    if m.termo != 'Assinado':
        m.termo = 'Assinado'
    m.data_ass = m.data_ass or date.today().isoformat()
    db.session.flush()
    tocar([m.item], [m.linha])
    db.session.commit()
    _mandar_ao_chamado(m)
    return True, 'Termo assinado pelas duas partes e guardado no Zelo'


def _mandar_ao_chamado(m):
    try:
        from flask import current_app
        from app import servicedesk as sd
        if m.chamado and sd.configurado():
            ids = sd.enfileirar_termo([m])
            if ids:
                sd.processar(current_app._get_current_object(), ids)
    except Exception:                          # noqa: BLE001  — o termo já está guardado; o envio reenfileira
        current_app.logger.exception('Falha ao mandar o termo assinado ao chamado')


# ------------------------------------------------------------------ listagem
def pendentes(limite=200):
    """Vias ainda não assinadas, da mais antiga para a mais nova (para a fila e os lembretes)."""
    return (Assinatura.query.filter(Assinatura.assinado.is_(None), Assinatura.cancelado.is_(None))
            .order_by(Assinatura.id).limit(limite).all())
