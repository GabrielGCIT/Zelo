"""Ativos × Service Desk: importar o que falta e enxergar onde os dois discordam."""
from datetime import date, datetime, timedelta

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


# ------------------------------------------------------------------ hostname com domínio (agente)

def test_casa_o_ativo_do_agente_pelo_nome_curto(app, sdl):
    """O agente batiza a máquina com o domínio; a planilha guarda o nome curto. Comparados crus,
    toda máquina com agente virava "Falta no Zelo" e a mesma máquina, "Só no Zelo"."""
    it = _item_com_host()
    a = _por(sdl, it.hostname.lower() + '.reyesholdings.com')
    a['service_tag'] = it.tag or ''
    linhas, _r = conferir([do_sd(a)])
    l = linhas[0]
    assert l['item'] and l['item']['codigo'] == it.codigo
    assert not any(d[0] == 'hostname' for d in l['difere'])      # o domínio não é divergência


def test_hostname_que_falta_entra_curto(app, sdl):
    """Marcar 'Completa o cadastro' não pode gravar o domínio no Zelo."""
    it = Item.query.filter(Item.tag.isnot(None), Item.tag != '',
                           (Item.hostname.is_(None)) | (Item.hostname == '')).first()
    a = _por(sdl, 'lmbcompleta.reyesholdings.com')
    a['service_tag'] = it.tag
    l = conferir([do_sd(a)])[0][0]
    assert ('hostname', 'LMBCOMPLETA') in l['faltam']


def test_duplicado_no_sd_entre_registro_manual_e_agente(app):
    """'LMB123' criado à mão e 'lmb123.dominio' criado pelo agente são a mesma máquina duas vezes —
    é justamente o que o teste de fusão do agente quer enxergar."""
    from app.conferir_sd import duplicados
    g = duplicados([_a('1', 'LMB123', 'T1'), _a('2', 'lmb123.reyesholdings.com', '')])
    assert len(g) == 1 and g[0]['por'] == 'hostname'


# ------------------------------------------------------------------ cobertura do agente

def _em_uso():
    """Notebook em uso, com hostname único, matrícula e data de entrega."""
    from sqlalchemy import func
    repetidos = [h for h, n in db.session.query(Item.hostname, func.count('*')).group_by(Item.hostname).all()
                 if n > 1 and h]
    return (Item.query.filter(Item.hostname.isnot(None), Item.hostname != '', Item.categoria == 'Notebook',
                              Item.situacao == 'Em uso', Item.desde.isnot(None), Item.desde != '',
                              Item.matricula.isnot(None), ~Item.hostname.in_(repetidos))
            .order_by(Item.codigo).first())


def _hoje(it, dias):
    return date.fromisoformat(it.desde[:10]) + timedelta(days=dias)


def _varrido(sdl, it, quando, login=''):
    """Ativo como o agente deixa: nome com domínio, tag em service_tag, varredura em epoch ms."""
    a = _por(sdl, it.hostname.lower() + '.reyesholdings.com')
    a['service_tag'] = it.tag or ''
    ms = int(datetime(quando.year, quando.month, quando.day, 12).timestamp() * 1000)
    a['last_scan_success_time'] = {'value': str(ms), 'display_value': quando.isoformat()}
    a['last_logged_user'] = login
    return a


def test_le_os_campos_do_agente():
    a = do_sd({'name': 'X', 'last_scan_success_time': {'value': '1813046399000'},
               'last_logged_user': 'REYES\\fulano'})
    assert a['varredura'] == datetime.fromtimestamp(1813046399).date().isoformat()
    assert a['logado'] == 'REYES\\fulano' and a['campos_agente']
    assert not do_sd({'name': 'X'})['campos_agente']
    assert do_sd({'name': 'X', 'last_scan_success_time': '2026-11-10T08:00:00'})['varredura'] == '2026-11-10'
    assert do_sd({'name': 'X', 'last_scan_success_time': 'lixo'})['varredura'] == ''


def test_login_curto():
    from app.conferir_sd import login_curto
    assert login_curto('REYES\\Fulano') == login_curto('fulano@mb.com') == login_curto('FULANO') == 'fulano'
    assert login_curto(None) == ''


def test_entregue_sem_agente_respeita_o_prazo(app, sdl):
    """Recém-entregue sem agente é normal (o Suporte instala à mão); semanas depois, não."""
    from app.conferir_sd import cobertura
    it = _em_uso()
    c = cobertura([], hoje=_hoje(it, 2))
    assert it.codigo not in {x['item']['codigo'] for x in c['sem_agente']} and c['aguardando'] >= 1
    c = cobertura([], hoje=_hoje(it, 30))
    l = next(x for x in c['sem_agente'] if x['item']['codigo'] == it.codigo)
    assert l['dias'] == 30 and l['motivo'] == 'não está no SD'


def test_em_uso_sai_do_so_no_zelo(app, sdl):
    """A máquina em uso é assunto da cobertura; listar nas duas seções dobra o trabalho."""
    it = _em_uso()
    linhas, _r = conferir([])
    assert it.codigo not in {x['item']['codigo'] for x in linhas if x['caso'] == 'so_zelo'}


def test_cadastro_manual_nunca_varrido_conta_como_sem_agente(app, sdl):
    from app.conferir_sd import cobertura
    it = _em_uso()
    manual = _por(sdl, it.hostname.upper())
    manual['service_tag'] = it.tag or ''
    manual['last_scan_success_time'] = None          # o campo veio, vazio: nunca houve varredura
    c = cobertura([do_sd(manual)], hoje=_hoje(it, 30))
    l = next(x for x in c['sem_agente'] if x['item']['codigo'] == it.codigo)
    assert 'nunca varrida' in l['motivo']


def test_sem_campos_do_agente_nao_acusa_cadastro_manual(app, sdl):
    """Se a listagem não trouxe os campos do agente, não dá para dizer que ninguém varreu."""
    from app.conferir_sd import cobertura
    it = _em_uso()
    a = _por(sdl, it.hostname.upper())
    a['service_tag'] = it.tag or ''
    c = cobertura([do_sd(a)], hoje=_hoje(it, 30))
    assert not c['veio_agente']
    assert it.codigo not in {x['item']['codigo'] for x in c['sem_agente']}


def test_agente_parou_de_ver(app, sdl):
    from app.conferir_sd import cobertura
    it = _em_uso()
    hoje = _hoje(it, 100)
    a = _varrido(sdl, it, hoje - timedelta(days=45))
    l = next(x for x in cobertura([do_sd(a)], hoje=hoje)['parou'] if x['item']['codigo'] == it.codigo)
    assert l['dias'] == 45
    a = _varrido(sdl, it, hoje - timedelta(days=3))
    assert it.codigo not in {x['item']['codigo'] for x in cobertura([do_sd(a)], hoje=hoje)['parou']}


def test_quem_usa_difere_compara_login_sem_dominio(app, sdl):
    from app.conferir_sd import cobertura
    it = _em_uso()
    db.session.get(Pessoa, it.matricula).user = 'dominio\\dono.certo'
    db.session.commit()
    hoje = _hoje(it, 100)
    a = _varrido(sdl, it, hoje - timedelta(days=1), login='REYES\\DONO.CERTO')
    assert it.codigo not in {x['item']['codigo'] for x in cobertura([do_sd(a)], hoje=hoje)['quem_usa']}
    a = _varrido(sdl, it, hoje - timedelta(days=1), login='REYES\\outra.pessoa')
    l = next(x for x in cobertura([do_sd(a)], hoje=hoje)['quem_usa'] if x['item']['codigo'] == it.codigo)
    assert l['login_zelo'] == 'dono.certo' and l['login_sd'] == 'outra.pessoa'


def test_login_de_varredura_velha_nao_conta(app, sdl):
    """Quem usou a máquina há dois meses não diz quem está com ela hoje."""
    from app.conferir_sd import cobertura
    it = _em_uso()
    db.session.get(Pessoa, it.matricula).user = 'dono.certo'
    db.session.commit()
    hoje = _hoje(it, 200)
    a = _varrido(sdl, it, hoje - timedelta(days=60), login='outra.pessoa')
    assert it.codigo not in {x['item']['codigo'] for x in cobertura([do_sd(a)], hoje=hoje)['quem_usa']}


def test_sem_login_no_zelo_nao_vira_divergencia(app, sdl):
    from app.conferir_sd import cobertura
    it = _em_uso()
    db.session.get(Pessoa, it.matricula).user = None
    db.session.commit()
    hoje = _hoje(it, 100)
    a = _varrido(sdl, it, hoje - timedelta(days=1), login='alguem')
    c = cobertura([do_sd(a)], hoje=hoje)
    assert it.codigo not in {x['item']['codigo'] for x in c['quem_usa']} and c['sem_login'] >= 1


def test_login_em_maquina_que_o_zelo_diz_estar_em_estoque(app, sdl):
    from app.conferir_sd import cobertura
    it = _item_com_host()                                    # Em estoque
    a = _varrido(sdl, it, date.today() - timedelta(days=1), login='REYES\\alguem')
    l = next(x for x in cobertura([do_sd(a)])['quem_usa'] if x['item']['codigo'] == it.codigo)
    assert l['login_zelo'] == '' and l['login_sd'] == 'alguem'


def test_tela_mostra_a_cobertura(app, cli, sdl):
    it = _em_uso()
    _por(sdl, 'OUTRA-MAQUINA')
    h = cli.post('/itens/conferir-sd', data={'acao': 'buscar'}).data.decode()
    assert 'Cobertura do agente' in h and 'Entregue e sem agente' in h
    assert 'não devolveu data de varredura' in h             # o SD de teste não trouxe os campos
    assert it.codigo in h
