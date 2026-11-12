"""Etapa 3: qualidade do cadastro, gráficos do painel e linha do tempo do item."""
from app import db
from app.models import Item, Linha, Movimentacao, Pessoa
from app.qualidade import linha_do_tempo, pessoas_duplicadas, tudo
from app.routes.painel import _garantias, _por_semana


def test_painel_e_fila_abrem(cli):
    for u in ('/', '/fila'):
        assert cli.get(u).status_code == 200


def test_duplicadas_nao_confundem_codigos_numerados(app):
    """FTCTRN0001 e FTCTRN0002 são postos diferentes; José da Silva × José da Silva é duplicata."""
    db.session.add_all([Pessoa(id='Z1', nome='POSTO TESTE 0001', tipo='Posto', situacao='Ativo'),
                        Pessoa(id='Z2', nome='POSTO TESTE 0002', tipo='Posto', situacao='Ativo'),
                        Pessoa(id='Z3', nome='JOSE DA SILVA TESTE', tipo='CLT', situacao='Ativo'),
                        Pessoa(id='Z4', nome='José da Silva Teste', tipo='CLT', situacao='Ativo')])
    db.session.commit()
    textos = ' | '.join(l['texto'] for l in pessoas_duplicadas()['linhas'])
    assert 'POSTO TESTE' not in textos and 'SILVA TESTE' in textos.upper()


def test_achados_tem_porque_e_botao(app, cli):
    achados, total = tudo()
    assert achados and total
    for a in achados:
        assert a['porque'] and a['n'] >= 1
        for l in a['linhas']:
            assert '/' in l['href'] and l['botao']
    h = cli.get('/').get_data(as_text=True)
    assert 'Qualidade do cadastro' in h and achados[0]['titulo'] in h


def test_linha_sem_aparelho_aparece(app):
    ln = Linha.query.filter_by(situacao='Em uso').first()
    ln.aparelho = None
    db.session.commit()
    ids = {a['id'] for a in tudo()[0]}
    assert 'linha' in ids


def test_graficos(app):
    s = _por_semana()
    assert len(s['rotulos']) == 12 == len(s['entregas']) == len(s['devolucoes'])
    assert s['total_e'] == sum(s['entregas']) and s['total_d'] == sum(s['devolucoes'])
    g = _garantias()
    assert sum(x['n'] for x in g) == Item.query.filter(Item.situacao != 'Baixada').count()


def test_linha_do_tempo(app, cli):
    from app.lancamento import gravar
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                           Item.finalidade != 'Pool de empréstimo').first()
    p = Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()
    gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega', 'T')
    gravar([{'acao': 'Devolver', 'item': it.codigo}], 'entrega', 'T')
    movs = Movimentacao.query.filter_by(item=it.codigo).order_by(Movimentacao.id.desc()).all()
    ev = linha_do_tempo(movs, [])
    assert [e['titulo'] for e in ev[:2]] == ['Devolução', 'Entrega']
    assert all('/lancamento/' in e['href'] for e in ev)
    assert 'Linha do tempo' in cli.get(f'/item/{it.codigo}').get_data(as_text=True)
