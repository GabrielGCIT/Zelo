import os
import shutil
import tempfile

import pytest

PLANILHA = os.environ.get('ZELO_PLANILHA_TESTE',
                          '/tmp/claude-0/-home-claude/362516bd-b636-5afb-874e-23c4b265653a/scratchpad/planilha_0911.xlsx')
_CACHE = os.path.join(tempfile.gettempdir(), 'zelo_teste_base.db')


@pytest.fixture()
def app():
    """Banco com a planilha real importada (copiado de um cache para cada teste ser isolado)."""
    from app import create_app, db
    if not os.path.exists(_CACHE):
        a = create_app('sqlite:///' + _CACHE, testing=True)
        with a.app_context():
            from app.importar import importar
            importar(PLANILHA, substituir=True, log=lambda *a: None)
            from app.auth import criar_usuario
            criar_usuario('Admin Teste', 'admin@teste', 'senha-forte-1', 'Administrador')
            criar_usuario('Operador Teste', 'op@teste', 'senha-forte-1', 'Operador')
            criar_usuario('Consulta Teste', 'cons@teste', 'senha-forte-1', 'Consulta')
            db.session.remove()
            db.engine.dispose()
    tmp = tempfile.mkdtemp()
    caminho = os.path.join(tmp, 'z.db')
    shutil.copy(_CACHE, caminho)
    a = create_app('sqlite:///' + caminho, testing=True)
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
