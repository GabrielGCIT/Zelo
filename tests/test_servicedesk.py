"""Integração com o Service Desk contra um simulador (o mesmo formato da API v3 on-premises)."""
import json
import re
import urllib.parse

import pytest

from app import db
from app import servicedesk as sd
from app.lancamento import gravar
from app.models import EnvioSD, Item, Pessoa


class SimuladorSD:
    """Responde como o ServiceDesk Plus: GET requests/{id}, PUT requests/{id}/upload, POST requests/{id}/notes."""

    def __init__(self, chamados):
        self.chamados = chamados          # {id: {'subject', 'status', 'requester': {...}}}
        self.anexos, self.notas, self.fora = [], [], False
        self.ativos, self.ativos_por_id, self.usuarios = {}, {}, []

    def __call__(self, metodo, url, headers, corpo):
        if self.fora:
            raise sd.ErroSD('Sem conexão com o Service Desk: simulador fora do ar')
        assert headers['authtoken'] == 'CHAVE-TESTE' and 'sdp.v3' in headers['Accept']
        u = urllib.parse.urlparse(url)
        cam = u.path
        q = urllib.parse.parse_qs(u.query)
        dados = json.loads((q.get('input_data') or ['{}'])[0]) if q else (
            json.loads(urllib.parse.parse_qs(corpo.decode())['input_data'][0]) if corpo and b'input_data' in corpo else {})
        if cam == '/api/v3/asset_assets' and metodo == 'GET':
            v = dados['list_info']['search_criteria']['value']
            return 200, json.dumps({'asset_assets': [a for a in self.ativos.values() if a['name'] == v],
                                    'response_status': [{'status': 'success'}]})
        ma = re.match(r'^/api/v3/asset_assets/(\d+)$', cam)
        if ma and metodo == 'PUT':
            a = self.ativos_por_id[ma.group(1)]
            novo = dados['asset_asset']
            a['user'] = {'id': novo['user']['id']} if novo.get('user') else None
            a['state'] = novo['state']
            return 200, json.dumps({'asset_asset': a, 'response_status': {'status': 'success'}})
        if cam == '/api/v3/users':
            sc = dados['list_info']['search_criteria']
            achados = [x for x in self.usuarios if x.get(sc['field'], '').lower() == sc['value'].lower()]
            return 200, json.dumps({'users': achados, 'response_status': [{'status': 'success'}]})
        m = re.match(r'^/api/v3/requests/(\d+)(/upload|/notes)?$', cam)
        if cam == '/api/v3/requests':
            return 200, json.dumps({'requests': [{'id': '1'}], 'response_status': [{'status': 'success'}]})
        if not m or m.group(1) not in self.chamados:
            return 404, json.dumps({'response_status': {'status': 'failed', 'messages': [{'message': 'Request not found'}]}})
        n, sub = m.group(1), m.group(2)
        if sub == '/upload':
            assert metodo == 'PUT' and b'name="input_file"' in corpo and corpo.count(b'%PDF') == 1
            nome = re.search(rb'filename="([^"]+)"', corpo).group(1).decode()
            self.anexos.append((n, nome))
            return 200, json.dumps({'response_status': {'status': 'success'}})
        if sub == '/notes':
            dados = json.loads(urllib.parse.parse_qs(corpo.decode())['input_data'][0])
            self.notas.append((n, dados['note']['description']))
            return 201, json.dumps({'note': {'id': '9'}, 'response_status': {'status': 'success'}})
        return 200, json.dumps({'request': dict(self.chamados[n], id=n), 'response_status': {'status': 'success'}})


@pytest.fixture()
def sim(app):
    p = Pessoa.query.filter(Pessoa.situacao == 'Ativo', Pessoa.tipo == 'CLT').first()
    s = SimuladorSD({'777001': {'subject': 'Entrega de notebook', 'status': {'name': 'Open'},
                                'requester': {'name': p.nome.title(), 'email_id': 'x@mb.com'}},
                     '777002': {'subject': 'Outro assunto', 'status': {'name': 'Open'},
                                'requester': {'name': 'Fulano Gestor Qualquer', 'email_id': 'g@mb.com'}}})
    sd.transporte = s
    sd.salvar_conf({'sd_url': 'http://sd.teste:8080', 'sd_chave': 'CHAVE-TESTE', 'sd_ativo': 'Sim'})
    yield s, p
    sd.transporte = None


def _nb():
    return Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                             Item.finalidade != 'Pool de empréstimo').first()


def test_pdf_do_termo(app):
    from app.routes.termo import montar
    from app.termo_pdf import gerar_pdf
    from app.models import Movimentacao
    m = Movimentacao.query.filter_by(tipo='Entrega').order_by(Movimentacao.id.desc()).first()
    pdf = gerar_pdf(montar(str(m.id))[0])
    assert pdf[:4] == b'%PDF' and len(pdf) > 1500


def test_registro_anexa_termo_e_grava_nota(app, cli, sim):
    s, p = sim
    it = _nb()
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': '777001', 'acess': 'Nenhum'}]})
    assert r.json['gravadas'] == 1
    num = r.json['resultados'][0]['nums'][0]
    assert s.anexos == [('777001', f'Termo_Zelo_{num}.pdf')]
    assert len(s.notas) == 1 and f'Nº {num}' in s.notas[0][1] and it.codigo in s.notas[0][1]
    assert EnvioSD.query.filter_by(mov_id=num).one().status == 'Enviado'


def test_service_desk_fora_nao_trava_e_reenvia(app, cli, sim):
    s, p = sim
    s.fora = True
    it = _nb()
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': '777001', 'acess': 'Nenhum'}]})
    assert r.json['gravadas'] == 1                       # o lançamento gravou
    e = EnvioSD.query.one()
    assert e.status == 'Erro' and 'Sem conexão' in e.erro
    s.fora = False
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    assert adm.post('/admin/servicedesk', data={'acao': 'reenviar'}).status_code == 302
    db.session.refresh(e)
    assert e.status == 'Enviado' and len(s.anexos) == 1 and len(s.notas) == 1


def test_chamado_inexistente_vira_erro_no_envio(app, cli, sim):
    s, p = sim
    it = _nb()
    cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': '123', 'acess': 'Nenhum'}]})
    e = EnvioSD.query.one()
    assert e.status == 'Erro' and 'not found' in e.erro


def test_espelho_mostra_solicitante_e_aponta_divergencia(app, sim):
    from app.espelho import espelho
    s, p = sim
    it = _nb()
    e = espelho({'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': '777001'})
    assert e['chamado']['solicitante'] and not any('foi aberto por' in a for a in e['atencao'])
    e = espelho({'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': '777002'})
    assert any('foi aberto por Fulano Gestor' in a for a in e['atencao'])
    e = espelho({'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': '555'})
    assert any('não existe' in a for a in e['atencao'])


def test_sem_integracao_nada_muda(app, cli):
    it = _nb()
    p = Pessoa.query.filter(Pessoa.situacao == 'Ativo', Pessoa.tipo == 'CLT').first()
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': '777001', 'acess': 'Nenhum'}]})
    assert r.json['gravadas'] == 1 and EnvioSD.query.count() == 0


def test_tela_admin(app):
    c = app.test_client()
    c.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    r = c.get('/admin/servicedesk')
    assert r.status_code == 200 and b'CHAVE' not in r.data


def test_baixar_pdf(app, cli):
    from app.models import Movimentacao
    m = Movimentacao.query.filter_by(tipo='Entrega').first()
    r = cli.get(f'/termo/{m.id}.pdf')
    assert r.status_code == 200 and r.data[:4] == b'%PDF'


def test_entrega_e_devolucao_atualizam_o_ativo(app, cli, sim):
    from app.models import EnvioSD
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook', Item.hostname.isnot(None),
                           Item.finalidade != 'Pool de empréstimo').first()
    a = {'id': '1', 'name': it.hostname.upper(), 'user': None, 'state': {'name': 'In Store'}}
    s.ativos[a['name']] = a
    s.ativos_por_id['1'] = a
    s.usuarios.append({'id': '14', 'name': p.nome, 'email_id': ''})
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    assert r.json['gravadas'] == 1
    assert a['user'] == {'id': '14'} and a['state']['name'] == 'In Use'
    assert EnvioSD.query.filter_by(tipo='ativo').one().status == 'Enviado'
    cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Devolver', 'item': it.codigo, 'receb_por': 'Adriano Santos'}]})
    assert a['user'] is None and a['state']['name'] == 'In Store'


def test_ativo_inexistente_no_sd_fica_como_erro(app, cli, sim):
    from app.models import EnvioSD
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook', Item.hostname.isnot(None),
                           Item.finalidade != 'Pool de empréstimo').first()
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    assert r.json['gravadas'] == 1
    e = EnvioSD.query.filter_by(tipo='ativo').one()
    assert e.status == 'Erro' and 'não existe no Service Desk' in e.erro


def test_migracao_acrescenta_colunas(tmp_path):
    import sqlite3
    from app import create_app
    caminho = tmp_path / 'velho.db'
    cx = sqlite3.connect(caminho)
    cx.execute('CREATE TABLE envios_sd (id INTEGER PRIMARY KEY, mov_id INTEGER, chamado VARCHAR(30), status VARCHAR(15),'
               ' anexo_ok BOOLEAN, tentativas INTEGER, erro VARCHAR(300), criado VARCHAR(25), enviado VARCHAR(25))')
    cx.commit()
    cx.close()
    create_app(f'sqlite:///{caminho}', testing=True)
    cols = {r[1] for r in sqlite3.connect(caminho).execute('PRAGMA table_info(envios_sd)')}
    assert {'tipo', 'alvo'} <= cols
