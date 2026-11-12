"""Ajuste de cadastro: corrigir o que a planilha trouxe errado, sem inventar movimentação."""
from app import db
from app.ajuste import conferir, gravar
from app.models import Item, Linha, Movimentacao, Pessoa


def _outra_pessoa(menos):
    return Pessoa.query.filter(Pessoa.situacao == 'Ativo', Pessoa.tipo == 'CLT', Pessoa.id != menos).first()


def test_tela_abre(cli):
    it = Item.query.filter(Item.situacao == 'Em uso').first()
    assert cli.get('/ajuste').status_code == 200
    assert 'Ajustar cadastro' in cli.get(f'/ajuste?item={it.codigo}').get_data(as_text=True)
    assert 'Ajustar cadastro' in cli.get(f'/item/{it.codigo}').get_data(as_text=True)


def test_troca_quem_esta_com_o_item(app):
    it = Item.query.filter(Item.situacao == 'Em uso', Item.matricula.isnot(None)).first()
    antes, p = it.matricula, _outra_pessoa(it.matricula)
    ok, msg, m = gravar(it, None, {'situacao': 'Em uso', 'para': p.id, 'motivo': 'Cadastro errado na planilha'}, 'Gabriel')
    assert ok, msg
    db.session.refresh(it)
    assert it.matricula == p.id and it.com_quem == p.nome and it.situacao == 'Em uso' and it.matricula != antes
    assert m.tipo == 'Ajuste' and m.etapa == 'Em uso' and 'com quem' in m.obs and m.resp == 'Gabriel'
    assert db.session.get(Movimentacao, m.id) in Movimentacao.query.filter_by(item=it.codigo).all()


def test_item_que_na_verdade_esta_no_estoque(app):
    it = Item.query.filter(Item.situacao == 'Em uso', Item.matricula.isnot(None)).first()
    erro, _ = conferir(it, None, {'situacao': 'Em estoque', 'para': it.matricula, 'motivo': 'x'})
    assert 'não fica com ninguém' in erro
    ok, msg, _m = gravar(it, None, {'situacao': 'Em estoque', 'motivo': 'Item conferido fisicamente'}, 'T')
    assert ok, msg
    db.session.refresh(it)
    assert it.situacao == 'Em estoque' and not it.com_quem and not it.matricula


def test_exige_motivo_e_mudanca_real(app):
    it = Item.query.filter(Item.situacao == 'Em uso', Item.matricula.isnot(None)).first()
    assert 'por que' in conferir(it, None, {'situacao': 'Em estoque'})[0]
    assert 'é com alguém' in conferir(it, None, {'situacao': 'Em uso', 'motivo': 'x'})[0]
    assert 'já está assim' in conferir(it, None, {'situacao': it.situacao, 'para': it.matricula, 'motivo': 'x'})[0]


def test_ajuste_de_linha(app):
    ln = Linha.query.filter_by(situacao='Em uso').first()
    p = _outra_pessoa(ln.matricula)
    ok, msg, m = gravar(None, ln, {'situacao': 'Em uso', 'para': p.id, 'motivo': 'Linha conferida na operadora'}, 'T')
    assert ok, msg
    db.session.refresh(ln)
    assert ln.com_quem == p.nome and ln.situacao == 'Em uso' and m.etapa == 'Em uso'
    ok, msg, _m = gravar(None, ln, {'situacao': 'Livre', 'motivo': 'Linha conferida na operadora'}, 'T')
    assert ok, msg
    db.session.refresh(ln)
    assert ln.situacao == 'Livre' and not ln.com_quem


def test_ajuste_poe_a_linha_no_aparelho_certo(app):
    it = Item.query.filter(Item.categoria == 'Celular', Item.situacao == 'Em uso', Item.matricula.isnot(None)).first()
    ln = Linha.query.filter(Linha.situacao == 'Em uso', Linha.aparelho != it.codigo).first()
    ok, msg, _m = gravar(it, ln, {'situacao': 'Em uso', 'para': it.matricula, 'motivo': 'Item conferido fisicamente'}, 'T')
    assert ok, msg
    db.session.refresh(it)
    db.session.refresh(ln)
    assert ln.aparelho == it.codigo and it.linha_atual == ln.numero


def test_ajuste_aparece_na_linha_do_tempo(app, cli):
    from app.qualidade import linha_do_tempo
    it = Item.query.filter(Item.situacao == 'Em uso', Item.matricula.isnot(None)).first()
    gravar(it, None, {'situacao': 'A localizar', 'motivo': 'Item conferido fisicamente'}, 'T')
    movs = Movimentacao.query.filter_by(item=it.codigo).order_by(Movimentacao.id.desc()).all()
    assert linha_do_tempo(movs, [])[0]['titulo'] == 'Ajuste'
    assert cli.get(f'/item/{it.codigo}').status_code == 200


def test_desfazer_um_ajuste_volta_tudo(app, cli):
    from app.pendencias import pode_desfazer
    it = Item.query.filter(Item.situacao == 'Em uso', Item.matricula.isnot(None)).first()
    antes = (it.situacao, it.matricula)
    _ok, _msg, m = gravar(it, None, {'situacao': 'A localizar', 'motivo': 'Item conferido fisicamente'}, 'T')
    db.session.refresh(it)
    assert it.situacao == 'A localizar' and pode_desfazer(m)
    cli.post(f'/lancamento/{m.id}', data={'acao': 'desfazer'})
    db.session.expire_all()
    it = db.session.get(Item, it.codigo)
    assert (it.situacao, it.matricula) == antes
