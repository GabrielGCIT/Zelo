"""Etapa 1: lançamento em cards, pendências no lugar de travas, corrigir e desfazer um lançamento."""
from app import db
from app.acompanhar import preparar
from app.lancamento import acoes_possiveis, gravar
from app.manutencao import registrar
from app.models import Item, Movimentacao, Pessoa
from app.pendencias import abertas, pode_desfazer, texto


def _nb():
    return Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                             Item.finalidade != 'Pool de empréstimo').first()


def _p():
    return Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()


def test_telas(cli):
    for u in ('/lancar', '/lancar?card=mobile', '/lancar?card=acessorio', '/lancar/lote', '/lancar/lote?aba=estoque', '/fila',
              '/fila?pend=todas'):
        assert cli.get(u).status_code == 200, u


def test_contexto_mostra_so_o_que_cabe(app, cli):
    it = _nb()
    j = cli.get(f'/api/lancar/contexto?card=mobile&item={it.codigo}').json
    assert j['card'] == 'notebook' and 'Entregar agora' in j['acoes'] and 'Devolver' not in j['acoes']
    uso = Item.query.filter(Item.situacao == 'Em uso', Item.categoria == 'Notebook', Item.finalidade != 'Pool de empréstimo').first()
    a = cli.get(f'/api/lancar/contexto?card=notebook&item={uso.codigo}').json['acoes']
    assert 'Devolver' in a and 'Transferir para outra pessoa' in a and 'Entregar agora' not in a
    pool = Item.query.filter_by(finalidade='Pool de empréstimo', situacao='Em estoque').first()
    j = cli.get(f'/api/lancar/contexto?card=notebook&item={pool.codigo}').json
    assert j['card'] == 'pool' and j['acoes'] == ['Emprestar']
    assert cli.get('/api/lancar/contexto?card=notebook&item=NAOEXISTE123').json['achou_item'] is False
    assert 'Baixar' in acoes_possiveis(it, None, 'estoque')[0]


def test_gravar_pelo_card_e_pendencias(app, cli):
    it, p = _nb(), _p()
    r = cli.post('/api/lancar/gravar', json={'card': 'notebook', 'linhas': [
        {'acao': 'Reservar', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]}).json     # sem técnico, sem chamado
    assert r['gravadas'] == 1
    m = db.session.get(Movimentacao, r['resultados'][0]['nums'][0])
    assert set(texto(m)) == {'Nº do chamado', 'Técnico'}
    assert any(x.id == m.id for x, _f in abertas('Operador Teste'))            # aparece na fila de quem lançou
    assert 'Técnico' in cli.get('/fila').get_data(as_text=True)
    # completa pela tela do lançamento: some da fila e fica na auditoria
    assert cli.post(f'/lancamento/{m.id}', data={'chamado': 'INC9', 'tecnico': 'Diogo Mariano'}).status_code == 302
    db.session.refresh(m)
    assert texto(m) == [] and m.chamado == 'INC9'
    from app.models import LogAuditoria
    assert 'Nº do chamado: (vazio) → INC9' in LogAuditoria.query.order_by(LogAuditoria.id.desc()).first().detalhe


def test_devolver_sem_recebido_por_vira_pendencia(app):
    it, p = _nb(), _p()
    gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega', 'T')
    res, n, _ = gravar([{'acao': 'Devolver', 'item': it.codigo}], 'entrega', 'T')
    assert n == 1 and texto(res[0].movs[0]) == ['Recebido por']


def test_desfazer_so_o_ultimo(app, cli):
    it, p = _nb(), _p()
    r1, _, _ = gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega', 'T')
    r2, _, _ = gravar([{'acao': 'Devolver', 'item': it.codigo}], 'entrega', 'T')
    m1, m2 = r1[0].movs[0], r2[0].movs[0]
    assert not pode_desfazer(m1) and pode_desfazer(m2)
    cli.post(f'/lancamento/{m1.id}', data={'acao': 'desfazer'})
    assert db.session.get(Movimentacao, m1.id) is not None                # recusou
    cli.post(f'/lancamento/{m2.id}', data={'acao': 'desfazer'})
    db.session.expire_all()
    assert db.session.get(Movimentacao, m2.id) is None and db.session.get(Item, it.codigo).situacao == 'Em uso'


def test_liberar_sem_todas_as_marcas(app):
    it, p = _nb(), _p()
    gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega', 'T')
    gravar([{'acao': 'Devolver', 'item': it.codigo}], 'entrega', 'T')
    ok, msg = preparar(it, dict(veio_fonte='Não', veio_mouse='Não', veio_teclado='Não', estado='Bom', preventiva='Sim',
                                formatado='Sim', liberar='Sim'), 'T')
    assert ok and 'sem: Fonte, Mouse, Teclado, Embalado' in msg, msg
    db.session.refresh(it)
    assert it.situacao == 'Em estoque'


def test_fechar_manutencao_sem_descricao(app):
    it = Item.query.filter(Item.situacao == 'Em uso', Item.categoria == 'Notebook').first()
    assert registrar({'acao': 'Abrir ocorrência', 'item': it.codigo, 'defeito': 'Tela'}, 'T')[0]
    assert registrar({'acao': 'Fechar ocorrência', 'item': it.codigo}, 'T')[0]


def test_ficha_do_item_tem_acoes(app, cli):
    it = _nb()
    h = cli.get(f'/item/{it.codigo}').get_data(as_text=True)
    assert 'acao=Entregar+agora' in h or 'acao=Entregar%20agora' in h
