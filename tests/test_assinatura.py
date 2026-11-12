"""Etapa 5 — assinatura digital do termo: duas vias, link público e convivência com o papel."""
import base64
import io
from datetime import date, timedelta

import pytest

from app import db
from app.assinatura import (MAX_PNG, PAPEIS, abrir, assinar, cancelar, codigo, completo, conferir, fechar_pendentes,
                            hash_do_termo, link, pedir, vias)
from app.lancamento import gravar
from app.models import Assinatura, Item, Movimentacao, Pessoa


def _png(largura=240, altura=90, tinta=True):
    """Uma assinatura de mentira: um rabisco preto sobre transparente."""
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (largura, altura), (0, 0, 0, 0))
    if tinta:
        d = ImageDraw.Draw(im)
        d.line([(10, 70), (60, 20), (110, 75), (160, 25), (220, 60)], fill=(17, 24, 39, 255), width=4)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def _data_url(dados=None):
    return 'data:image/png;base64,' + base64.b64encode(dados if dados is not None else _png()).decode()


@pytest.fixture()
def entrega(app):
    """Uma entrega recém-lançada, com termo pendente."""
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                           Item.finalidade != 'Pool de empréstimo').first()
    p = Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()
    res, n, _l = gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'termo': 'Pendente',
                          'acess': 'Nenhum'}], 'entrega', 'T')
    assert n == 1, res[0].msg
    return res[0].movs[-1]


# ------------------------------------------------------------------ pedidos e links
def test_pedir_cria_as_duas_vias(app, entrega):
    a1, msg = pedir(entrega, 'colaborador', quem='Gabriel')
    a2, _ = pedir(entrega, 'empresa', 'Giselly Oliveira', quem='Gabriel')
    assert a1 and a2 and a1.token != a2.token
    assert len(a1.token) >= 32 and a1.expira > date.today().isoformat()
    assert a1.nome == entrega.nome                       # colaborador vem do lançamento
    assert a2.nome == 'Giselly Oliveira'
    v = vias(entrega)
    assert v['colaborador'].id == a1.id and v['empresa'].id == a2.id
    assert not completo(entrega)
    assert '/assinar/' in link(a1, externo=False)


def test_refazer_link_invalida_o_anterior(app, entrega):
    a1, _ = pedir(entrega, 'colaborador', quem='T')
    velho = a1.token
    a2, msg = pedir(entrega, 'colaborador', quem='T')
    assert a2.token != velho and 'deixou de valer' in msg
    assert abrir(velho)[2].startswith('Este link foi cancelado')
    assert vias(entrega)['colaborador'].id == a2.id       # a cancelada sai da conta


def test_pedir_recusa_tipo_sem_termo(app):
    m = Movimentacao.query.filter(Movimentacao.tipo == 'Transferência').first()
    if not m:
        m = Movimentacao.query.filter(~Movimentacao.tipo.in_(('Entrega', 'Empréstimo', 'Devolução'))).first()
    a, msg = pedir(m, 'colaborador', quem='T')
    assert a is None and 'não tem termo' in msg
    assert pedir(Movimentacao.query.first(), 'inventado', quem='T')[0] is None


def test_abrir_link_vencido_e_cancelado(app, entrega):
    a, _ = pedir(entrega, 'colaborador', quem='T')
    a.expira = (date.today() - timedelta(days=1)).isoformat()
    db.session.commit()
    assert 'venceu' in abrir(a.token)[2]
    a.expira = (date.today() + timedelta(days=3)).isoformat()
    db.session.commit()
    assert abrir(a.token)[2] == ''
    cancelar(a, 'Não precisa mais', 'T')
    assert 'cancelado' in abrir(a.token)[2]
    assert abrir('token-que-nao-existe')[2].startswith('Este link não existe')


# ------------------------------------------------------------------ assinar
def test_assinatura_recusa_quadro_em_branco_e_lixo(app, entrega):
    a, _ = pedir(entrega, 'colaborador', quem='T')
    assert assinar(a, entrega, '', 'Fulano de Tal')[1] == 'Assine no quadro antes de confirmar'
    assert 'em branco' in assinar(a, entrega, _data_url(_png(tinta=False)), 'Fulano de Tal')[1]
    assert 'não aceito' in assinar(a, entrega, 'data:image/gif;base64,R0lGOD', 'Fulano de Tal')[1]
    assert 'não aceito' in assinar(a, entrega, b'nao sou png', 'Fulano de Tal')[1]
    assert 'grande demais' in assinar(a, entrega, b'\x89PNG\r\n\x1a\n' + b'x' * MAX_PNG, 'Fulano')[1]
    assert 'nome completo' in assinar(a, entrega, _data_url(), 'Z')[1]
    db.session.refresh(a)
    assert a.pendente                                     # nada disso marcou a via


def test_duas_vias_fecham_o_termo(app, entrega):
    a1, _ = pedir(entrega, 'colaborador', quem='T')
    a2, _ = pedir(entrega, 'empresa', 'Giselly Oliveira', quem='T')
    ok, msg, fechou = assinar(a1, entrega, _data_url(), 'Fulano de Tal Silva', '10.0.0.5', 'Chrome/Teste')
    assert ok and not fechou                              # falta a via da empresa
    db.session.refresh(entrega)
    assert entrega.termo == 'Pendente' and not entrega.termo_arquivo

    ok, msg, fechou = assinar(a2, entrega, _data_url(), 'Giselly Oliveira', '10.0.0.9', 'Safari/Teste')
    assert ok and fechou, msg
    db.session.refresh(entrega)
    assert entrega.termo == 'Assinado' and entrega.data_ass
    assert entrega.termo_arquivo.endswith('.pdf')
    assert completo(entrega)

    from app.termo_arquivo import caminho
    with open(caminho(entrega), 'rb') as fh:
        pdf = fh.read()
    assert pdf.startswith(b'%PDF') and len(pdf) > 3000    # com as imagens das assinaturas dentro

    db.session.refresh(a1)
    assert a1.assinante == 'Fulano de Tal Silva' and a1.ip == '10.0.0.5' and a1.traco
    assert a1.hash_termo and len(a1.hash_termo) == 64 and codigo(a1) != codigo(a2)


def test_nao_assina_duas_vezes_pelo_mesmo_link(app, entrega):
    a, _ = pedir(entrega, 'colaborador', quem='T')
    assert assinar(a, entrega, _data_url(), 'Fulano de Tal')[0]
    ok, msg, _f = assinar(a, entrega, _data_url(), 'Outra Pessoa')
    assert not ok and 'já foi assinada' in msg
    db.session.refresh(a)
    assert a.assinante == 'Fulano de Tal'


def test_hash_avisa_quando_o_termo_muda_depois(app, entrega):
    a1, _ = pedir(entrega, 'colaborador', quem='T')
    assinar(a1, entrega, _data_url(), 'Fulano de Tal')
    assert conferir(entrega) == []
    entrega.obs = 'observação acrescentada depois da assinatura'
    db.session.commit()
    avisos = conferir(entrega)
    assert avisos and 'alterado depois de assinado' in avisos[0] and 'Fulano de Tal' in avisos[0]


def test_hash_do_termo_e_estavel(app, entrega):
    from app.routes.termo import montar
    d = montar(str(entrega.id))[0]
    assert hash_do_termo(d) == hash_do_termo(montar(str(entrega.id))[0])
    d2 = dict(d, obs='outra coisa')
    assert hash_do_termo(d) != hash_do_termo(d2)


# ------------------------------------------------------------------ papel e tela conviverem
def test_termo_digitalizado_encerra_os_pedidos(app, entrega):
    from werkzeug.datastructures import FileStorage
    a1, _ = pedir(entrega, 'colaborador', quem='T')
    a2, _ = pedir(entrega, 'empresa', 'Cristiano Sato', quem='T')
    from app.termo_arquivo import salvar
    pdf = FileStorage(stream=io.BytesIO(b'%PDF-1.4 termo escaneado'), filename='termo.pdf')
    ok, msg = salvar(entrega, pdf, 'Gabriel')
    assert ok and '2 pedido(s) de assinatura em aberto foram encerrados' in msg
    db.session.refresh(entrega)
    assert entrega.termo == 'Assinado' and entrega.termo_arquivo.endswith('.pdf')
    db.session.refresh(a1)
    db.session.refresh(a2)
    assert a1.cancelado and 'Gabriel' in a1.motivo and a2.cancelado
    assert vias(entrega) == {'colaborador': None, 'empresa': None}


def test_fechar_pendentes_nao_mexe_no_que_ja_assinou(app, entrega):
    a1, _ = pedir(entrega, 'colaborador', quem='T')
    a2, _ = pedir(entrega, 'empresa', 'Giselly Oliveira', quem='T')
    assinar(a1, entrega, _data_url(), 'Fulano de Tal')
    assert fechar_pendentes(entrega, 'teste') == 1
    db.session.refresh(a1)
    db.session.refresh(a2)
    assert a1.assinado and not a1.cancelado and a2.cancelado


# ------------------------------------------------------------------ telas
def test_pagina_publica_abre_sem_login_e_grava(app, entrega):
    a, _ = pedir(entrega, 'colaborador', quem='T')
    anon = app.test_client()
    r = anon.get(f'/assinar/{a.token}')
    assert r.status_code == 200
    h = r.data.decode()
    assert 'Assine aqui' in h and entrega.nome in h
    assert 'z-sidebar' not in h                            # sem login, sem menu interno

    r = anon.post(f'/assinar/{a.token}', data={'desenho': _data_url(), 'nome': 'Fulano de Tal Silva'},
                  follow_redirects=True)
    assert r.status_code == 200 and 'Assinatura registrada' in r.data.decode()
    db.session.refresh(a)
    assert a.assinado and a.assinante == 'Fulano de Tal Silva'
    assert 'Assinatura registrada' in anon.get(f'/assinar/{a.token}').data.decode()


def test_pagina_publica_so_mostra_o_proprio_termo(app, entrega):
    anon = app.test_client()
    assert anon.get('/assinar/token-inventado').status_code == 404
    a, _ = pedir(entrega, 'colaborador', quem='T')
    outra = Movimentacao.query.filter(Movimentacao.id != entrega.id, Movimentacao.nome.isnot(None)).first()
    h = anon.get(f'/assinar/{a.token}').data.decode()
    assert f'Nº {outra.id}' not in h


def test_pdf_do_link(app, entrega):
    a, _ = pedir(entrega, 'colaborador', quem='T')
    anon = app.test_client()
    r = anon.get(f'/assinar/{a.token}/termo.pdf')
    assert r.status_code == 200 and r.data.startswith(b'%PDF')
    assert anon.get('/assinar/nada/termo.pdf').status_code == 404


def test_painel_das_assinaturas(app, cli, entrega):
    r = cli.get(f'/lancamento/{entrega.id}/assinaturas')
    assert r.status_code == 200
    h = r.data.decode()
    assert 'Colaborador(a)' in h and 'Pela empresa' in h and 'Anexar termo digitalizado' in h
    assert 'Giselly Oliveira' in h                          # assinantes da empresa vêm da configuração

    r = cli.post(f'/lancamento/{entrega.id}/assinaturas',
                 data={'acao': 'pedir', 'papel': 'empresa', 'nome': 'Cristiano Sato', 'contato': 'whats'},
                 follow_redirects=True)
    assert r.status_code == 200
    a = vias(entrega)['empresa']
    assert a and a.nome == 'Cristiano Sato' and a.contato == 'whats'
    assert a.token in r.data.decode()                       # o link aparece para copiar

    r = cli.post(f'/lancamento/{entrega.id}/assinaturas', data={'acao': 'cancelar', 'papel': 'empresa'},
                 follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(a)
    assert a.cancelado


def test_traco_so_para_quem_esta_logado(app, cli, entrega):
    a, _ = pedir(entrega, 'colaborador', quem='T')
    assinar(a, entrega, _data_url(), 'Fulano de Tal')
    r = cli.get(f'/assinatura/{a.id}.png')
    assert r.status_code == 200 and r.data.startswith(b'\x89PNG')
    anon = app.test_client()
    assert anon.get(f'/assinatura/{a.id}.png').status_code in (302, 403)


def test_lancamento_mostra_o_placar_das_vias(app, cli, entrega):
    a, _ = pedir(entrega, 'colaborador', quem='T')
    assinar(a, entrega, _data_url(), 'Fulano de Tal')
    h = cli.get(f'/lancamento/{entrega.id}').data.decode()
    assert 'Assinaturas' in h and '1/2' in h


def test_todas_as_vias_tem_rotulo():
    from app.assinatura import ROTULO
    assert set(ROTULO) == set(PAPEIS) and all(ROTULO.values())


# ------------------------------------------------------------------ cobrança
def test_lembrete_cobra_assinatura_parada(app, entrega):
    from app import lembretes as lb
    from app.models import Assinatura as A
    lb.esquecer()
    assert not any(x['chave'] == 'assinatura_parada' for x in lb.tudo()[0])
    a, _ = pedir(entrega, 'empresa', 'Giselly Oliveira', quem='T')
    a.criado = (date.today() - timedelta(days=10)).isoformat()
    db.session.commit()
    lb.esquecer()
    x = next(x for x in lb.tudo()[0] if x['chave'] == 'assinatura_parada')
    assert x['n'] == 1 and x['urgencia'] == 'media' and 'não é liberado' in x['porque']
    assinar(a, entrega, _data_url(), 'Giselly Oliveira')
    lb.esquecer()
    assert not any(x['chave'] == 'assinatura_parada' for x in lb.tudo()[0])
    assert A.query.filter(A.assinado.isnot(None)).count() >= 1


def test_fila_lista_as_assinaturas_em_aberto(app, cli, entrega):
    a, _ = pedir(entrega, 'empresa', 'Cristiano Sato', quem='T', contato='whats')
    h = cli.get('/fila').data.decode()
    assert 'Assinaturas pedidas e não assinadas' in h
    assert 'Cristiano Sato' in h and 'whats' in h and f'/lancamento/{entrega.id}/assinaturas' in h


def test_formato_de_data_e_hora():
    from app.formato import quando_br
    assert quando_br('2026-11-11T22:34:07') == '11/11/2026 às 22:34'
    assert quando_br('2026-11-11 22:34') == '11/11/2026 às 22:34'
    assert quando_br('2026-11-11') == '11/11/2026'
    assert quando_br(None) == '' and quando_br('') == ''


def test_link_usa_o_endereco_configurado(app):
    from app.assinatura import local
    from app.models import Config
    m = Movimentacao.query.filter(Movimentacao.tipo == 'Entrega').first()
    a, _ = pedir(m, 'colaborador', quem='T')
    with app.test_request_context('/'):
        assert local(link(a))                                  # SERVER_NAME=localhost nos testes
        db.session.add(Config(chave='url_base', valor='http://servidor-ti:5001/'))
        db.session.commit()
        u = link(a)
    assert u == f'http://servidor-ti:5001/assinar/{a.token}' and not local(u)


def test_painel_avisa_link_local(app, cli):
    m = Movimentacao.query.filter(Movimentacao.tipo == 'Entrega').first()
    pedir(m, 'colaborador', quem='T')
    h = cli.get(f'/lancamento/{m.id}/assinaturas').data.decode()
    assert 'só abre aqui' in h and 'endereço do Zelo na rede' in h


def test_etiqueta_do_estado_nao_mente(app, cli, entrega):
    entrega.termo = 'Assinado'                                 # como vem da planilha, sem via nenhuma
    db.session.commit()
    h = cli.get(f'/lancamento/{entrega.id}/assinaturas').data.decode()
    assert 'marcado como assinado (sem via no Zelo)' in h
    a1, _ = pedir(entrega, 'colaborador', quem='T')
    assinar(a1, entrega, _data_url(), 'Fulano de Tal')
    assert 'uma via assinada' in cli.get(f'/lancamento/{entrega.id}/assinaturas').data.decode()
    a2, _ = pedir(entrega, 'empresa', 'Giselly Oliveira', quem='T')
    assinar(a2, entrega, _data_url(), 'Giselly Oliveira')
    assert 'assinado nesta tela' in cli.get(f'/lancamento/{entrega.id}/assinaturas').data.decode()


# ------------------------------------------------------------------ como se chega até aqui
def test_tela_de_assinaturas_no_menu(app, cli, entrega):
    h = cli.get('/').data.decode()
    assert '/assinaturas' in h                                 # entrada na barra lateral

    r = cli.get('/assinaturas')
    assert r.status_code == 200
    assert 'Nenhuma via esperando' in r.data.decode()

    a, _ = pedir(entrega, 'empresa', 'Giselly Oliveira', quem='T', contato='whats')
    h = cli.get('/assinaturas').data.decode()
    assert 'Giselly Oliveira' in h and f'/lancamento/{entrega.id}/assinaturas' in h
    assert entrega.nome in h                                   # dá para saber de quem é o termo

    assinar(a, entrega, _data_url(), 'Giselly Oliveira', '10.0.0.3')
    h = cli.get('/assinaturas').data.decode()
    assert 'Últimas assinadas' in h and '10.0.0.3' in h


def test_abrir_pelo_numero(app, cli, entrega):
    r = cli.get(f'/assinaturas?n={entrega.id}')
    assert r.status_code == 302 and f'/lancamento/{entrega.id}/assinaturas' in r.headers['Location']
    assert 'Não achei o lançamento Nº 99999999' in cli.get('/assinaturas?n=99999999').data.decode()


def test_tela_termo_leva_para_a_assinatura(app, cli, entrega):
    h = cli.get(f'/termo?n={entrega.id}').data.decode()
    assert 'Assinar sem papel' in h and f'/lancamento/{entrega.id}/assinaturas' in h
    assert '/assinaturas' in cli.get('/termo').data.decode()


def test_busca_acha_a_tela_de_assinatura(app, cli):
    for q in ('assinatura digital', 'assinador', 'assinar termo'):
        j = cli.get('/api/busca?q=' + q).json
        ir = next((x for x in j['grupos'] if x['titulo'] == 'Ir para'), None)
        assert ir and any(l['titulo'] == 'Assinaturas' for l in ir['linhas']), q
