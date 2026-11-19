import io
import os

import openpyxl
import pytest

from app import db
from app.acompanhar import corrigir, preparar
from app.estoque import cadastrar_item, imei_ok, mover, saldo_site
from app.lancamento import gravar, saldo
from app.manutencao import registrar
from app.models import Consumivel, Item, Manutencao, MovConsumivel, Movimentacao, Pessoa

SCR = '/tmp/claude-0/-home-claude/362516bd-b636-5afb-874e-23c4b265653a/scratchpad'


def _nb():
    return Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                             Item.finalidade != 'Pool de empréstimo').first()


def _pessoa():
    return Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()


def _repor(nome, qtd=5):
    if not Consumivel.query.filter_by(nome=nome).first():
        db.session.add(Consumivel(nome=nome, item=nome.split(' – ')[0], marca=nome.split(' – ')[1]))
    db.session.add(MovConsumivel(data='2026-11-01', consumivel=nome, site='EC', movimento='Entrada', qtd=qtd, resp='t'))
    db.session.commit()


def test_telas(cli):
    for u in ('/acompanhar', '/manutencao', '/consumiveis', '/itens/novo', '/linhas/analise', '/lancamento/10'):
        assert cli.get(u).status_code == 200, u


def test_reserva_avanca_ate_entregue(app):
    it, p = _nb(), _pessoa()
    res, n, _ = gravar([{'acao': 'Reservar', 'item': it.codigo, 'para': p.id, 'tecnico': 'Diogo Mariano', 'acess': 'Nenhum'}],
                       'entrega', 'T')
    assert n == 1, res[0].msg
    m = res[0].movs[0]
    assert corrigir(m, {'etapa': 'Chamado aberto', 'chamado': 'INC123'}, 'T')[0]
    db.session.refresh(it)
    assert it.situacao == 'Reservada'
    assert corrigir(m, {'etapa': 'Entregue'}, 'T')[0]
    db.session.refresh(it)
    assert it.situacao == 'Em uso' and m.data_ent
    assert not corrigir(m, {'etapa': 'Termo assinado'}, 'T')[0]          # já entregue
    assert corrigir(m, {'link': 'https://x/termo.pdf'}, 'T')[0]           # só corrige


def test_cancelar_reserva_devolve_kit(app):
    it, p = _nb(), _pessoa()
    _repor(f'Kit teclado + mouse sem fio – {it.fabricante or "Dell"}')
    res, n, lote = gravar([{'acao': 'Reservar', 'item': it.codigo, 'para': p.id, 'tecnico': 'Diogo Mariano'}], 'entrega', 'T')
    assert n == 1, res[0].msg
    m = res[0].movs[0]
    kit = MovConsumivel.query.filter_by(mov_id=m.id, movimento='Saída').all()
    antes = {k.consumivel: saldo(k.consumivel) for k in kit}
    assert corrigir(m, {'etapa': 'Cancelado'}, 'T')[0]
    db.session.refresh(it)
    assert it.situacao == 'Em estoque'
    for k in kit:
        assert saldo(k.consumivel) == antes[k.consumivel] + k.qtd


def test_preparacao_parcial_e_liberacao_com_kit(app, fluxo_preparacao):
    it, p = _nb(), _pessoa()
    fab = it.fabricante or 'Dell'
    _repor(f'Fonte de notebook – {fab}')
    _repor(f'Kit teclado + mouse sem fio – {fab}')
    gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega', 'T')
    gravar([{'acao': 'Devolver', 'item': it.codigo, 'receb_por': 'Adriano Santos'}], 'entrega', 'T')
    db.session.refresh(it)
    assert it.situacao == 'Devolvido'
    base = dict(veio_fonte='Não', veio_mouse='Não', veio_teclado='Não', estado='Bom', preparado_por='Adriano Santos')
    ok, msg = preparar(it, dict(base, preventiva='Sim', formatado='Sim'), 'T')
    assert ok
    db.session.refresh(it)
    assert it.situacao == 'Em preparação'
    s_fonte = saldo(f'Fonte de notebook – {fab}')
    ok, msg = preparar(it, dict(base, **{k: 'Sim' for k in ('preventiva', 'formatado', 'fonte', 'mouse', 'teclado', 'embalado')}), 'T')
    assert ok, msg
    db.session.refresh(it)
    assert it.situacao == 'Em estoque' and it.kit == 'Completo'
    assert saldo(f'Fonte de notebook – {fab}') == s_fonte - 1


def test_manutencao_com_backup(app):
    it = Item.query.filter(Item.situacao == 'Em uso', Item.categoria == 'Notebook', Item.matricula.isnot(None)).first()
    bk = Item.query.filter_by(finalidade='Pool de empréstimo', situacao='Em estoque').first()
    assert not registrar({'acao': 'Abrir ocorrência', 'item': it.codigo}, 'T')[0]          # sem defeito
    ok, msg = registrar({'acao': 'Abrir ocorrência', 'item': it.codigo, 'defeito': 'Tela', 'backup': bk.codigo}, 'T')
    assert ok, msg
    db.session.refresh(it)
    db.session.refresh(bk)
    assert it.situacao == 'Manutenção' and bk.situacao == 'Emprestado' and bk.matricula == it.matricula
    assert not registrar({'acao': 'Abrir ocorrência', 'item': it.codigo, 'defeito': 'x'}, 'T')[0]  # já aberta
    assert registrar({'acao': 'Atualizar ocorrência', 'item': it.codigo, 'status': 'Aguardando peça'}, 'T')[0]
    ok, msg = registrar({'acao': 'Fechar ocorrência', 'item': it.codigo, 'feito': 'Troca de tela'}, 'T')
    assert not ok and 'Backup volta' in msg
    ok, msg = registrar({'acao': 'Fechar ocorrência', 'item': it.codigo, 'feito': 'Troca de tela', 'backup_volta': 'Sim'}, 'T')
    assert ok, msg
    db.session.refresh(it)
    db.session.refresh(bk)
    assert it.situacao == 'Em uso' and bk.situacao == 'Em estoque'
    os_ = Manutencao.query.filter_by(item=it.codigo).order_by(Manutencao.id.desc()).first()
    assert os_.status == 'Concluída' and os_.solucao == 'Troca de tela'


def test_consumiveis_e_contagem(app):
    nome = 'Mouse sem fio – Teste'
    _repor(nome, 3)
    assert not mover({'consumivel': nome, 'movimento': 'Saída', 'site': 'EC', 'qtd': '9'}, 'T')[0]
    assert mover({'consumivel': nome, 'movimento': 'Saída', 'site': 'EC', 'qtd': '1'}, 'T')[0]
    assert saldo_site(nome, 'EC') == 2
    assert not mover({'consumivel': nome, 'movimento': 'Contagem de inventário', 'site': 'EC', 'qtd': '2'}, 'T')[0]
    assert mover({'consumivel': nome, 'movimento': 'Contagem de inventário', 'site': 'EC', 'qtd': '7'}, 'T')[0]
    assert saldo_site(nome, 'EC') == 7


def test_item_novo_valida_imei(app):
    assert imei_ok('490154203237518') and not imei_ok('490154203237519')
    ok, msg = cadastrar_item({'codigo': '490154203237519', 'categoria': 'Celular', 'modelo': 'X', 'imei1': '490154203237519'}, 'T')
    assert not ok and 'IMEI' in msg
    ok, msg = cadastrar_item({'codigo': '490154203237518', 'categoria': 'Celular', 'modelo': 'Galaxy', 'imei1': '490154203237518',
                              'site': 'EC'}, 'T')
    assert ok, msg
    assert db.session.get(Item, '490154203237518').situacao == 'Em estoque'
    ja = Item.query.filter(Item.plaqueta.isnot(None)).first()
    assert 'plaqueta' in cadastrar_item({'codigo': 'NOVO1', 'categoria': 'Monitor', 'modelo': 'M', 'plaqueta': ja.plaqueta}, 'T')[1]


@pytest.mark.skipif(not os.path.exists(f'{SCR}/easy/e.xlsx'), reason='arquivos reais da Easy/AirWatch ausentes')
def test_analise_linhas_arquivos_reais(app, cli):
    with open(f'{SCR}/easy/e.xlsx', 'rb') as fe, open(f'{SCR}/aw/a.xlsx', 'rb') as fa:
        r = cli.post('/linhas/analise', data={'easy': (io.BytesIO(fe.read()), 'e.xlsx'), 'airwatch': (io.BytesIO(fa.read()), 'a.xlsx')},
                     content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200 and 'Bloquear'.encode() in r.data
    from app.models import AnaliseLinha
    rs = AnaliseLinha.query.all()
    assert len(rs) > 900
    dec = {d: sum(1 for x in rs if x.decisao == d) for d in {x.decisao for x in rs}}
    assert dec.get('Bloquear', 0) > 50 and dec.get('OK', 0) > 300
    a = next(x for x in rs if x.decisao.startswith('Validar'))
    assert cli.post(f'/linhas/analise/retorno/{a.id}', data={'quem_atendeu': 'Fulano', 'retorno': 'confirmou'}).status_code == 302
    x = cli.get(f'/linhas/analise/{a.rodada}.xlsx')
    assert x.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(x.data))
    assert wb.active.max_row == len(rs) + 1


def test_espelho_tempo_real(app, cli):
    from app.espelho import espelho
    dono = Item.query.filter(Item.situacao == 'Em uso', Item.categoria == 'Notebook', Item.matricula.isnot(None)).first()
    p = db.session.get(Pessoa, dono.matricula)
    it = _nb()
    e = espelho({'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id})
    assert e['pessoa']['id'] == p.id and e['item']['codigo'] == it.codigo
    assert any('já tem' in a for a in e['atencao'])                      # já tem notebook
    assert p.nome in e['resumo'] and it.codigo in e['resumo']
    e = espelho({'acao': 'Devolver', 'item': dono.codigo})
    assert any('Quem devolve' in a for a in e['atencao'])
    e = espelho({'acao': 'Entregar agora', 'item': it.codigo, 'para': 'FULANO QUE NAO EXISTE'})
    assert e['nova'] and any('NOVA' in a for a in e['atencao'])
    r = cli.post('/api/lancar/conferir', json={'aba': 'entrega', 'linhas': [{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id}, {}]})
    assert r.json[0]['espelho']['pessoa']['id'] == p.id and r.json[1]['espelho'] is None


def test_comparacao_de_nome_nao_casa_por_palavra_solta():
    """Armadilha paga em 19/11: bastava UMA palavra em comum, e o "DE" fazia RICARDO DE JESUS
    casar com JERONIMO DE LIMA SILVA. Foram 45 linhas marcadas como "mesmo usuário" sem ser."""
    from app.analise_linhas import mesmo_nome
    assert not mesmo_nome('RICARDO DE JESUS', 'JERONIMO DE LIMA SILVA')
    assert not mesmo_nome('PABLO JUNIOR DE ANDRADE SANTOS', 'ROBERTO SOUZA DE JESUS')
    assert not mesmo_nome('CARLOS HENRIQUE LEME DE SOUSA', 'CARLOS ALBERTO ALVES FLAUZINO')
    assert not mesmo_nome('MODEM CDNE', 'Modem CDGR - Netpark')
    assert not mesmo_nome('', 'QUALQUER NOME')
    # acento, caixa e nome do meio abreviado continuam sendo a mesma pessoa
    assert mesmo_nome('PLANTÃO ARMAZÉM FT I', 'Plantao Armazem FT I')
    assert mesmo_nome('PLANTÃO ADM TRANSPORTE CARJ', 'Plantão ADM Transporte')
    assert mesmo_nome('MARIA SOUZA SILVA', 'MARIA SILVA')


def test_relatorio_de_linhas_traz_cargo_site_e_pessoa_desligada(app, tmp_path):
    """Para quem administra telefonia, a coluna que decide dinheiro é a situação da pessoa: linha
    ativa no nome de quem já saiu é conta correndo à toa. O contexto é lido na hora do relatório,
    não guardado na rodada, para refletir um desligamento posterior à conferência."""
    from app.analise_linhas import exportar, gravar_rodada
    from app.models import AnaliseLinha, Linha
    p = Pessoa(id='Z-9001', nome='TESTE DESLIGADO', tipo='CLT', situacao='Desligado',
               cargo='Motorista', site='GR', cc='999.1', obs='JDE: CD GRU - ARMAZÉM')
    it = Item(codigo='359999999999991', categoria='Celular', modelo='Moto G35 5G')
    db.session.add_all([p, it, Linha(numero='11999990001', operadora='Vivo', regional='LINHA REGIONAL SP',
                                     tipo_chip='eSIM', situacao='Em uso', com_quem=p.nome,
                                     matricula=p.id, aparelho=it.codigo)])
    db.session.commit()
    rodada, _ = gravar_rodada([dict(numero='11999990001', operadora='Vivo', conta='1', usuario_easy='OUTRO NOME',
                                    cc_easy='999.1', sem_consumo=False, sit_mb='Em uso', com_quem=p.nome,
                                    easy_x_mb='usuário diferente', aw_visto='Visto 10/11/2026', aw_aparelho='',
                                    aw_usuario='', aw_modelo='', decisao='OK', motivo='m', acao='a')])
    arq = tmp_path / 'linhas.xlsx'
    exportar(rodada, str(arq))
    ws = openpyxl.load_workbook(arq).active
    cab = {c.value: c.column for c in ws[1] if c.value}
    linha = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, cab['Linha']).value == '11999990001')
    def v(nome):
        return str(ws.cell(linha, cab[nome]).value or '')
    assert v('Pessoa (Zelo)') == 'CLT · Desligado' and 'TESTE DESLIGADO' in v('Atenção')
    assert v('Cargo') == 'Motorista' and v('Site') == 'GR' and v('Área') == 'CD GRU - ARMAZÉM'
    assert v('Tipo de chip') == 'eSIM' and v('Aparelho (Zelo)').startswith('Moto G35 5G · 359999')
    AnaliseLinha.query.filter_by(rodada=rodada).delete()
    db.session.commit()
