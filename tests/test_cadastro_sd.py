"""Cadastro em massa no Service Desk: o retrato antes, a fila depois, e nada duplicado."""
from types import SimpleNamespace

import pytest

from app import cadastro_sd as cad
from app import db
from app import servicedesk as sd
from app.models import EnvioSD, Item
from tests.conftest import entrar
from tests.test_servicedesk import sim  # noqa: F401  (fixture)


def _cat(a, nome):
    return next(c for c in a['categorias'] if c['categoria'] == nome)


def _ligar():
    # Monitor fica só no Zelo por padrão; aqui ele é mapeado de propósito, porque é a categoria
    # sem hostname que o simulador sabe criar — e é ela que exercita o nome pela service tag.
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_criar_ativo': 'Sim', 'sd_tipos': 'Monitor=Monitor'})


# ------------------------------------------------------------------ o nome no SD
def test_nome_no_sd_hostname_depois_tag_depois_codigo():
    assert sd.nome_no_sd(SimpleNamespace(hostname='lmb01', tag='ABC', codigo='1')) == 'LMB01'
    assert sd.nome_no_sd(SimpleNamespace(hostname='', tag='cn0abc', codigo='W-127')) == 'CN0ABC'
    assert sd.nome_no_sd(SimpleNamespace(hostname=None, tag='', codigo='353044841094072')) == '353044841094072'


def test_item_sem_hostname_nasce_pela_service_tag(app, sim):  # noqa: F811
    """Monitor, dock e coletor não têm hostname: antes não podiam ser criados, e sem o agente do
    SDP nunca entrariam no SD."""
    s, _p = sim
    _ligar()
    novo = sd.criar_ativo(SimpleNamespace(hostname='', tag='CN0MON1', codigo='W-1', plaqueta='', categoria='Monitor',
                                          site='', fornecedor='', garantia='', modelo=''), 'In Store')
    assert novo['name'] == 'CN0MON1' and 'CN0MON1' in s.ativos


def test_item_sem_nome_nenhum_nao_tenta_criar(app, sim):  # noqa: F811
    with pytest.raises(sd.ErroSD, match='precisa de um nome'):
        sd.criar_ativo(SimpleNamespace(hostname='', tag='', codigo='', plaqueta='', categoria='Monitor',
                                       site='', fornecedor='', garantia=''))


# ------------------------------------------------------------------ o retrato
def test_analise_diz_por_categoria_para_onde_iria(app, sim):  # noqa: F811
    a = cad.analisar()
    assert not a['erro'] and a['no_sd'] == 0
    nb = _cat(a, 'Notebook')
    assert nb['pronta'] and nb['tipo'] == 'Laptop' and nb['endereco'] == '/api/v3/asset_computers'
    assert len(nb['faltam']) + len(nb['sem_dono']) == nb['total'] == Item.query.filter(
        Item.categoria == 'Notebook', Item.situacao != 'Baixada').count()
    # celular vai para Smart Phone, que este SD (o simulador) não tem: bloqueada, com o motivo
    cel = _cat(a, 'Celular')
    assert not cel['pronta'] and 'não existe no seu Service Desk' in cel['motivo']


def test_tipo_sem_produto_bloqueia_mesmo_se_o_metainfo_nao_exigir(app, sim):  # noqa: F811
    """Achado no laboratório (18/11): o tipo Smart Phone existe, não tem produto, e o _metainfo não
    marca `product` como obrigatório. A tela dizia "pronta" e toda criação voltava
    "400 Value not provided"."""
    s, _p = sim
    s.modulos.append({'id': '3', 'display_name': 'Smart Phone', 'api_name': 'asset_smartphone',
                      'api_plural_name': 'asset_smartphones', 'category': {'display_name': 'Asset'}})
    s.campos_metainfo = ['name']
    cel = _cat(cad.analisar(), 'Celular')
    assert not cel['pronta'] and 'nenhum produto do tipo "Smart Phone"' in cel['motivo']


def test_monitor_e_dock_ficam_so_no_zelo_por_padrao(app, sim):  # noqa: F811
    """Decisão do Gabriel (18/11): no SD só o que o usuário aponta ao abrir chamado. Ninguém lê o
    S/N de um monitor ou de um dock para isso."""
    a = cad.analisar()
    for cat in ('Monitor', 'Dock station'):
        c = _cat(a, cat)
        assert c['so_zelo'] and not c['pronta'] and 'fica só no Zelo' in c['motivo']
    assert not sd.sincroniza(Item.query.filter(Item.categoria == 'Monitor', Item.tag != '').first())
    # mapear de propósito libera
    sd.salvar_conf({'sd_tipos': 'Monitor=Monitor'})
    c = _cat(cad.analisar(), 'Monitor')
    assert c['pronta'] and not c['so_zelo']


def test_categoria_sem_tipo_e_categoria_desligada(app, sim):  # noqa: F811
    sd.salvar_conf({'sd_tipos': 'Notebook='})
    a = cad.analisar()
    assert 'desligada' in _cat(a, 'Notebook')['motivo']
    sem = [c for c in a['categorias'] if c['categoria'] not in sd.mapa_tipos() and c['faltam']]
    assert all(not c['so_zelo'] for c in sem)
    assert sem and all('sem tipo de produto' in c['motivo'] for c in sem)


def test_produto_proprio_ou_generico_por_modelo(app, sim):  # noqa: F811
    """A decisão do PLANO com número: quantos modelos já têm produto no SD e quantos cairiam no
    primeiro do tipo."""
    s, _p = sim
    nb = Item.query.filter(Item.categoria == 'Notebook', Item.situacao != 'Baixada', Item.modelo.isnot(None),
                           Item.modelo != '').first()
    s.produtos.append({'id': '90', 'name': nb.modelo, 'product_type': {'name': 'Laptop'}})
    sd.salvar_conf({})                    # limpa o cache de produtos, como faria o tempo
    modelos = {m['modelo']: m for m in _cat(cad.analisar(), 'Notebook')['modelos']}
    assert modelos[nb.modelo]['como'] == 'proprio' and modelos[nb.modelo]['produto'] == nb.modelo
    assert any(m['como'] == 'generico' and m['produto'] == 'Latitude 5450' for m in modelos.values()
               if m['modelo'] != nb.modelo) or len(modelos) == 1


def test_o_que_ja_esta_no_sd_nao_falta(app, sim):  # noqa: F811
    """Já lá pelo nome (o agente põe domínio) ou pela service tag, com outro nome."""
    s, _p = sim
    nb = Item.query.filter(Item.categoria == 'Notebook', Item.situacao != 'Baixada', Item.hostname != '').first()
    mon = Item.query.filter(Item.categoria == 'Monitor', Item.situacao != 'Baixada', Item.tag != '').first()
    for i, (nome, tag) in enumerate(((nb.hostname.lower() + '.reyesholdings.com', ''),
                                     ('OUTRO-NOME', mon.tag))):
        a = {'id': str(900 + i), 'name': nome, 'serial_number': tag}
        s.ativos[nome] = a
        s.ativos_por_id[a['id']] = a
    a = cad.analisar()
    assert nb.codigo not in {x.codigo for x in _cat(a, 'Notebook')['faltam']}
    assert mon.codigo not in {x.codigo for x in _cat(a, 'Monitor')['faltam']}
    assert _cat(a, 'Notebook')['ja_no_sd'] == 1


def test_baixada_nao_entra(app, sim):  # noqa: F811
    b = Item.query.filter(Item.situacao == 'Baixada').first()
    if not b:
        pytest.skip('sem item baixado na planilha')
    todos = {x.codigo for c in cad.analisar()['categorias'] for x in c['faltam']}
    assert b.codigo not in todos


# ------------------------------------------------------------------ a fila
def test_enfileirar_exige_a_criacao_ligada(app, sim):  # noqa: F811
    ids, recado = cad.enfileirar(['Monitor'], 5)
    assert not ids and 'Cadastrar o ativo' in recado and EnvioSD.query.count() == 0


def test_enfileira_com_limite_e_cria_pela_fila(app, sim):  # noqa: F811
    s, _p = sim
    _ligar()
    ids, recado = cad.enfileirar(['Monitor'], 3)
    assert len(ids) == 3 and '3 item(ns)' in recado
    envios = EnvioSD.query.filter(EnvioSD.id.in_(ids)).all()
    assert all(e.codigo and e.mov_id is None and e.tipo == 'ativo' for e in envios)
    sd.processar(app, ids)              # nos testes roda na hora
    for e in envios:
        db.session.refresh(e)
        it = db.session.get(Item, e.codigo)
        assert e.status == 'Enviado', e.erro
        assert sd.nome_no_sd(it) in s.ativos and 'cadastrado agora' in e.erro
        # o produto saiu do catálogo do SD (o do modelo, ou o primeiro do tipo) — nunca inventado
        assert s.ativos[sd.nome_no_sd(it)]['product']['id'] in {p['id'] for p in s.produtos}


def test_categoria_bloqueada_nao_entra_na_fila(app, sim):  # noqa: F811
    _ligar()
    ids, _r = cad.enfileirar(['Celular'], 5)
    assert not ids


def test_segunda_vez_nao_duplica(app, sim):  # noqa: F811
    """Na fila ou já criado: clicar de novo não manda o mesmo ativo outra vez."""
    _ligar()
    ids1, _r = cad.enfileirar(['Monitor'], 4)
    ids2, recado = cad.enfileirar(['Monitor'], 4)
    alvos1 = {e.alvo for e in EnvioSD.query.filter(EnvioSD.id.in_(ids1))}
    alvos2 = {e.alvo for e in EnvioSD.query.filter(EnvioSD.id.in_(ids2))}
    assert not alvos1 & alvos2 and 'pulado' in recado
    sd.processar(app, ids1 + ids2)
    ids3, _r = cad.enfileirar(['Monitor'], 8)            # os 8 já estão no SD agora
    assert not {e.alvo for e in EnvioSD.query.filter(EnvioSD.id.in_(ids3))} & (alvos1 | alvos2)


def test_criado_de_novo_procura_antes(app, sim):  # noqa: F811
    """A análise pode ficar velha: o envio procura o ativo antes de criar."""
    s, _p = sim
    _ligar()
    ids, _r = cad.enfileirar(['Monitor'], 1)
    e = db.session.get(EnvioSD, ids[0])
    a = {'id': '950', 'name': e.alvo}               # alguém criou à mão entre a análise e o envio
    s.ativos[e.alvo] = a
    s.ativos_por_id['950'] = a
    sd.processar(app, ids)
    db.session.refresh(e)
    assert e.status == 'Enviado' and 'cadastrado agora' not in (e.erro or '')
    assert sum(1 for x in s.ativos.values() if x['name'] == e.alvo) == 1


# ------------------------------------------------------------------ depois do cadastro
def test_monitor_so_sincroniza_com_a_criacao_ligada(app, sim):  # noqa: F811
    mon = Item.query.filter(Item.categoria == 'Monitor', Item.situacao != 'Baixada', Item.tag != '').first()
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_tipos': 'Monitor=Monitor'})
    assert not sd.sincroniza(mon)               # sem criação, nunca vai existir lá: não enche a fila
    sd.salvar_conf({'sd_criar_ativo': 'Sim'})
    assert sd.sincroniza(mon)
    sd.salvar_conf({'sd_tipos': 'Monitor='})
    assert not sd.sincroniza(mon)


def test_enfileirar_item_de_monitor_usa_o_codigo(app, sim):  # noqa: F811
    s, _p = sim
    _ligar()
    mon = Item.query.filter(Item.categoria == 'Monitor', Item.situacao == 'Em estoque', Item.tag != '').first()
    assert sd.enfileirar_item(app, mon.codigo) == 1
    e = EnvioSD.query.filter_by(codigo=mon.codigo).one()
    assert e.alvo == sd.nome_no_sd(mon) and e.status == 'Enviado', e.erro
    assert sd.nome_no_sd(mon) in s.ativos


# ------------------------------------------------------------------ tela
def test_tela_mostra_o_retrato_e_poe_na_fila(app, sim):  # noqa: F811
    c = entrar(app.test_client(), 'admin@teste')
    h = c.get('/admin/servicedesk/cadastro').data.decode()
    assert 'Por categoria' in h and 'Smart Phone' in h and 'Para criar, ligue' in h
    assert '/admin/servicedesk/cadastro' in c.get('/admin/servicedesk').data.decode()
    _ligar()
    r = c.post('/admin/servicedesk/cadastro', data={'categorias': ['Monitor'], 'limite': '2'},
               follow_redirects=True)
    assert '2 item(ns) na fila' in r.data.decode()
    assert EnvioSD.query.filter(EnvioSD.codigo.isnot(None), EnvioSD.status == 'Enviado').count() == 2
    assert 'Andamento da fila' in c.get('/admin/servicedesk/cadastro').data.decode()


def test_tela_so_para_admin(app, cli):
    assert cli.get('/admin/servicedesk/cadastro').status_code == 403


def test_imei_vai_so_para_modulo_que_tem_o_campo(app, sim):  # noqa: F811
    """Laboratório (18/11): IMEI grava na criação de Smart Phone e derruba a de Laptop."""
    s, _p = sim
    _ligar()
    base = dict(hostname='', plaqueta='', categoria='Monitor', site='', fornecedor='', garantia='', modelo='',
                imei1='353044841099999')
    sd.criar_ativo(SimpleNamespace(tag='SEMIMEI1', codigo='X1', **base), 'In Store')
    assert 'imei' not in s.ativos['SEMIMEI1']
    s.campos_metainfo = ['name', 'product', 'imei']
    sd.salvar_conf({})                                  # o _metainfo do módulo mudou
    sd.criar_ativo(SimpleNamespace(tag='COMIMEI1', codigo='X2', **base), 'In Store')
    assert s.ativos['COMIMEI1']['imei'] == '353044841099999'


def test_em_uso_sem_pessoa_fica_fora_da_fila(app, sim):  # noqa: F811
    """Máquina de posto no CD: "Em uso" sem pessoa. O SDP não aceita In Use sem usuário
    (laboratório, 18/11), então ela aparece no retrato e não vai para a fila."""
    _ligar()
    it = Item.query.filter(Item.categoria == 'Notebook', Item.situacao == 'Em estoque', Item.hostname != '').first()
    it.situacao, it.matricula = 'Em uso', None
    db.session.commit()
    nb = _cat(cad.analisar(), 'Notebook')
    assert it.codigo in {x.codigo for x in nb['sem_dono']} and it.codigo not in {x.codigo for x in nb['faltam']}
    ids, _r = cad.enfileirar(['Notebook'])
    assert it.codigo not in {e.codigo for e in EnvioSD.query.filter(EnvioSD.id.in_(ids))}
    # e se chegar à fila por outro caminho (uma entrega desfeita, um ajuste), o erro diz o que fazer
    assert sd.enfileirar_item(app, it.codigo) == 1
    e = EnvioSD.query.filter_by(codigo=it.codigo).one()
    assert e.status == 'Erro' and 'sem pessoa' in e.erro
