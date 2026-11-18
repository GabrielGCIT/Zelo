import os
import shutil
import tempfile

import pytest

PLANILHA = os.environ.get('ZELO_PLANILHA_TESTE', '')
_CACHE = os.path.join(tempfile.gettempdir(), 'zelo_teste_base.db')


def _montar_cache():
    """Importa a planilha num arquivo à parte e só então o põe no lugar do cache.

    O cache só é montado quando não existe. Antes ele era montado direto no
    nome final: uma importação que falhasse no meio (planilha ausente, por
    exemplo) deixava um banco sem usuários ali, e TODAS as rodadas seguintes o
    reaproveitavam. O login falhava, as telas davam 302, e a suíte acusava
    ~200 erros que não diziam nada sobre a causa.
    """
    from app import create_app, db
    if not PLANILHA or not os.path.exists(PLANILHA):
        pytest.exit(
            'Planilha de teste não encontrada. Defina ZELO_PLANILHA_TESTE com o caminho da '
            '"Gestão de Ativos de TI - Centralizado.xlsx" (fora do repositório). '
            f'Valor atual: {PLANILHA or "<vazio>"}', returncode=1)
    montando = _CACHE + '.montando'
    if os.path.exists(montando):
        os.remove(montando)
    a = create_app('sqlite:///' + montando, testing=True)
    try:
        with a.app_context():
            from app.importar import importar
            importar(PLANILHA, substituir=True, log=lambda *a: None)
            from app.auth import criar_usuario
            criar_usuario('Admin Teste', 'admin@teste', 'senha-forte-1', 'Administrador')
            criar_usuario('Operador Teste', 'op@teste', 'senha-forte-1', 'Operador')
            criar_usuario('Consulta Teste', 'cons@teste', 'senha-forte-1', 'Consulta')
            db.session.remove()
            # No Windows o arquivo aberto não pode ser renomeado: soltar a conexão antes.
            db.engine.dispose()
    except BaseException:
        with a.app_context():
            db.engine.dispose()
        if os.path.exists(montando):
            os.remove(montando)
        raise
    os.replace(montando, _CACHE)


@pytest.fixture()
def app():
    """Banco com a planilha real importada (copiado de um cache para cada teste ser isolado)."""
    from app import create_app, db
    if not os.path.exists(_CACHE):
        _montar_cache()
    tmp = tempfile.mkdtemp()
    caminho = os.path.join(tmp, 'z.db')
    shutil.copy(_CACHE, caminho)
    a = create_app('sqlite:///' + caminho, testing=True)
    a.config['SERVER_NAME'] = 'localhost'      # deixa url_for funcionar fora de uma requisição
    with a.app_context():
        yield a
        db.session.remove()
        db.engine.dispose()
    shutil.rmtree(tmp, ignore_errors=True)


def entrar(client, email='op@teste'):
    client.post('/login', data={'email': email, 'senha': 'senha-forte-1'})
    return client


@pytest.fixture()
def cli(app):
    return entrar(app.test_client())


@pytest.fixture()
def fluxo_preparacao(app):
    """Liga o fluxo de preparação, que vem desligado: sem ele a devolução volta direto ao estoque
    e nenhum notebook chega ao quadro de preparação."""
    from app import db
    from app.models import Config
    db.session.merge(Config(chave='fluxo_preparacao', valor='2026-01-01'))
    db.session.commit()
    return '2026-01-01'
