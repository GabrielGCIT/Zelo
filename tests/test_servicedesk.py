"""Integração com o Service Desk contra um simulador (o mesmo formato da API v3 on-premises)."""
import json
import re
import urllib.parse

import pytest

from app import db
from app import servicedesk as sd
from app.lancamento import gravar
from app.models import EnvioSD, Item, Movimentacao, Pessoa


class SimuladorSD:
    """Responde como o ServiceDesk Plus: GET requests/{id}, PUT requests/{id}/upload, POST requests/{id}/notes."""

    def __init__(self, chamados):
        self.chamados = chamados          # {id: {'subject', 'status', 'requester': {...}}}
        self.anexos, self.notas, self.fora = [], [], False
        self.ativos, self.ativos_por_id, self.usuarios = {}, {}, []
        self.apagados, self.seq, self.recusa_post, self.recusa_campo = [], 500, '', ''
        self.ignora_campo = ''
        # como o build de verdade: um endereço por tipo de produto, e asset_assets não cria
        self.modulos = [{'id': '1', 'display_name': 'Laptop', 'api_name': 'asset_computer',
                         'api_plural_name': 'asset_computers', 'category': {'display_name': 'Asset'}},
                        {'id': '2', 'display_name': 'Monitor', 'api_name': 'asset_monitor',
                         'api_plural_name': 'asset_monitors', 'category': {'display_name': 'Asset'}}]
        self.produtos = [{'id': '77', 'name': 'Latitude 5450', 'product_type': {'name': 'Laptop'}},
                         {'id': '78', 'name': 'P2422H', 'product_type': {'name': 'Monitor'}}]

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
            li = dados['list_info']
            if 'search_criteria' in li:
                v = li['search_criteria']['value']
                # o SDP não diferencia maiúscula de minúscula na busca por nome
                return 200, json.dumps({'asset_assets': [a for a in self.ativos.values()
                                                         if (a['name'] or '').upper() == (v or '').upper()],
                                        'response_status': [{'status': 'success'}]})
            todos = list(self.ativos.values())                      # listagem paginada
            ini, n = li.get('start_index', 1), li.get('row_count', 100)
            pagina = todos[ini - 1:ini - 1 + n]
            return 200, json.dumps({'asset_assets': pagina, 'response_status': [{'status': 'success'}],
                                    'list_info': {'has_more_rows': ini - 1 + n < len(todos),
                                                  'row_count': len(pagina)}})
        mi = re.match(r'^/api/v3/(asset_[a-z_0-9]+)/_metainfo$', cam)
        if mi:
            campos = getattr(self, 'campos_metainfo', None) or ['name', 'product', 'asset_tag']
            return 200, json.dumps({'metainfo': {'fields': [
                {'name': c, 'mandatory': c in ('name', 'product')} for c in campos]},
                'response_status': {'status': 'success'}})
        if cam == '/api/v3/products':
            li = dados.get('list_info') or {}
            ini, n = li.get('start_index', 1), li.get('row_count', 100)
            pagina = self.produtos[ini - 1:ini - 1 + n]
            return 200, json.dumps({'products': pagina, 'response_status': [{'status': 'success'}],
                                    'list_info': {'has_more_rows': ini - 1 + n < len(self.produtos)}})
        if cam == '/api/v3/requests/assets/module':
            li = dados.get('list_info') or {}
            ini, n = li.get('start_index', 1), li.get('row_count', 10)   # sem row_count: só 10
            pagina = self.modulos[ini - 1:ini - 1 + n]
            return 200, json.dumps({'module': pagina, 'response_status': [{'status': 'success'}],
                                    'list_info': {'has_more_rows': ini - 1 + n < len(self.modulos)}})
        if cam == '/api/v3/asset_assets' and metodo == 'POST':
            # como no build de verdade: o endereço geral NÃO cria
            return 404, json.dumps({'response_status': {'status': 'failed', 'messages': [
                {'message': 'Cannot add asset under Asset product type.'}]}})
        mf = re.match(r'^/api/v3/(asset_[a-z_0-9]+)/(\d+)$', cam)
        if mf and metodo == 'GET':                     # ficha completa, pelo endereço do módulo
            mod = next((m for m in self.modulos if m['api_plural_name'] == mf.group(1)), None)
            a = self.ativos_por_id.get(mf.group(2))
            if not mod or not a:
                return 404, json.dumps({'response_status': {'status': 'failed',
                                                            'messages': [{'message': 'Not found'}]}})
            return 200, json.dumps({mod['api_name']: a, 'response_status': {'status': 'success'}})
        mc = re.match(r'^/api/v3/(asset_[a-z_]+)$', cam)
        if mc and metodo == 'POST':
            mod = next((m for m in self.modulos if m['api_plural_name'] == mc.group(1)), None)
            if not mod:
                return 404, json.dumps({'response_status': {'status': 'failed',
                                                            'messages': [{'message': 'No such module'}]}})
            novo = dict(dados[mod['api_name']])
            if novo['name'] in self.ativos:
                return 400, json.dumps({'response_status': {'status': 'failed',
                                                            'messages': [{'message': 'Asset name already exists'}]}})
            if self.recusa_post:
                return 400, json.dumps({'response_status': {'status': 'failed',
                                                            'messages': [{'message': self.recusa_post}]}})
            if self.recusa_campo and self.recusa_campo in novo:   # como o SDP: não diz qual campo
                return 400, json.dumps({'response_status': {'status': 'failed',
                                                            'messages': [{'message': 'Invalid Input'}]}})
            if self.ignora_campo:                 # aceita a chamada e descarta o valor
                novo.pop(self.ignora_campo, None)
            self.seq += 1
            novo['id'] = str(self.seq)
            self.ativos[novo['name']] = novo
            self.ativos_por_id[novo['id']] = novo
            return 201, json.dumps({mod['api_name']: novo, 'response_status': {'status': 'success'}})
        ma = re.match(r'^/api/v3/asset_assets/(\d+)$', cam)
        if ma and metodo == 'DELETE':
            a = self.ativos_por_id.pop(ma.group(1), None)
            if a:
                self.ativos.pop(a['name'], None)
            self.apagados.append(ma.group(1))
            return 200, json.dumps({'response_status': {'status': 'success'}})
        if ma and metodo == 'PUT':
            a = self.ativos_por_id[ma.group(1)]
            novo = dados['asset_asset']
            a['user'] = {'id': novo['user']['id']} if novo.get('user') else None
            if 'state' in novo:                                     # sem 'state' = não mexer
                a['state'] = novo['state']
            for k, v in novo.items():                               # plaqueta, site, fornecedor...
                if k not in ('user', 'state'):
                    a[k] = v
            return 200, json.dumps({'asset_asset': a, 'response_status': {'status': 'success'}})
        if cam == '/api/v3/users':
            li = dados['list_info']
            if 'search_criteria' in li:
                sc = li['search_criteria']
                achados = [x for x in self.usuarios if x.get(sc['field'], '').lower() == sc['value'].lower()]
                return 200, json.dumps({'users': achados, 'response_status': [{'status': 'success'}]})
            ini, n = li.get('start_index', 1), li.get('row_count', 100)     # listagem paginada
            pagina = self.usuarios[ini - 1:ini - 1 + n]
            return 200, json.dumps({'users': pagina, 'response_status': [{'status': 'success'}],
                                    'list_info': {'has_more_rows': ini - 1 + n < len(self.usuarios),
                                                  'row_count': len(pagina)}})
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
        if metodo == 'PUT':
            self.chamados[n].update(dados['request'])
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


def _entrega_com_termo(cli, p, chamado='777001'):
    """Entrega gravada, com o termo assinado guardado no Zelo."""
    import io
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                           Item.finalidade != 'Pool de empréstimo').first()
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'chamado': chamado, 'acess': 'Nenhum'}]})
    num = r.json['resultados'][0]['nums'][0]
    cli.post(f'/termo/{num}/assinado', data={'arquivo': (io.BytesIO(b'%PDF-1.4 assinado'), 'termo.pdf')},
             content_type='multipart/form-data', headers={'X-Requested-With': 'fetch'})
    return num


def test_termo_assinado_vai_para_o_chamado(app, cli, sim):
    from app.models import EnvioSD
    s, p = sim
    num = _entrega_com_termo(cli, p)
    assert ('777001', f'Termo_assinado_Zelo_{num}.pdf') in s.anexos
    assert any('Termo ASSINADO' in t for _n, t in s.notas)
    assert EnvioSD.query.filter_by(mov_id=num, tipo='termo').one().status == 'Enviado'


def test_termo_assinado_com_o_sd_fora_fica_na_fila(app, cli, sim):
    from app.models import EnvioSD
    s, p = sim
    s.fora = True
    num = _entrega_com_termo(cli, p)
    e = EnvioSD.query.filter_by(mov_id=num, tipo='termo').one()
    assert e.status == 'Erro' and db.session.get(Movimentacao, num).termo_arquivo      # o termo ficou guardado
    s.fora = False
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    adm.post('/admin/servicedesk', data={'acao': 'reenviar'})
    db.session.refresh(e)
    assert e.status == 'Enviado' and ('777001', f'Termo_assinado_Zelo_{num}.pdf') in s.anexos


def test_chamado_informado_depois_leva_o_termo_assinado(app, cli, sim):
    import io
    from app.models import EnvioSD
    s, p = sim
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook',
                           Item.finalidade != 'Pool de empréstimo').first()
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    num = r.json['resultados'][0]['nums'][0]
    cli.post(f'/termo/{num}/assinado', data={'arquivo': (io.BytesIO(b'%PDF-1.4 assinado'), 't.pdf')},
             content_type='multipart/form-data', headers={'X-Requested-With': 'fetch'})
    assert not s.anexos                                        # sem chamado, nada foi enviado
    assert cli.post('/api/acompanhar/marca', json={'id': num, 'campo': 'chamado', 'valor': '777001'}).json['ok']
    tipos = {e.tipo for e in EnvioSD.query.filter_by(mov_id=num)}
    assert {'chamado', 'termo'} <= tipos
    assert ('777001', f'Termo_assinado_Zelo_{num}.pdf') in s.anexos


def test_desligamento_avisa_o_service_desk(app, cli, sim):
    """Devolução pela fila do desligamento vale como qualquer outra: solta o ativo no Service Desk."""
    from app.models import EnvioSD, Pessoa
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook', Item.hostname.isnot(None),
                           Item.finalidade != 'Pool de empréstimo').first()
    a = {'id': '70', 'name': it.hostname.upper(), 'user': None, 'state': {'name': 'In Store'}}
    s.ativos[a['name']] = a
    s.ativos_por_id['70'] = a
    s.usuarios.append({'id': '71', 'name': p.nome, 'email_id': ''})
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    assert r.json['gravadas'] == 1 and a['state']['name'] == 'In Use'

    p.situacao = 'Desligado'
    db.session.commit()
    r = cli.post(f'/desligamento/{p.id}', data={'item': [it.codigo]}, follow_redirects=True)
    assert r.status_code == 200
    assert a['user'] is None and a['state']['name'] == 'In Store'       # saiu do nome de quem foi desligado
    env = EnvioSD.query.filter_by(tipo='ativo').order_by(EnvioSD.id.desc()).first()
    assert env.status == 'Enviado' and 'In Store' in (env.erro or '')


# ------------------------------------------------------------------ ciclo completo do ativo

def _ativo_do(s, it, ident='90'):
    a = {'id': ident, 'name': (it.hostname or '').upper(), 'user': None, 'state': {'name': 'In Store'}}
    s.ativos[a['name']] = a
    s.ativos_por_id[ident] = a
    return a


def _com_host():
    return Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook', Item.hostname.isnot(None),
                             Item.finalidade != 'Pool de empréstimo').first()


def test_manutencao_poe_em_in_repair_e_o_fechamento_desfaz(app, cli, sim):
    """Manutenção não gera movimentação, mas o ativo no Service Desk tem que acompanhar."""
    s, _p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = _com_host()
    a = _ativo_do(s, it, '90')
    r = cli.post('/manutencao', data={'acao': 'Abrir ocorrência', 'item': it.codigo, 'defeito': 'Tela trincada'},
                 follow_redirects=True)
    assert r.status_code == 200
    assert a['state']['name'] == 'In Repair'
    env = EnvioSD.query.filter(EnvioSD.tipo == 'ativo').order_by(EnvioSD.id.desc()).first()
    assert env.status == 'Enviado' and env.mov_id is None and env.alvo == it.hostname.upper()
    cli.post('/manutencao', data={'acao': 'Fechar ocorrência', 'item': it.codigo, 'feito': 'Tela trocada'},
             follow_redirects=True)
    assert a['state']['name'] == 'In Store'          # voltou ao estoque


def test_baixa_pelo_ajuste_expira_o_ativo(app, cli, sim):
    s, _p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = _com_host()
    a = _ativo_do(s, it, '91')
    r = cli.post('/ajuste', data={'item': it.codigo, 'situacao': 'Baixada', 'motivo': 'Item conferido fisicamente',
                                  'obs': 'Sucateado'}, follow_redirects=True)
    assert r.status_code == 200
    assert db.session.get(Item, it.codigo).situacao == 'Baixada'
    assert a['state']['name'] == 'Expired' and a['user'] is None


def test_situacao_sem_mapa_nao_mexe_no_estado(app, cli, sim):
    """'A localizar' não tem equivalente no Service Desk: melhor não mentir um estado."""
    s, _p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = _com_host()
    a = _ativo_do(s, it, '92')
    a['state'] = {'name': 'In Use'}
    cli.post('/ajuste', data={'item': it.codigo, 'situacao': 'A localizar', 'motivo': 'Item conferido fisicamente'},
             follow_redirects=True)
    assert a['state']['name'] == 'In Use'            # intocado
    env = EnvioSD.query.filter(EnvioSD.tipo == 'ativo').order_by(EnvioSD.id.desc()).first()
    assert env.status == 'Enviado' and 'inalterado' in (env.erro or '')


def test_sd_estados_sobrepoe_o_padrao(app, cli, sim):
    s, _p = sim
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_estados': 'Manutenção = Em conserto; Baixada ='})
    assert sd.mapa_estados()['Manutenção'] == 'Em conserto'
    assert sd.mapa_estados()['Baixada'] is None      # vazio = não mexer
    it = _com_host()
    a = _ativo_do(s, it, '93')
    cli.post('/manutencao', data={'acao': 'Abrir ocorrência', 'item': it.codigo, 'defeito': 'Não liga'},
             follow_redirects=True)
    assert a['state']['name'] == 'Em conserto'


def test_anexar_ativo_ao_chamado_preserva_os_que_estavam(app, sim):
    s, _p = sim
    s.chamados['777001']['assets'] = [{'id': '55', 'name': 'OUTRA-MAQUINA'}]
    ok, recado = sd.anexar_ativo_ao_chamado('777001', 'nb-novo')
    assert ok and 'NB-NOVO' in recado
    nomes = [a.get('name') for a in s.chamados['777001']['assets']]
    assert {'id': '55'} in s.chamados['777001']['assets'] or '55' in str(s.chamados['777001']['assets'])
    assert 'NB-NOVO' in nomes
    ok, recado = sd.anexar_ativo_ao_chamado('777001', 'NB-NOVO')      # idempotente
    assert ok and 'já estava' in recado


def test_anexar_ativo_em_chamado_inexistente_nao_levanta(app, sim):
    ok, recado = sd.anexar_ativo_ao_chamado('777999', 'NB-X')
    assert not ok and 'não deu para anexar' in recado


def test_entrega_anexa_o_ativo_ao_chamado_quando_ligado(app, cli, sim):
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_anexar_ativo': 'Sim'})
    it = _com_host()
    a = _ativo_do(s, it, '94')
    s.usuarios.append({'id': '94', 'name': p.nome, 'email_id': ''})
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum', 'chamado': '777001'}]})
    assert r.json['gravadas'] == 1 and a['state']['name'] == 'In Use'
    assert any((x.get('name') or '') == it.hostname.upper() for x in s.chamados['777001'].get('assets') or [])


def test_enfileirar_item_nao_duplica_pendencia(app, sim):
    s, _p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = _com_host()
    s.fora = True                                    # força o envio a ficar pendente
    sd.enfileirar_item(app, it)
    s.fora = False
    pend = EnvioSD.query.filter(EnvioSD.tipo == 'ativo', EnvioSD.status == 'Pendente').count()
    sd.enfileirar_item(app, it)
    assert EnvioSD.query.filter(EnvioSD.tipo == 'ativo', EnvioSD.status == 'Pendente').count() == pend


# ------------------------------------------------------------------ o Zelo cadastrando no SD

def test_sem_criar_ligado_ativo_ausente_continua_erro(app, cli, sim):
    """A criação é opt-in: quem não ligou continua vendo o erro, e não ganha ativo novo sem pedir."""
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = _com_host()
    cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    e = EnvioSD.query.filter_by(tipo='ativo').one()
    assert e.status == 'Erro' and 'não existe no Service Desk' in e.erro
    assert not s.ativos


def test_criar_ativo_leva_hostname_tag_e_plaqueta(app, cli, sim):
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_criar_ativo': 'Sim'})
    it = _com_host()
    it.tag, it.plaqueta, it.site = 'ABC1234', 'MB-0099', 'EC'
    db.session.commit()
    s.usuarios.append({'id': '31', 'name': p.nome, 'email_id': ''})
    r = cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    assert r.json['gravadas'] == 1
    a = s.ativos[it.hostname.upper()]
    assert a['serial_number'] == 'ABC1234' and a['asset_tag'] == 'MB-0099'
    assert a['site'] == {'name': 'EC'}
    # o tipo de produto escolhe o endereço e para por aí: no corpo seria redundante, e o SDP recusa
    assert 'product_type' not in a and a['product'] == {'id': '77'}
    assert a['user'] == {'id': '31'} and a['state']['name'] == 'In Use'
    e = EnvioSD.query.filter_by(tipo='ativo').one()
    assert e.status == 'Enviado' and 'cadastrado agora' in (e.erro or '')


def test_campo_vazio_nao_entra_no_corpo(app, sim):
    """No SDP mandar nulo apaga o que está lá; não mandar o campo deixa como está."""
    from types import SimpleNamespace
    it = SimpleNamespace(hostname='NB-X', tag='', plaqueta='', categoria='Monitor', site='',
                         fornecedor='', garantia='')
    c = sd.corpo_do_item(it)
    assert c == {'name': 'NB-X', 'product_type': {'name': 'Monitor'}}


def test_categoria_sem_tipo_cria_sem_product_type(app, sim):
    from types import SimpleNamespace
    it = SimpleNamespace(hostname='KIOSK-1', tag='', plaqueta='', categoria='Kiosk', site='',
                         fornecedor='', garantia='')
    assert 'product_type' not in sd.corpo_do_item(it)


def test_sd_tipos_sobrepoe_o_padrao(app, sim):
    from types import SimpleNamespace
    sd.salvar_conf({'sd_tipos': 'Notebook = Notebook MB; Monitor ='})
    it = SimpleNamespace(hostname='NB-Y', tag='', plaqueta='', categoria='Notebook', site='',
                         fornecedor='', garantia='')
    assert sd.corpo_do_item(it)['product_type'] == {'name': 'Notebook MB'}
    assert 'product_type' not in sd.corpo_do_item(SimpleNamespace(
        hostname='MON-1', tag='', plaqueta='', categoria='Monitor', site='', fornecedor='', garantia=''))


def test_item_sem_hostname_nao_tenta_criar(app, sim):
    from types import SimpleNamespace
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_criar_ativo': 'Sim'})
    it = SimpleNamespace(hostname='', tag='ABC', plaqueta='', categoria='Celular', site='',
                         fornecedor='', garantia='')
    with pytest.raises(sd.ErroSD, match='sem hostname'):
        sd.criar_ativo(it)


def test_diagnostico_cria_confere_e_apaga(app, sim):
    s, _p = sim
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok and 'apagado' in texto
    assert 'OK   name' in texto and 'OK   serial_number' in texto
    assert s.apagados and not s.ativos            # não deixou lixo no Service Desk


def test_diagnostico_relata_a_recusa_sem_levantar(app, sim):
    s, _p = sim
    s.recusa_post = 'product_type is not valid'
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert not ok and 'FALHOU' in texto and 'product_type is not valid' in texto
    assert 'Campos mandados' in texto and not s.ativos


def test_diagnostico_na_tela_de_administracao(app, sim):
    s, _p = sim
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    r = adm.post('/admin/servicedesk', data={'acao': 'diagnostico'}, follow_redirects=True)
    assert r.status_code == 200
    assert 'Diagnóstico de criação de ativo' in r.get_data(as_text=True)
    assert not s.ativos


def test_campos_do_zelo_so_vao_quando_ligado(app, cli, sim):
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim'})
    it = _com_host()
    it.plaqueta, it.site = 'MB-0100', 'GR'
    db.session.commit()
    a = _ativo_do(s, it, '95')
    a['asset_tag'] = 'POSTO-A-MAO'
    s.usuarios.append({'id': '95', 'name': p.nome, 'email_id': ''})
    cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    assert a['asset_tag'] == 'POSTO-A-MAO'            # desligado: não encosta
    sd.salvar_conf({'sd_campos_zelo': 'Sim'})
    cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Devolver', 'item': it.codigo, 'receb_por': 'Adriano Santos'}]})
    assert a['asset_tag'] == 'MB-0100' and a['site'] == {'name': 'GR'}


def test_campos_do_zelo_nao_mexem_em_hostname_nem_tag(app, cli, sim):
    """A regra de dono: o que a máquina diz de si mesma é do agente, não do Zelo."""
    s, p = sim
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_campos_zelo': 'Sim'})
    it = _com_host()
    it.tag, it.plaqueta = 'TAG-DO-ZELO', 'MB-0101'
    db.session.commit()
    a = _ativo_do(s, it, '96')
    a['serial_number'] = 'TAG-DO-AGENTE'
    s.usuarios.append({'id': '96', 'name': p.nome, 'email_id': ''})
    cli.post('/api/lancar/gravar', json={'aba': 'entrega', 'linhas': [
        {'acao': 'Entregar agora', 'item': it.codigo, 'para': p.id, 'acess': 'Nenhum'}]})
    assert a['serial_number'] == 'TAG-DO-AGENTE'      # intocado
    assert a['asset_tag'] == 'MB-0101'                # esse sim
    e = EnvioSD.query.filter_by(tipo='ativo').one()
    assert 'service tag no SD' in (e.erro or '')      # divergência fica avisada, não corrigida


def test_salvar_uma_ficha_nao_zera_a_outra(app, sim):
    """A tela tem duas fichas; cada POST traz só os campos dela."""
    sd.salvar_conf({'sd_ativos': 'Sim', 'sd_criar_ativo': 'Sim', 'sd_campos_zelo': 'Sim'})
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    adm.post('/admin/servicedesk', data={'acao': 'salvar', 'sd_url': 'http://sd.teste:8080',
                                         'sd_ssl': 'Verificar', 'sd_ativo': 'Sim'})
    assert sd.conf('sd_ativos') == 'Sim' and sd.conf('sd_criar_ativo') == 'Sim'
    adm.post('/admin/servicedesk', data={'acao': 'salvar', 'sd_ativos': 'Sim', 'sd_anexar_ativo': 'Não',
                                         'sd_criar_ativo': 'Não', 'sd_campos_zelo': 'Não',
                                         'sd_estados': '', 'sd_tipos': ''})
    assert sd.conf('sd_url') == 'http://sd.teste:8080' and sd.conf('sd_ativo') == 'Sim'
    assert sd.conf('sd_criar_ativo') == 'Não'


# ------------------------------------------------------------------ um endereço por tipo

def test_criacao_vai_no_endereco_do_tipo_nao_no_geral(app, sim):
    """asset_assets não cria ativo: cada tipo de produto tem o seu endereço."""
    from types import SimpleNamespace
    s, _p = sim
    it = SimpleNamespace(hostname='NB-ENDERECO', tag='T1', plaqueta='', categoria='Notebook',
                         site='', fornecedor='', garantia='')
    novo = sd.criar_ativo(it, 'In Store')
    assert novo['id'] and s.ativos['NB-ENDERECO']['serial_number'] == 'T1'
    assert sd.modulo_do_tipo('Laptop')['api_plural_name'] == 'asset_computers'


def test_tipo_que_nao_existe_no_sd_lista_os_que_existem(app, sim):
    from types import SimpleNamespace
    sd.salvar_conf({'sd_tipos': 'Notebook = Ultrabook'})
    it = SimpleNamespace(hostname='NB-Z', tag='', plaqueta='', categoria='Notebook', site='',
                         fornecedor='', garantia='')
    with pytest.raises(sd.ErroSD) as e:
        sd.criar_ativo(it)
    assert 'não existe no seu Service Desk' in str(e.value) and 'Laptop' in str(e.value)


def test_categoria_sem_tipo_nao_tenta_criar(app, sim):
    """Sem tipo não há endereço para onde mandar: erro claro em vez de 404 do SDP."""
    from types import SimpleNamespace
    it = SimpleNamespace(hostname='KIOSK-9', tag='', plaqueta='', categoria='Kiosk', site='',
                         fornecedor='', garantia='')
    with pytest.raises(sd.ErroSD, match='sem tipo de produto'):
        sd.criar_ativo(it)


def test_diagnostico_mostra_os_tipos_do_build(app, sim):
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok
    assert '/api/v3/asset_computers' in texto and '/api/v3/asset_monitors' in texto
    assert 'Tipos de produto no seu Service Desk (2)' in texto


def test_diagnostico_sem_a_lista_de_tipos_para_antes_de_criar(app, sim):
    s, _p = sim
    s.fora = True
    ok, linhas = sd.diagnostico_criacao()
    assert not ok and 'não cria ativo' in '\n'.join(linhas)
    s.fora = False


def test_criacao_leva_o_produto_que_existe_no_sd(app, sim):
    """O SDP exige um produto, e ele tem que já existir lá: pelo modelo, ou um do mesmo tipo."""
    from types import SimpleNamespace
    s, _p = sim
    it = SimpleNamespace(hostname='NB-PROD', tag='', plaqueta='', categoria='Notebook', site='',
                         fornecedor='', garantia='', modelo='Latitude 5450')
    sd.criar_ativo(it, 'In Store')
    assert s.ativos['NB-PROD']['product'] == {'id': '77'}
    it2 = SimpleNamespace(hostname='NB-SEMMOD', tag='', plaqueta='', categoria='Notebook', site='',
                          fornecedor='', garantia='', modelo='Modelo que não existe lá')
    sd.criar_ativo(it2, 'In Store')
    assert s.ativos['NB-SEMMOD']['product'] == {'id': '77'}     # cai no produto do tipo


def test_zelo_nao_cria_produto_no_sd(app, sim):
    """Sem produto, não inventa um: para com o motivo em vez de deixar o SDP dizer só
    "Value not provided"."""
    from types import SimpleNamespace
    s, _p = sim
    s.produtos = []
    it = SimpleNamespace(hostname='NB-SEMPROD', tag='', plaqueta='', categoria='Notebook', site='',
                         fornecedor='', garantia='', modelo='X')
    with pytest.raises(sd.ErroSD, match='exige um produto'):
        sd.criar_ativo(it, 'In Store')
    assert 'NB-SEMPROD' not in s.ativos


def test_sem_produto_do_tipo_a_mensagem_diz_quantos_existem(app, sim):
    from types import SimpleNamespace
    s, _p = sim
    s.produtos = [{'id': '9', 'name': 'Impressora X', 'product_type': {'name': 'Printer'}}]
    it = SimpleNamespace(hostname='NB-T', tag='', plaqueta='', categoria='Notebook', site='',
                         fornecedor='', garantia='', modelo='')
    with pytest.raises(sd.ErroSD, match='nenhum do tipo "Laptop"'):
        sd.criar_ativo(it, 'In Store')


def test_diagnostico_mostra_obrigatorios_e_produto(app, sim):
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok and 'Obrigatórios segundo /api/v3/asset_computers/_metainfo: name, product' in texto
    assert 'Produto para o tipo "Laptop": Latitude 5450' in texto


def test_modulos_paginados_vem_todos(app, sim):
    """Sem row_count o SDP devolve só os 10 primeiros tipos."""
    s, _p = sim
    s.modulos = s.modulos + [{'id': str(10 + i), 'display_name': f'Tipo {i}',
                              'api_name': f'asset_t{i}', 'api_plural_name': f'asset_t{i}s'}
                             for i in range(150)]
    assert len(sd.listar_modulos(recarregar=True)) == 152


def test_metainfo_tenta_as_variantes_do_nome(app, sim):
    """O nome do recurso muda entre build; desistir na primeira foi o que escondeu o motivo."""
    s, _p = sim
    vistos = []
    original = s.__call__

    class Variante:
        def __call__(self, metodo, url, headers, corpo):
            cam = urllib.parse.urlparse(url).path
            if cam.endswith('/_metainfo'):
                vistos.append(cam)
                return 404, json.dumps({'response_status': {'status': 'failed',
                                                            'messages': [{'message': 'URL not found'}]}})
            if cam.endswith('/meta_info'):
                vistos.append(cam)
                return 200, json.dumps({'metainfo': {'fields': [{'name': 'site', 'mandatory': True}]},
                                        'response_status': {'status': 'success'}})
            return original(metodo, url, headers, corpo)

    sd.transporte = Variante()
    try:
        assert sd.obrigatorios('asset_computers') == ['site']
    finally:
        sd.transporte = s
    assert vistos == ['/api/v3/asset_computers/_metainfo', '/api/v3/asset_computers/meta_info']


def test_produtos_paginados_vem_todos(app, sim):
    s, _p = sim
    s.produtos = [{'id': str(i), 'name': f'P{i}', 'product_type': {'name': 'Laptop'}} for i in range(250)]
    assert len(sd.listar_produtos()) == 250


def test_diagnostico_lista_os_produtos_que_existem(app, sim):
    s, _p = sim
    s.produtos = [{'id': '9', 'name': 'Impressora X', 'product_type': {'name': 'Printer'}}]
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert not ok and 'nenhum do tipo "Laptop"' in texto
    assert 'Produtos cadastrados no Service Desk (1)' in texto and 'Impressora X  [Printer]' in texto


def test_diagnostico_acha_o_campo_recusado_e_guarda(app, sim):
    """O SDP diz só "Invalid Input": quem descobre qual campo é o diagnóstico, não o Gabriel."""
    s, _p = sim
    s.recusa_campo = 'asset_tag'
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert not ok
    assert 'NÃO  asset_tag' in texto and 'OK   serial_number' in texto and 'OK   state' in texto
    assert sd.conf('sd_criar_fora') == 'asset_tag'
    assert not s.ativos                        # nenhuma sonda ficou para trás
    s.recusa_campo = ''
    ok2, linhas2 = sd.diagnostico_criacao()    # na segunda passada já nasce sem o campo
    assert ok2 and 'apagado' in '\n'.join(linhas2)


def test_criar_ativo_respeita_os_campos_descartados(app, sim):
    from types import SimpleNamespace
    s, _p = sim
    sd.salvar_conf({'sd_criar_fora': 'asset_tag;state'})
    it = SimpleNamespace(hostname='NB-FORA', tag='T9', plaqueta='PL9', categoria='Notebook',
                         site='', fornecedor='', garantia='', modelo='Latitude 5450')
    sd.criar_ativo(it, 'In Store')
    a = s.ativos['NB-FORA']
    assert 'asset_tag' not in a and 'state' not in a and a['serial_number'] == 'T9'


def test_nem_o_minimo_passa_aponta_o_sdp_nao_o_campo(app, sim):
    s, _p = sim
    s.recusa_post = 'No permission to add asset'
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert not ok and 'Nem o mínimo' in texto and 'permissão da chave' in texto


def test_diagnostico_acha_o_campo_com_outro_nome(app, sim):
    """Recusa pode ser "este build não tem esse campo", não "valor inválido"."""
    s, _p = sim
    s.recusa_campo = 'serial_number'
    s.campos_metainfo = ['name', 'asset_tag', 'serial_no', 'state']
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert not ok and 'serial_number — neste build chama-se "serial_no"' in texto
    assert sd.conf('sd_apelidos') == 'serial_number=serial_no'
    assert 'serial_number' not in (sd.conf('sd_criar_fora') or '')


def test_criar_ativo_usa_o_apelido(app, sim):
    from types import SimpleNamespace
    s, _p = sim
    s.recusa_campo = 'serial_number'
    sd.salvar_conf({'sd_apelidos': 'serial_number=serial_no'})
    it = SimpleNamespace(hostname='NB-APL', tag='T7', plaqueta='', categoria='Notebook', site='',
                         fornecedor='', garantia='', modelo='Latitude 5450')
    sd.criar_ativo(it, 'In Store')
    a = s.ativos['NB-APL']
    assert a['serial_no'] == 'T7' and 'serial_number' not in a


def test_campo_descartado_nao_vira_campo_perdido_no_relatorio(app, sim):
    """Comparar com o que SERIA mandado fazia campo descartado parecer campo que o SD apagou."""
    s, _p = sim
    sd.salvar_conf({'sd_criar_fora': 'product_type'})
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok and 'product_type: não mandei (descartado antes)' in texto


def test_diagnostico_tenta_recuperar_o_que_foi_descartado(app, sim):
    """Descarte não é sentença: a cada rodada ele testa de novo, inclusive com outro nome."""
    s, _p = sim
    s.recusa_campo = 'serial_number'
    s.campos_metainfo = ['name', 'product', 'asset_tag', 'serial_no', 'state']
    sd.salvar_conf({'sd_criar_fora': 'serial_number'})
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok and 'neste build chama-se "serial_no"' in texto
    assert sd.conf('sd_apelidos') == 'serial_number=serial_no'
    assert not (sd.conf('sd_criar_fora') or '')          # saiu da lista de descartados


def test_campo_volta_quando_o_sd_passa_a_aceitar(app, sim):
    s, _p = sim
    sd.salvar_conf({'sd_criar_fora': 'asset_tag'})
    ok, linhas = sd.diagnostico_criacao()
    assert ok and 'asset_tag voltou a ser aceito' in '\n'.join(linhas)
    assert not (sd.conf('sd_criar_fora') or '')


def test_apelido_so_vale_se_o_valor_voltar_gravado(app, sim):
    """Campo que o SDP aceita e ignora passava como apelido: foi assim que product_id virou
    'tipo de produto'. Agora o valor tem que voltar naquele campo."""
    s, _p = sim
    s.recusa_campo = 'serial_number'
    s.ignora_campo = 'org_serial_number'       # aceita a chamada e descarta o valor
    s.campos_metainfo = ['name', 'product', 'asset_tag', 'org_serial_number', 'state']
    sd.salvar_conf({'sd_criar_fora': 'serial_number'})
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok and 'chama-se "org_serial_number"' not in texto     # não virou apelido
    assert 'serial_number: segue recusado' in texto
    assert sd.conf('sd_criar_fora') == 'serial_number'


def test_campo_aceito_mas_nao_guardado_nao_conta_como_aceito(app, sim):
    s, _p = sim
    s.ignora_campo = 'asset_tag'
    sd.salvar_conf({'sd_criar_fora': 'asset_tag'})
    ok, linhas = sd.diagnostico_criacao()
    assert 'asset_tag voltou a ser aceito' not in '\n'.join(linhas)
    assert sd.conf('sd_criar_fora') == 'asset_tag'


def test_apelido_falso_de_rodada_anterior_e_desfeito(app, sim):
    """product_type=product_id passou quando a prova era só "a chamada não falhou". Agora cai."""
    s, _p = sim
    s.recusa_campo = 'product_type'
    s.ignora_campo = 'product_id'
    s.campos_metainfo = ['name', 'product', 'product_id', 'asset_tag', 'state']
    sd.salvar_conf({'sd_apelidos': 'product_type=product_id'})
    ok, linhas = sd.diagnostico_criacao()
    assert ok and 'product_type: ' in '\n'.join(linhas)
    assert 'product_type' not in (sd.conf('sd_apelidos') or '')
    assert sd.conf('sd_criar_fora') == 'product_type'


def test_apelido_nunca_sobrescreve_campo_ja_em_uso(app, sim):
    """'product' já carrega o produto: usá-lo como apelido de product_type grava lixo nele."""
    s, _p = sim
    s.recusa_campo = 'product_type'
    s.campos_metainfo = ['name', 'product', 'asset_tag', 'state']
    sd.salvar_conf({'sd_criar_fora': 'product_type'})
    ok, linhas = sd.diagnostico_criacao()
    assert ok and 'chama-se "product"' not in '\n'.join(linhas)
    assert sd.conf('sd_criar_fora') == 'product_type'


def test_entre_candidatos_vence_o_campo_que_o_agente_usa(app, sim):
    """cpu_serial_number e service_tag gravam os dois. Não é empate: a tag precisa estar onde o
    agente a escreve, senão ele não reconhece o registro e cria outro."""
    s, _p = sim
    s.recusa_campo = 'serial_number'
    s.campos_metainfo = ['name', 'product', 'asset_tag', 'cpu_serial_number', 'service_tag',
                         'org_serial_number', 'state']
    sd.salvar_conf({'sd_criar_fora': 'serial_number'})
    ok, linhas = sd.diagnostico_criacao()
    assert ok and 'chama-se "service_tag"' in '\n'.join(linhas)
    assert sd.conf('sd_apelidos') == 'serial_number=service_tag'


def test_ambiguidade_sem_razao_para_preferir_continua_sendo_escolha_do_gabriel(app, sim):
    """Quando nenhum dos candidatos é um campo conhecido, não há o que preferir: pergunta."""
    s, _p = sim
    s.recusa_campo = 'serial_number'
    s.campos_metainfo = ['name', 'product', 'asset_tag', 'cpu_serial_number',
                         'chassis_serial_number', 'state']
    sd.salvar_conf({'sd_criar_fora': 'serial_number'})
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok and 'mais de um campo guarda o valor' in texto
    assert not (sd.conf('sd_apelidos') or '')
    assert sd.conf('sd_criar_fora') == 'serial_number'


def test_escolha_manual_do_nome_de_campo_e_respeitada(app, sim):
    """Decidida a ambiguidade na tela, a criação passa a usar o nome escolhido."""
    from types import SimpleNamespace
    s, _p = sim
    s.recusa_campo = 'serial_number'
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    adm.post('/admin/servicedesk', data={'acao': 'salvar', 'sd_ativos': 'Sim',
                                         'sd_apelidos': 'serial_number=org_serial_number',
                                         'sd_estados': '', 'sd_tipos': ''})
    it = SimpleNamespace(hostname='NB-ESC', tag='TAG9', plaqueta='', categoria='Notebook',
                         site='', fornecedor='', garantia='', modelo='Latitude 5450')
    sd.criar_ativo(it, 'In Store')
    assert s.ativos['NB-ESC']['org_serial_number'] == 'TAG9'


def test_relatorio_confere_o_campo_pelo_nome_apelidado(app, sim):
    """Com apelido ativo o campo É mandado, com outro nome. Conferir pelo nome antigo faz o
    relatório acusar de perdido justamente o que o apelido resolveu."""
    s, _p = sim
    s.recusa_campo = 'serial_number'
    s.campos_metainfo = ['name', 'product', 'asset_tag', 'org_serial_number', 'state']
    sd.salvar_conf({'sd_apelidos': 'serial_number=org_serial_number'})
    ok, linhas = sd.diagnostico_criacao()
    texto = '\n'.join(linhas)
    assert ok
    assert 'OK   serial_number (como "org_serial_number"): mandei' in texto
    assert 'serial_number: não mandei' not in texto


def test_tipo_de_produto_escolhe_o_endereco_e_nao_vai_no_corpo(app, sim):
    """Ele cumpriu o papel ao decidir /api/v3/asset_computers; mandá-lo junto é redundante, o SDP
    recusa, e ele voltava como "campo recusado" no diagnóstico a cada rodada."""
    from types import SimpleNamespace
    s, _p = sim
    it = SimpleNamespace(hostname='NB-TIPO', tag='', plaqueta='', categoria='Notebook', site='',
                         fornecedor='', garantia='', modelo='Latitude 5450')
    sd.criar_ativo(it, 'In Store')
    assert 'product_type' not in s.ativos['NB-TIPO']
    assert sd.corpo_do_item(it)['product_type'] == {'name': 'Laptop'}   # segue servindo de bússola


# ------------------------------------------------------------------ inspecionar um ativo

def test_inspecionar_mostra_os_campos_preenchidos_pela_ficha_do_modulo(app, sim):
    """A listagem geral devolve menos campos que a ficha do módulo; ler por ela esconderia
    justamente o campo que se está procurando."""
    s, _p = sim
    s.ativos['NB-AGENTE'] = {'id': '700', 'name': 'NB-AGENTE', 'product_type': {'name': 'Laptop'},
                             'org_serial_number': 'TAGREAL1', 'serial_number': '',
                             'state': {'name': 'In Use'}, 'asset_tag': None, 'contracts': []}
    s.ativos_por_id['700'] = s.ativos['NB-AGENTE']
    achados, err = sd.inspecionar_ativo('nb-agente')
    assert not err and len(achados) == 1
    campos = dict(achados[0]['campos'])
    assert campos['org_serial_number'] == 'TAGREAL1' and campos['state'] == 'In Use'
    assert 'serial_number' not in campos and 'asset_tag' not in campos   # vazios ficam de fora
    assert achados[0]['onde'].endswith('/asset_computers/700')


def test_inspecionar_avisa_quando_o_ativo_nao_existe(app, sim):
    achados, err = sd.inspecionar_ativo('NAO-EXISTE')
    assert not achados and 'não tem nenhum ativo' in err


def test_inspecionar_sem_hostname_nao_chama_o_sd(app, sim):
    achados, err = sd.inspecionar_ativo('   ')
    assert not achados and 'Diga o hostname' in err


def test_inspecionar_pela_tela_de_administracao(app, sim):
    s, _p = sim
    s.ativos['NB-TELA'] = {'id': '701', 'name': 'NB-TELA', 'product_type': {'name': 'Laptop'},
                           'org_serial_number': 'TAG-DA-TELA'}
    s.ativos_por_id['701'] = s.ativos['NB-TELA']
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    r = adm.post('/admin/servicedesk', data={'acao': 'inspecionar', 'hostname': 'NB-TELA'},
                 follow_redirects=True)
    texto = r.get_data(as_text=True)
    assert 'org_serial_number: TAG-DA-TELA' in texto


# ------------------------------------------------------------------ a tela não pode dar 500

def test_recusa_com_messages_em_formato_estranho_nao_quebra(app, sim):
    """O formato da recusa varia entre builds. Ler o erro errado virava 500 e escondia justamente
    o que o Service Desk tentou dizer."""
    s, _p = sim
    for brutos in ([{'message': 'Sem permissão'}], ['Sem permissão'], {'message': 'Sem permissão'},
                   None, 'Sem permissão'):
        class Esquisito:
            def __call__(self, metodo, url, headers, corpo):
                return 400, json.dumps({'response_status': {'status': 'failed', 'messages': brutos}})
        sd.transporte = Esquisito()
        try:
            with pytest.raises(sd.ErroSD) as e:
                sd.testar()
            assert 'HTTP 400' in str(e.value)
        finally:
            sd.transporte = s


def test_response_status_em_formato_estranho_nao_quebra(app, sim):
    s, _p = sim

    class Esquisito:
        def __call__(self, metodo, url, headers, corpo):
            return 400, json.dumps({'response_status': 'failed'})
    sd.transporte = Esquisito()
    try:
        with pytest.raises(sd.ErroSD):
            sd.testar()
    finally:
        sd.transporte = s


def test_imprevisto_na_tela_vira_recado_e_nao_erro_500(app, sim):
    """Tela de configuração que responde Internal Server Error deixa o Gabriel sem saída."""
    s, _p = sim

    class Explode:
        def __call__(self, metodo, url, headers, corpo):
            raise RuntimeError('algo que eu não previ')
    sd.transporte = Explode()
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    try:
        r = adm.post('/admin/servicedesk', data={'acao': 'testar'}, follow_redirects=True)
    finally:
        sd.transporte = s
    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'falhou' in texto and 'algo que eu não previ' in texto


def test_testar_salva_o_que_esta_na_tela_antes(app, sim):
    """O botão vive dentro da ficha: testar o que está salvo enquanto a tela mostra outra coisa
    produzia só 'endereço vazio' — foi o primeiro erro no servidor da MB."""
    s, _p = sim
    sd.salvar_conf({'sd_url': '', 'sd_chave': ''})
    adm = app.test_client()
    adm.post('/login', data={'email': 'admin@teste', 'senha': 'senha-forte-1'})
    r = adm.post('/admin/servicedesk', data={'acao': 'testar', 'sd_url': 'http://sd.novo:8080/',
                                             'sd_chave': 'CHAVE-TESTE', 'sd_ssl': 'Verificar',
                                             'sd_ativo': 'Sim'}, follow_redirects=True)
    assert sd.conf('sd_url') == 'http://sd.novo:8080'      # salvou, sem a barra do fim
    assert 'Conexão OK' in r.get_data(as_text=True)


def test_sem_endereco_a_mensagem_diz_o_que_falta(app, sim):
    """Antes vazava um ValueError sobre 'unknown url type', que não ajuda ninguém."""
    sd.salvar_conf({'sd_url': '', 'sd_chave': 'K'})
    with pytest.raises(sd.ErroSD, match='Falta o endereço'):
        sd.testar()
    sd.salvar_conf({'sd_url': 'http://x:8080', 'sd_chave': ''})
    with pytest.raises(sd.ErroSD, match='Falta a chave'):
        sd.testar()


def test_inspecionar_usa_o_campo_module_do_proprio_ativo(app, sim):
    """A listagem geral costuma vir sem product_type, mas vem com module — e foi assim que o
    Inspecionar caiu na listagem reduzida na primeira vez, no servidor da MB."""
    s, _p = sim
    s.ativos['NB-MOD'] = {'id': '710', 'name': 'NB-MOD', 'module': 'asset_computer',
                          'org_serial_number': 'TAG-COMPLETA', 'state': {'name': 'In Use'}}
    s.ativos_por_id['710'] = s.ativos['NB-MOD']
    achados, err = sd.inspecionar_ativo('NB-MOD')
    assert not err
    assert achados[0]['onde'].endswith('/asset_computers/710')          # ficha do módulo, não listagem
    assert dict(achados[0]['campos'])['org_serial_number'] == 'TAG-COMPLETA'


def test_listar_ativos_pede_os_campos_e_cai_de_pe_se_o_build_recusar(app, sim):
    """Sem fields_required a listagem vem sem service tag, e a conferência casa só por hostname
    sem perceber que está cega. Mas nome inválido derruba a chamada: tem que ter plano B."""
    s, _p = sim
    pedidos = []
    original = s

    class SóSemCampos:
        def __call__(self, metodo, url, headers, corpo):
            pedidos.append('fields_required' in url)
            if 'fields_required' in url:
                return 400, json.dumps({'response_status': {'status': 'failed', 'messages': [
                    {'message': 'Invalid field: org_serial_number'}]}})
            return original(metodo, url, headers, corpo)

    sd.transporte = SóSemCampos()
    try:
        lista, mais = sd.listar_ativos(1, 10)
    finally:
        sd.transporte = s
    assert pedidos == [True, False]        # tentou com campos, repetiu sem
    assert isinstance(lista, list) and mais in (True, False)


def test_inspecionar_diz_o_tipo_pelo_modulo_quando_falta_product_type(app, sim):
    """Ativo escaneado pelo agente vem sem product_type; mostrar "tipo ?" é esconder o que se sabe."""
    s, _p = sim
    s.ativos['NB-SEMTIPO'] = {'id': '720', 'name': 'NB-SEMTIPO', 'module': 'asset_computer',
                              'service_tag': 'T1'}
    s.ativos_por_id['720'] = s.ativos['NB-SEMTIPO']
    achados, err = sd.inspecionar_ativo('NB-SEMTIPO')
    assert not err and achados[0]['tipo'] == 'Laptop'
