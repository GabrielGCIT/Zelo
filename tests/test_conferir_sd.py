"""Ativos × Service Desk: importar o que falta e enxergar onde os dois discordam."""
import pytest

from app import db
from app import servicedesk as sd
from app.conferir_sd import aplicar, baixar, conferir, do_sd
from app.lancamento import gravar
from app.models import Item, Pessoa
from tests.test_servicedesk import SimuladorSD


@pytest.fixture()
def sdl(app):
    s = SimuladorSD({})
    sd.transporte = s
    sd.salvar_conf({'sd_url': 'http://sd.teste:8080', 'sd_chave': 'CHAVE-TESTE', 'sd_ativo': 'Sim'})
    yield s
    sd.transporte = None


def _ativo(nome, **kw):
    a = {'id': str(abs(hash(nome)) % 9999), 'name': nome}
    a.update(kw)
    return a


def _por(s, nome):
    s.ativos[nome] = _ativo(nome)
    return s.ativos[nome]


def _item_com_host():
    """Notebook em estoque com hostname que não se repete no parque (senão o casamento recusa, e deve)."""
    from sqlalchemy import func
    repetidos = [h for h, n in db.session.query(Item.hostname, func.count('*')).group_by(Item.hostname).all()
                 if n > 1 and h]
    return (Item.query.filter(Item.hostname.isnot(None), Item.hostname != '', Item.categoria == 'Notebook',
                              Item.finalidade != 'Pool de empréstimo', Item.situacao == 'Em estoque',
                              ~Item.hostname.in_(repetidos)).order_by(Item.codigo).first())


# ------------------------------------------------------------------ tradução
def test_le_o_ativo_mesmo_com_nomes_de_campo_diferentes():
    a = do_sd({'id': '7', 'name': 'LMBB01', 'serial_number': 'ABC123', 'asset_tag': '9988',
               'product': {'name': 'Latitude 5450'}, 'product_type': {'name': 'Laptop'},
               'state': {'name': 'In Use'}, 'user': {'name': 'FULANO DE TAL'}, 'site': {'name': 'EC'}})
    assert a['hostname'] == 'LMBB01' and a['tag'] == 'ABC123' and a['plaqueta'] == '9988'
    assert a['modelo'] == 'Latitude 5450' and a['estado'] == 'In Use' and a['usuario'] == 'FULANO DE TAL'
    # build que usa service_tag em vez de serial_number
    assert do_sd({'name': 'X', 'service_tag': 'ZZZ'})['tag'] == 'ZZZ'
    assert do_sd({'name': 'X'})['tag'] == '' and do_sd({'name': 'X'})['modelo'] == ''


def test_baixar_pagina_a_pagina(app, sdl):
    for i in range(130):
        _por(sdl, f'HOST{i:03d}')
    lista, truncou, erro = baixar()
    assert not erro and not truncou and len(lista) == 130
    lista, truncou, _e = baixar(limite_paginas=1)
    assert len(lista) == 100 and truncou


# ------------------------------------------------------------------ casar e classificar
def test_casa_por_hostname_e_completa_o_que_falta(app, sdl):
    it = _item_com_host()
    it.tag, it.modelo = None, None
    db.session.commit()
    a = _por(sdl, it.hostname.upper())
    a['serial_number'] = 'TAG-DO-SD'
    a['product'] = {'name': 'Latitude 5450'}
    linhas, resumo = conferir([do_sd(a)])
    l = next(x for x in linhas if x['item'] and x['item']['codigo'] == it.codigo)
    assert l['caso'] == 'completa' and dict(l['faltam']) == {'tag': 'TAG-DO-SD', 'modelo': 'Latitude 5450'}
    assert resumo['no_sd'] == 1


def test_casa_pela_service_tag_quando_nao_ha_hostname(app, sdl):
    it = Item.query.filter(Item.tag.isnot(None), Item.tag != '',
                           (Item.hostname.is_(None)) | (Item.hostname == '')).first()
    a = _por(sdl, 'NOME-QUE-NAO-BATE')
    a['serial_number'] = it.tag
    linhas, _r = conferir([do_sd(a)])
    l = linhas[0]
    assert l['item']['codigo'] == it.codigo and l['caso'] == 'completa'
    assert ('hostname', 'NOME-QUE-NAO-BATE') in l['faltam']


def test_dado_diferente_nao_e_aplicado_sozinho(app, sdl):
    it = _item_com_host()
    it.tag = 'TAG-DO-ZELO'
    db.session.commit()
    a = _por(sdl, it.hostname.upper())
    a['serial_number'] = 'TAG-DIFERENTE'
    linhas, resumo = conferir([do_sd(a)])
    l = linhas[0]
    assert l['caso'] == 'divergente' and ('tag', 'TAG-DO-ZELO', 'TAG-DIFERENTE') in l['difere']
    db.session.refresh(it)
    assert it.tag == 'TAG-DO-ZELO'              # conferir não escreve nada


def test_quem_esta_com_a_maquina_difere(app, sdl):
    """A pergunta que ninguém responde hoje: o SD diz uma pessoa e o Zelo diz outra."""
    it = _item_com_host()
    p = Pessoa.query.filter_by(situacao='Ativo', tipo='CLT').first()
    res, n, _l = gravar([{'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}], 'entrega', 'T')
    assert n == 1, res[0].msg
    a = _por(sdl, it.hostname.upper())
    a['user'] = {'name': 'OUTRA PESSOA QUALQUER'}
    a['state'] = {'name': 'In Use'}
    linhas, resumo = conferir([do_sd(a)])
    l = linhas[0]
    assert l['caso'] == 'quem' and l['quem_sd'] == 'OUTRA PESSOA QUALQUER' and l['quem_zelo'] == p.nome
    assert resumo['quem'] == 1

    a['user'] = {'name': p.nome.title()}        # mesmo nome, outra caixa/acento: não é divergência
    assert conferir([do_sd(a)])[0][0]['caso'] == 'confere'


def test_situacao_difere(app, sdl):
    it = _item_com_host()                        # Em estoque no Zelo
    a = _por(sdl, it.hostname.upper())
    a['state'] = {'name': 'In Use'}
    a['serial_number'] = it.tag or ''
    a['product'] = {'name': it.modelo or ''}
    linhas, _r = conferir([do_sd(a)])
    assert linhas[0]['caso'] == 'estado' and linhas[0]['estado_sd'] == 'In Use'
    a['state'] = {'name': 'In Store'}
    assert conferir([do_sd(a)])[0][0]['caso'] == 'confere'


def test_hostname_repetido_no_zelo_nao_vira_palpite(app, sdl):
    """Duas máquinas com o mesmo hostname aqui dentro: a tela diz isso em vez de escolher uma."""
    for i in (1, 2):
        db.session.add(Item(codigo=f'REPETIDO{i}', categoria='Notebook', modelo='X', hostname='LMBBREPETIDO'))
    db.session.commit()
    a = _por(sdl, 'LMBBREPETIDO')
    linhas, resumo = conferir([do_sd(a)])
    l = next(x for x in linhas if x['caso'] == 'repetido')
    assert {r['codigo'] for r in l['repetidos']} == {'REPETIDO1', 'REPETIDO2'}
    assert resumo['repetido'] == 1
    assert not any(x['caso'] == 'so_zelo' and x['item']['codigo'].startswith('REPETIDO') for x in linhas)


def test_separa_o_que_falta_de_cada_lado(app, sdl):
    a = _por(sdl, 'MAQUINA-QUE-SO-EXISTE-NO-SD')
    a['serial_number'] = 'SERIAL-NOVO'
    linhas, resumo = conferir([do_sd(a)])
    novo = next(x for x in linhas if x['caso'] == 'novo')
    assert novo['sd']['hostname'] == 'MAQUINA-QUE-SO-EXISTE-NO-SD' and not novo['item']
    assert resumo['so_zelo'] > 100               # o parque do Zelo é bem maior que o do SD de teste
    assert all(x['item'] for x in linhas if x['caso'] == 'so_zelo')


def test_ativo_sem_identificacao_e_ignorado(app, sdl):
    linhas, _r = conferir([do_sd({'id': '1'}), do_sd({'id': '2', 'name': ''})])
    assert not any(x['caso'] == 'novo' for x in linhas)


# ------------------------------------------------------------------ aplicar
def test_aplicar_completa_so_o_que_foi_marcado(app, sdl):
    it = _item_com_host()
    it.tag, it.modelo = None, 'MODELO DO ZELO'
    db.session.commit()
    n, msg, det = aplicar([{'codigo': it.codigo, 'campos': {'tag': 'NOVA-TAG', 'modelo': 'MODELO DO SD',
                                                            'site': 'NAO DEVE ENTRAR'}}], 'Gabriel')
    assert n == 1
    db.session.refresh(it)
    assert it.tag == 'NOVA-TAG'
    assert it.modelo == 'MODELO DO SD'           # modelo é campo de que o SD é dono
    assert it.site != 'NAO DEVE ENTRAR'          # site é do Zelo: a importação nem olha
    assert 'tag (vazio) → NOVA-TAG' in det[0]

    n, _m, det = aplicar([{'codigo': it.codigo, 'campos': {'tag': 'NOVA-TAG'}}], 'Gabriel')
    assert n == 0 and 'nada a mudar' in det[0]


def test_aplicar_cadastra_o_que_falta(app, sdl):
    s = {'hostname': 'LMBBNOVA0001', 'tag': 'SERIALNOVO1', 'plaqueta': '', 'modelo': 'Latitude 5450',
         'tipo': 'Laptop', 'estado': 'In Store', 'usuario': '', 'site': '', 'garantia': '', 'fornecedor': ''}
    n, msg, det = aplicar([{'criar': True, 'sd': s, 'categoria': 'Notebook', 'site': 'EC'}], 'Gabriel')
    assert n == 1, det
    it = db.session.get(Item, 'SERIALNOVO1')     # sem plaqueta, o código é a service tag
    assert it and it.hostname == 'LMBBNOVA0001' and it.modelo == 'Latitude 5450'
    assert it.site == 'EC' and it.situacao == 'Em estoque' and it.origem == 'Service Desk'


def test_cadastrar_avisa_quando_o_sd_diz_que_esta_com_alguem(app, sdl):
    s = {'hostname': 'LMBBNOVA0002', 'tag': 'SERIALNOVO2', 'plaqueta': '', 'modelo': 'Latitude',
         'tipo': '', 'estado': 'In Use', 'usuario': 'MARIA DA SILVA', 'site': '', 'garantia': '', 'fornecedor': ''}
    n, _m, det = aplicar([{'criar': True, 'sd': s, 'categoria': 'Notebook'}], 'G')
    assert n == 1
    assert 'MARIA DA SILVA' in det[0] and 'Ajustar cadastro' in det[0]
    assert db.session.get(Item, 'SERIALNOVO2').situacao == 'Em estoque'


def test_aplicar_recusa_o_que_nao_da(app, sdl):
    vazio = {k: '' for k in ('hostname', 'tag', 'plaqueta', 'modelo', 'tipo', 'estado', 'usuario', 'site')}
    it = _item_com_host()
    n, msg, det = aplicar([{'codigo': 'NAO-EXISTE', 'campos': {'tag': 'X'}},
                           {'criar': True, 'sd': vazio},
                           {'criar': True, 'sd': dict(vazio, hostname=it.hostname, tag=it.codigo)}], 'G')
    assert n == 0 and 'sem efeito' in msg
    assert any('não encontrei' in d for d in det) and any('sem hostname' in d for d in det)
    assert any('já existe' in d for d in det)


# ------------------------------------------------------------------ tela
def test_tela_de_conferencia(app, cli, sdl):
    it = _item_com_host()
    it.tag = None
    db.session.commit()
    a = _por(sdl, it.hostname.upper())
    a['serial_number'] = 'TAG-QUE-FALTA'
    _por(sdl, 'SO-NO-SERVICE-DESK')['serial_number'] = 'SERIAL-SO-SD'

    assert 'Comparar agora' in cli.get('/itens/conferir-sd').data.decode()
    assert '/itens/conferir-sd' in cli.get('/itens').data.decode()      # botão na tela de Itens

    h = cli.post('/itens/conferir-sd', data={'acao': 'buscar'}).data.decode()
    assert 'Completa o cadastro' in h and 'TAG-QUE-FALTA' in h
    assert 'Falta no Zelo' in h and 'SO-NO-SERVICE-DESK' in h
    assert 'Só no Zelo' in h

    import json
    r = cli.post('/itens/conferir-sd', follow_redirects=True, data={
        'acao': 'aplicar', 'escolhas': json.dumps([{'codigo': it.codigo, 'campos': {'tag': 'TAG-QUE-FALTA'}}])})
    assert r.status_code == 200 and '1 item(ns) atualizado(s)' in r.data.decode()
    db.session.refresh(it)
    assert it.tag == 'TAG-QUE-FALTA'


def test_tela_avisa_integracao_desligada(app, cli):
    sd.salvar_conf({'sd_ativo': 'Não'})
    assert 'desligada ou sem chave' in cli.get('/itens/conferir-sd').data.decode()
    sd.salvar_conf({'sd_ativo': 'Sim'})


def test_so_no_zelo_lista_so_maquina_com_hostname(app, sdl):
    """Monitor e celular nunca estiveram no Service Desk: listá-los faria a tela virar ruído."""
    db.session.add(Item(codigo='MONITOR-SEM-HOST', categoria='Monitor', modelo='P2419', tag='MON123'))
    db.session.add(Item(codigo='MAQUINA-SEM-SD', categoria='Notebook', modelo='X', hostname='LMBBFORADOSD'))
    db.session.add(Item(codigo='SUCATA', categoria='Notebook', modelo='X', hostname='LMBBSUCATA', situacao='Baixada'))
    db.session.commit()
    linhas, _r = conferir([])
    sos = {x['item']['codigo'] for x in linhas if x['caso'] == 'so_zelo'}
    assert 'MAQUINA-SEM-SD' in sos
    assert 'MONITOR-SEM-HOST' not in sos and 'SUCATA' not in sos


# ------------------------------------------------------------------ repetido DENTRO do Service Desk

def _a(ident, host, tag=''):
    return {'id': ident, 'hostname': host, 'tag': tag, 'plaqueta': '', 'modelo': '', 'tipo': '',
            'estado': 'In Store', 'usuario': '', 'site': '', 'garantia': '', 'fornecedor': ''}


def test_duplicados_acha_a_mesma_tag_em_dois_ativos(app):
    from app.conferir_sd import duplicados
    g = duplicados([_a('1', 'NB-A', 'ABC123'), _a('2', 'NB-A-NOVO', 'abc123'), _a('3', 'NB-B', 'XYZ')])
    assert len(g) == 1 and g[0]['por'] == 'service tag'
    assert sorted(x['id'] for x in g[0]['ativos']) == ['1', '2']


def test_duplicados_acha_o_mesmo_hostname(app):
    from app.conferir_sd import duplicados
    g = duplicados([_a('1', 'NB-A', 'T1'), _a('2', 'nb-a', 'T2')])
    assert len(g) == 1 and g[0]['por'] == 'hostname'


def test_duplicados_nao_conta_o_mesmo_par_duas_vezes(app):
    """Tag E hostname repetidos é um problema só, não dois."""
    from app.conferir_sd import duplicados
    g = duplicados([_a('1', 'NB-A', 'T1'), _a('2', 'NB-A', 'T1')])
    assert len(g) == 1


def test_duplicados_ignora_vazio(app):
    from app.conferir_sd import duplicados
    assert duplicados([_a('1', '', ''), _a('2', '', ''), _a('3', 'NB-C', 'T3')]) == []


def test_tag_do_sd_tambem_sai_de_org_serial_number(app):
    """No build da MB a service tag mora em org_serial_number; lendo só serial_number a tela
    acharia que o SD não tem tag nenhuma."""
    from app.conferir_sd import do_sd
    assert do_sd({'id': '1', 'name': 'NB-X', 'org_serial_number': 'ABC123'})['tag'] == 'ABC123'
    assert do_sd({'id': '2', 'name': 'NB-Y', 'serial_number': 'DEF456'})['tag'] == 'DEF456'
