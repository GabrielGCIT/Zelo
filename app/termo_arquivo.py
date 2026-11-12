"""Termo assinado guardado no próprio Zelo (no lugar do antigo "link do termo").

Os arquivos ficam em <pasta do banco>/termos e entram no backup diário (cópia incremental em backups/termos)."""
import os
from datetime import date, datetime

from flask import current_app

from app import db
from app.backup import caminho_do_banco

EXTENSOES = {'pdf': b'%PDF', 'png': b'\x89PNG', 'jpg': b'\xff\xd8', 'jpeg': b'\xff\xd8'}
MIME = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}


def pasta():
    p = os.path.join(os.path.dirname(caminho_do_banco(current_app.config['SQLALCHEMY_DATABASE_URI'])), 'termos')
    os.makedirs(p, exist_ok=True)
    return p


def caminho(m):
    if not m.termo_arquivo:
        return None
    c = os.path.join(pasta(), os.path.basename(m.termo_arquivo))
    return c if os.path.exists(c) else None


def guardar_bytes(m, conteudo, ext):
    """Grava o arquivo e aponta o lançamento para ele. Não mexe na situação do termo — quem chama decide.

    Serve tanto para o digitalizado que alguém anexa quanto para o PDF que o Zelo monta com as
    assinaturas da tela; os dois moram no mesmo lugar e entram no mesmo backup.
    """
    antigo = caminho(m)
    novo = f'{m.id}-{datetime.now():%Y%m%d%H%M%S}.{ext}'
    with open(os.path.join(pasta(), novo), 'wb') as fh:
        fh.write(conteudo)
    m.termo_arquivo = novo
    db.session.flush()
    if antigo:      # a versão anterior fica guardada, só deixa de ser a atual
        os.replace(antigo, antigo + '.substituido')
    return novo


def salvar(m, arquivo, quem):
    """Guarda o termo assinado do lançamento e marca o termo como Assinado. Devolve (ok, mensagem)."""
    from app.regras import tocar
    nome = (arquivo.filename or '') if arquivo else ''
    ext = nome.rsplit('.', 1)[-1].lower() if '.' in nome else ''
    if ext not in EXTENSOES:
        return False, 'Envie o termo em PDF, JPG ou PNG'
    conteudo = arquivo.read()
    if not conteudo.startswith(EXTENSOES[ext]):
        return False, 'O arquivo não parece ser um ' + ext.upper() + ' válido'
    if len(conteudo) > 15 * 1024 * 1024:
        return False, 'Arquivo maior que 15 MB'
    guardar_bytes(m, conteudo, ext)
    if m.termo != 'Assinado':
        m.termo, m.data_ass = 'Assinado', m.data_ass or date.today().isoformat()
    db.session.flush()
    tocar([m.item], [m.linha])
    db.session.commit()
    msg = 'Termo assinado guardado'
    # assinou no papel: os pedidos de assinatura na tela perdem a razão de existir
    from app.assinatura import fechar_pendentes
    n = fechar_pendentes(m, f'Termo digitalizado anexado por {quem}')
    if n:
        msg += f'. {n} pedido(s) de assinatura em aberto foram encerrados'
    return True, msg
