"""Etapa 4 — agilidade: bipagem, etiqueta, busca rápida, lembretes e desligamento."""
from datetime import date, timedelta

from app import db
from app.bipagem import MODOS, fila, gravar_fila, linha_do_item
from app.desligamento import devolver_tudo, o_que_tem, pendentes, total
from app.etiqueta import PADROES, barras, codigo_do_item, svg
from app.lancamento import gravar
from app.models import Consumivel, EmprestimoAcessorio, Item, Linha, MovConsumivel, Movimentacao, Pessoa


# ------------------------------------------------------------------ etiqueta
def test_code128_confere_com_a_tabela_padrao():
    """Golden conferido módulo a módulo contra o python-barcode (conjunto B, com dígito verificador)."""
    assert barras('FTCTRN0001') == ('2112141323112133111313212133112311311133211231221231221231221232211311412331112')
    assert barras('A') == '2112141113231311232331112'
    assert barras('') == '' and barras(None) == ''
    assert len(PADROES) == 107 and all(sum(int(c) for c in p) == 11 for p in PADROES[:106])


def test_etiqueta_svg(app):
    it = Item.query.filter(Item.plaqueta.isnot(None)).first()
    assert codigo_do_item(it) == it.plaqueta
    s = svg(codigo_do_item(it))
    assert s.startswith('<svg') and '<rect' in s and it.plaqueta in s
    sem = Item.query.filter((Item.plaqueta.is_(None)) | (Item.plaqueta == '')).first()
    assert codigo_do_item(sem) == sem.codigo          # sem plaqueta, o código do Zelo serve


def test_tela_de_etiquetas(app, cli):
    its = Item.query.limit(3).all()
    r = cli.get('/etiquetas?' + '&'.join(f'c={i.codigo}' for i in its) + '&copias=2')
    assert r.status_code == 200
    h = r.data.decode()
    assert h.count('<svg') == 6                        # 3 itens × 2 vias
    assert cli.get('/etiquetas').status_code == 302     # sem códigos, volta para a lista


# ------------------------------------------------------------------ bipagem
def _nb():
    return Item.query.filter(Item.situacao == 'Em uso', Item.categoria == 'Notebook',
                             Item.finalidade != 'Pool de empréstimo', Item.matricula.isnot(None)).first()


def test_campo_comum_vai_so_onde_cabe(app):
    """Recebido por é recusado pelo motor em celular: a fila não manda esse campo para ele."""
    nb = _nb()
    cel = Item.query.filter(Item.categoria == 'Celular', Item.situacao == 'Em uso').first()
    c = {'receb_por': 'Adriano Santos', 'obs': 'chegou junto'}
    assert linha_do_item('devolver', nb, c)['receb_por'] == 'Adriano Santos'
    assert 'receb_por' not in linha_do_item('devolver', cel, c)
    assert linha_do_item('devolver', cel, c)['obs'] == 'chegou junto'
    assert linha_do_item('site', nb, {'destino': 'RJ'})['obs'] == 'RJ'     # o motor lê o destino na observação


def test_fila_de_devolucao_mista(app):
    nb, cel = _nb(), Item.query.filter(Item.categoria == 'Celular', Item.situacao == 'Em uso').first()
    r = fila('devolver', [nb.plaqueta or nb.codigo, cel.codigo, cel.codigo, 'NAO-EXISTE-123'],
             {'receb_por': 'Adriano Santos'})
    assert [l['status'] for l in r['linhas']] == ['ok', 'ok', 'repetido', 'erro']
    assert r['resumo'] == {'ok': 2, 'aviso': 0, 'erro': 1, 'total': 3}
    assert 'Não encontrei' in r['linhas'][3]['msg']
    assert r['linhas'][0]['item']['codigo'] == nb.codigo       # achou pela plaqueta


def test_fila_grava_so_o_que_passa(app):
    nb = _nb()
    estoque = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook').first()
    n, lote, saida = gravar_fila('devolver', [nb.codigo, estoque.codigo], {'receb_por': 'Adriano Santos'}, 'T')
    assert n == 1 and lote
    por = {l['lido']: l for l in saida['linhas']}
    assert por[nb.codigo]['gravada'] and por[nb.codigo]['nums']
    assert not por[estoque.codigo]['gravada'] and 'já está' in por[estoque.codigo]['msg']
    db.session.refresh(nb)
    assert nb.situacao == 'Devolvido'
    m = db.session.get(Movimentacao, por[nb.codigo]['nums'][-1])
    assert m.tipo == 'Devolução' and m.receb_por == 'Adriano Santos' and m.lote == lote


def test_fila_de_entrega_para_uma_pessoa(app):
    p = Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()
    livres = Item.query.filter(Item.situacao == 'Em estoque', Item.finalidade != 'Pool de empréstimo').limit(2).all()
    r = fila('entregar', [i.codigo for i in livres], {'para': p.id, 'acess': 'Nenhum'})
    assert all(l['status'] in ('ok', 'aviso') for l in r['linhas']), [l['msg'] for l in r['linhas']]
    n, _lote, _s = gravar_fila('entregar', [i.codigo for i in livres], {'para': p.id, 'acess': 'Nenhum'}, 'T')
    assert n == 2
    for i in livres:
        db.session.refresh(i)
        assert i.situacao == 'Em uso' and i.matricula == p.id


def test_conferir_prateleira(app):
    site = Item.query.filter(Item.situacao == 'Em estoque', Item.site.isnot(None)).first().site
    naprat = Item.query.filter(Item.situacao == 'Em estoque', Item.site == site).limit(3).all()
    fora = _nb()
    r = fila('conferir', [naprat[0].codigo, fora.codigo], {'site': site})
    assert r['linhas'][0]['status'] == 'ok' and 'Confere' in r['linhas'][0]['msg']
    assert r['linhas'][1]['status'] == 'aviso' and 'Em uso' in r['linhas'][1]['msg']
    faltam = {i['codigo'] for i in r['faltando']}
    assert naprat[1].codigo in faltam and naprat[0].codigo not in faltam
    assert r['esperado'] >= len(naprat)
    # conferência não grava nada
    n, lote, _s = gravar_fila('conferir', [naprat[0].codigo], {'site': site}, 'T')
    assert n == 0 and lote is None


def test_telas_e_api_da_bipagem(app, cli):
    assert cli.get('/bipar').status_code == 200
    assert cli.get('/bipar?modo=conferir').status_code == 200
    assert cli.get('/bipar?modo=inventado').status_code == 200      # modo errado cai no padrão
    it = _nb()
    r = cli.post('/api/bipar/fila', json={'modo': 'devolver', 'codigos': [it.codigo], 'comum': {}})
    assert r.status_code == 200 and r.json['linhas'][0]['item']['codigo'] == it.codigo
    r = cli.post('/api/bipar/gravar', json={'modo': 'devolver', 'codigos': [it.codigo], 'comum': {}})
    assert r.json['gravadas'] == 1 and 'movs' not in r.json


def test_selecao_em_lote_na_lista_de_itens(app, cli):
    """A lista de Itens manda a seleção para a fila de bipagem."""
    its = Item.query.limit(2).all()
    h = cli.get('/itens').data.decode()
    assert 'name="codigo"' in h and '/bipar' in h
    r = cli.post('/bipar', data={'modo': 'ec', 'codigo': [i.codigo for i in its]})
    assert r.status_code == 200
    for i in its:
        assert i.codigo in r.data.decode()


# ------------------------------------------------------------------ busca rápida
def test_busca_acha_e_oferece_acao(app, cli):
    it = _nb()
    j = cli.get('/api/busca?q=' + (it.plaqueta or it.codigo)).json
    g = next(x for x in j['grupos'] if x['titulo'] == 'Itens')
    assert g['linhas'][0]['cod'] == it.codigo
    rot = [a['rotulo'] for a in g['linhas'][0]['acoes']]
    assert 'Devolver' in rot and 'Ajustar cadastro' in rot      # ações que cabem em item Em uso

    p = db.session.get(Pessoa, it.matricula)
    j = cli.get('/api/busca?q=' + p.nome.split(' ')[0]).json
    assert any(x['titulo'] == 'Pessoas' for x in j['grupos'])

    m = Movimentacao.query.first()
    j = cli.get(f'/api/busca?q=Nº {m.id}').json
    assert any(x['titulo'] == 'Lançamento' and x['linhas'][0]['cod'] == (m.data or '') for x in j['grupos'])


def test_busca_acha_telas_e_lista_atalhos(app, cli):
    j = cli.get('/api/busca?q=codigo de barras').json
    ir = next(x for x in j['grupos'] if x['titulo'] == 'Ir para')
    assert any(l['titulo'] == 'Bipar' for l in ir['linhas'])
    vazia = cli.get('/api/busca?q=').json
    assert vazia['grupos'][0]['titulo'] == 'Ir para' and len(vazia['grupos'][0]['linhas']) >= 5
    assert cli.get('/api/busca?q=zzzznaoexistezzz').json['grupos'] == []


def test_busca_de_linha_por_numero(app, cli):
    ln = Linha.query.filter(Linha.situacao == 'Em uso').first()
    j = cli.get('/api/busca?q=' + ln.numero[-8:]).json
    g = next(x for x in j['grupos'] if x['titulo'] == 'Linhas')
    assert any(l['cod'] == ln.numero for l in g['linhas'])


# ------------------------------------------------------------------ lembretes
def test_lembretes_cobram_o_que_passou_do_prazo(app):
    from app import lembretes as lb
    lb.esquecer()
    pool = Item.query.filter_by(finalidade='Pool de empréstimo', situacao='Em estoque').first()
    p = Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()
    res, n, _l = gravar([{'acao': 'Emprestar', 'item': pool.codigo, 'para': p.id, 'prazo': '30'}], 'emprestimo', 'T')
    assert n == 1, res[0].msg
    m = res[0].movs[0]
    m.prazo = (date.today() - timedelta(days=5)).isoformat()      # vencido há 5 dias
    db.session.commit()
    from app.regras import recalcular_item
    recalcular_item(pool)
    db.session.commit()

    L, total_n = lb.tudo()
    venc = next(x for x in L if x['chave'] == 'emprestimo_vencido')
    assert venc['n'] >= 1 and venc['urgencia'] == 'alta' and venc['acao'] and venc['porque']
    assert L[0]['urgencia'] == 'alta'                              # urgentes primeiro
    assert total_n >= venc['n']
    assert all(x['n'] > 0 for x in L)
    assert lb.alta(L) and all(x['urgencia'] == 'alta' for x in lb.alta(L))


def test_contagem_de_lembretes_usa_cache(app):
    from app import lembretes as lb
    lb.esquecer()
    a = lb.contagem(agora=1000.0)
    assert a == lb.contagem(agora=1000.0 + lb.VALIDADE - 1)        # dentro da validade, não recalcula
    assert isinstance(lb.contagem(agora=1000.0 + lb.VALIDADE + 1), tuple)


def test_painel_mostra_os_lembretes(app, cli):
    h = cli.get('/').data.decode()
    assert 'Precisa de alguém' in h
    assert 'Minha fila' in h


# ------------------------------------------------------------------ desligamento
def _desligado_com_tudo(app):
    """Monta uma pessoa desligada com notebook, linha solta, kit e acessório."""
    p = Pessoa.query.filter(Pessoa.situacao == 'Ativo', Pessoa.tipo == 'CLT',
                            ~Pessoa.id.in_(db.session.query(Item.matricula).filter(Item.matricula.isnot(None)))).first()
    nb = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                           Item.finalidade != 'Pool de empréstimo').first()
    fab = nb.fabricante or 'Dell'
    for nome in (f'Mouse sem fio – {fab}', f'Kit teclado + mouse sem fio – {fab}'):
        if not Consumivel.query.filter_by(nome=nome).first():
            db.session.add(Consumivel(nome=nome, item=nome.split(' – ')[0], marca=fab))
        db.session.add(MovConsumivel(data='2026-11-01', consumivel=nome, site='EC', movimento='Entrada', qtd=9, resp='T'))
    db.session.commit()
    res, n, _l = gravar([{'acao': 'Entregar agora', 'item': nb.codigo, 'para': p.id, 'acess': 'Mouse + teclado'}],
                        'entrega', 'T')
    assert n == 1, res[0].msg
    ln = Linha.query.filter(Linha.situacao == 'Livre').first()
    res, n, _l = gravar([{'acao': 'Entregar agora', 'linha': ln.numero, 'para': p.id}], 'mobile', 'T')
    assert n == 1, res[0].msg
    ea = EmprestimoAcessorio(data='2026-11-01', consumivel=f'Mouse sem fio – {fab}', qtd=1, matricula=p.id, nome=p.nome,
                             prazo='2026-12-01', resp='T')
    db.session.add(ea)
    p.situacao = 'Desligado'
    db.session.commit()
    return p, nb, ln, ea


def test_fila_do_desligamento_junta_tudo(app):
    p, nb, ln, ea = _desligado_com_tudo(app)
    t = o_que_tem(p.id)
    assert nb.codigo in [i.codigo for i in t['itens']]
    assert ln.numero in [l.numero for l in t['linhas']]           # linha sem aparelho: entra sozinha
    assert t['kit'] and ea.id in [x.id for x in t['acess']]
    assert total(t) >= 4
    assert p.id in [f['p'].id for f in pendentes()]


def test_desligamento_devolve_tudo_de_uma_vez(app):
    p, nb, ln, ea = _desligado_com_tudo(app)
    t = o_que_tem(p.id)
    ok, msg, det = devolver_tudo(p, {
        'itens': [nb.codigo], 'linhas': {ln.numero: 'Devolver'},
        'kit': [(str(m), c) for m, c, _q in t['kit']], 'acess': [ea.id],
        'receb_por': 'Adriano Santos', 'obs': 'saída'}, 'T')
    assert ok, msg
    assert 'Nada mais consta' in msg, msg
    db.session.refresh(nb)
    db.session.refresh(ln)
    db.session.refresh(ea)
    assert nb.situacao == 'Devolvido'                              # notebook vai para a preparação
    assert ln.situacao == 'Livre' and ea.devolvido
    assert not total(o_que_tem(p.id))
    assert p.id not in [f['p'].id for f in pendentes()]
    m = Movimentacao.query.filter_by(item=nb.codigo).order_by(Movimentacao.id.desc()).first()
    assert m.tipo == 'Devolução' and m.motivo == 'Desligamento' and m.receb_por == 'Adriano Santos'


def test_desligamento_respeita_o_que_nao_foi_marcado(app):
    p, nb, ln, _ea = _desligado_com_tudo(app)
    ok, msg, _d = devolver_tudo(p, {'itens': [nb.codigo], 'linhas': {ln.numero: 'Deixar com a pessoa'}}, 'T')
    assert ok
    db.session.refresh(ln)
    assert ln.situacao == 'Em uso'                                 # ninguém pediu para devolver a linha
    assert 'Ainda constam' in msg
    assert not devolver_tudo(p, {}, 'T')[0]                        # nada marcado


def test_telas_do_desligamento(app, cli):
    p, nb, ln, _ea = _desligado_com_tudo(app)
    assert cli.get('/desligamentos').status_code == 200
    h = cli.get(f'/desligamento/{p.id}').data.decode()
    assert nb.codigo in h and 'Devolver o que está marcado' in h
    r = cli.post(f'/desligamento/{p.id}', data={'item': [nb.codigo], 'receb_por': 'Adriano Santos'},
                 follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(nb)
    assert nb.situacao == 'Devolvido'
    assert cli.get('/desligamento/NAO-EXISTE').status_code == 404


def test_todos_os_modos_tem_rotulo_e_explicacao():
    for k, (tit, ico, acao, campos, exp) in MODOS.items():
        assert tit and ico.startswith('fa-') and isinstance(campos, list) and exp.endswith('.')
        assert (acao is None) == (k == 'conferir')
