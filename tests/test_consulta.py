from app.models import Item, Linha, Pessoa


def test_paginas_abrem(app, cli):
    it = Item.query.filter_by(situacao='Em uso').first()
    p = Pessoa.query.first()
    ln = Linha.query.filter_by(situacao='Em uso').first()
    for url in ['/', '/fila', '/itens', '/itens?situacao=Em+estoque&categoria=Notebook', '/pessoas', '/historico',
                '/linhas', '/emprestimos', '/contratos', f'/item/{it.codigo}', f'/pessoa/{p.id}', f'/linha/{ln.numero}',
                f'/buscar?q={it.codigo}', '/buscar?q=silva']:
        r = cli.get(url, follow_redirects=True)
        assert r.status_code == 200, url


def test_sem_login_redireciona(app):
    assert app.test_client().get('/itens').status_code == 302


def test_consulta_nao_edita(app):
    from tests.conftest import entrar
    c = entrar(app.test_client(), 'cons@teste')
    it = Item.query.first()
    assert c.post(f'/item/{it.codigo}', data={'modelo': 'X'}).status_code == 403
    assert c.get('/admin/usuarios').status_code == 403
