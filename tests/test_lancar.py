from app import db
from app.lancamento import conferir, desfazer_ultimo, gravar
from app.models import Item, Linha, MovConsumivel, Movimentacao, Pessoa


def _estoque_nb():
    return Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                             Item.finalidade != 'Pool de empréstimo').first()


def test_entregar_e_devolver(app):
    it = _estoque_nb()
    p = Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()
    r = conferir([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega')
    assert r[0].status in ('ok', 'aviso'), r[0].msg
    res, n, lote = gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega', 'Teste')
    assert n == 1
    db.session.refresh(it)
    assert it.situacao == 'Em uso' and it.matricula == p.id
    # entregar de novo: erro
    assert conferir([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id}], 'entrega')[0].status == 'erro'
    # devolução de notebook pede Recebido por
    assert 'Recebido por' in conferir([{'acao': 'Devolver', 'item': it.codigo}], 'entrega')[0].msg
    gravar([{'acao': 'Devolver', 'item': it.codigo, 'receb_por': 'Adriano Santos'}], 'entrega', 'Teste')
    db.session.refresh(it)
    assert it.situacao == 'Devolvido'


def test_desfazer_apaga_o_lote(app):
    it = _estoque_nb()
    p = Pessoa.query.filter_by(situacao='Ativo').first()
    antes = Movimentacao.query.count()
    gravar([{'acao': 'Reservar', 'item': it.codigo, 'para': p.id, 'tecnico': 'Diogo Mariano', 'acess': 'Nenhum'}],
           'entrega', 'Desfaz')
    assert Movimentacao.query.count() == antes + 1
    n, _ = desfazer_ultimo('Desfaz')
    assert n == 1 and Movimentacao.query.count() == antes
    db.session.refresh(it)
    assert it.situacao == 'Em estoque'


def test_transferir_gera_dois_lancamentos(app):
    it = Item.query.filter(Item.situacao == 'Em uso', Item.categoria == 'Notebook', Item.matricula.isnot(None)).first()
    outro = Pessoa.query.filter(Pessoa.situacao == 'Ativo', Pessoa.id != it.matricula).first()
    res, n, lote = gravar([{'acao': 'Transferir para outra pessoa', 'item': it.codigo, 'para': outro.id}], 'entrega', 'T')
    assert n == 1, res[0].msg
    assert Movimentacao.query.filter_by(lote=lote).count() == 2
    db.session.refresh(it)
    assert it.matricula == outro.id


def test_pessoa_nova_e_kit_de_admissao(app):
    it = _estoque_nb()
    linha = [{'acao': 'Entregar agora', 'item': it.codigo, 'para': 'FULANO DE TESTE · 99999'}]
    r = conferir(linha, 'entrega')[0]
    assert r.status in ('ok', 'aviso', 'erro')
    if r.status == 'erro':          # sem saldo de mouse/teclado no EC na base de teste
        assert 'saldo' in r.msg
        return
    res, n, lote = gravar(linha, 'entrega', 'K')
    assert db.session.get(Pessoa, '99999') is not None
    assert MovConsumivel.query.filter_by(lote=lote).count() >= 1


def test_linha_mobile(app):
    ln = Linha.query.filter_by(situacao='Livre').first()
    p = Pessoa.query.filter_by(situacao='Ativo').first()
    res, n, _ = gravar([{'acao': 'Entregar agora', 'linha': ln.numero, 'para': p.id}], 'mobile', 'M')
    assert n == 1, res[0].msg
    db.session.refresh(ln)
    assert ln.situacao == 'Em uso' and ln.matricula == p.id
    gravar([{'acao': 'Desativar linha', 'linha': ln.numero}], 'mobile', 'M')
    db.session.refresh(ln)
    assert ln.situacao == 'Livre'


def test_baixa_exige_motivo_e_bo(app):
    it = _estoque_nb()
    assert 'Motivo' in conferir([{'acao': 'Baixar', 'item': it.codigo}], 'estoque')[0].msg
    assert 'B.O.' in conferir([{'acao': 'Baixar', 'item': it.codigo, 'motivo': 'Roubo/furto'}], 'estoque')[0].msg


def test_tela_e_api(app, cli):
    assert cli.get('/lancar').status_code == 200
    assert cli.get('/lancar?aba=emprestimo').status_code == 200
    assert cli.get('/lancar/pessoa').status_code == 200
    r = cli.post('/api/lancar/conferir', json={'aba': 'entrega', 'linhas': [{'acao': 'Devolver', 'item': 'naoexiste'}]})
    assert r.json[0]['status'] == 'erro'


def test_termo(app, cli):
    from app.models import Movimentacao
    for tipo in ('Entrega', 'Empréstimo', 'Devolução'):
        m = Movimentacao.query.filter_by(tipo=tipo).order_by(Movimentacao.id.desc()).first()
        r = cli.get(f'/termo?n={m.id}')
        assert r.status_code == 200 and b'TERMO' in r.data
    assert cli.get('/termo?n=999999').status_code == 200
