"""Agente do Zelo: o inventário que as próprias máquinas mandam, e o que o Zelo faz com ele."""
import json

import pytest

from app import db
from app.agente import como_ativos, limpar, receber, tag_valida
from app.models import Config, Item, MaquinaVista

SENHA = 'senha-do-agente-teste'


@pytest.fixture()
def ligado(app):
    db.session.merge(Config(chave='agente_token', valor=SENHA))
    db.session.commit()
    return SENHA


def _manda(app, corpo, senha=SENHA):
    c = app.test_client()          # sem login: quem chama é a máquina
    return c.post('/api/agente/inventario', data=json.dumps(corpo) if not isinstance(corpo, (str, bytes)) else corpo,
                  headers={'X-Zelo-Agente': senha, 'Content-Type': 'application/json'})


def _inv(**kw):
    d = {'hostname': 'LMBAGENTE01', 'tag': 'ABC1234', 'fabricante': 'Dell Inc.', 'modelo': 'Latitude 5450',
         'chassi': 'Notebook', 'so': 'Microsoft Windows 11 Pro 10.0.22631', 'usuario': 'REYES\\fulano',
         'ip': '10.1.2.3', 'mac': 'AA:BB:CC:DD:EE:FF', 'versao': '1'}
    d.update(kw)
    return d


# ------------------------------------------------------------------ porta de entrada
def test_desligado_recusa_tudo(app):
    """Sem senha configurada o Zelo não aceita inventário: ninguém liga o agente sem querer."""
    r = _manda(app, _inv(), senha='qualquer')
    assert r.status_code == 503 and MaquinaVista.query.count() == 0


def test_senha_errada_e_recusada(app, ligado):
    r = _manda(app, _inv(), senha='errada')
    assert r.status_code == 403 and MaquinaVista.query.count() == 0


def test_recebe_e_grava(app, ligado):
    r = _manda(app, _inv())
    assert r.status_code == 200 and r.json['ok']
    m = MaquinaVista.query.one()
    assert (m.hostname, m.tag, m.modelo, m.usuario) == ('LMBAGENTE01', 'ABC1234', 'Latitude 5450', 'REYES\\fulano')
    assert m.visto_em and m.primeira_vez and m.origem


def test_corpo_que_nao_e_inventario(app, ligado):
    assert _manda(app, 'isto não é json').status_code == 400
    assert _manda(app, ['lista']).status_code == 400
    assert _manda(app, _inv(hostname='')).status_code == 400
    assert _manda(app, 'x' * 20000).status_code == 413
    assert MaquinaVista.query.count() == 0


def test_campo_desconhecido_e_tamanho_sao_contidos(app, ligado):
    """O script fica legível onde for distribuído: o endereço não pode confiar no que recebe."""
    _manda(app, _inv(modelo='M' * 500, situacao='Baixada', com_quem='Outra Pessoa', usuario={'x': 1}))
    m = MaquinaVista.query.one()
    assert len(m.modelo) == 100 and not m.usuario
    assert not hasattr(m, 'situacao') or m.situacao is None


def test_nao_mexe_no_cadastro_do_item(app, ligado):
    """O agente descreve a máquina; quem está com ela e a situação continuam sendo do Zelo."""
    it = Item.query.filter(Item.hostname.isnot(None), Item.hostname != '', Item.situacao == 'Em uso').first()
    antes = (it.situacao, it.com_quem, it.tag, it.modelo)
    _manda(app, _inv(hostname=it.hostname, tag='OUTRATAG99', modelo='Outro Modelo', usuario='X\\outro'))
    db.session.refresh(it)
    assert (it.situacao, it.com_quem, it.tag, it.modelo) == antes


# ------------------------------------------------------------------ uma linha por máquina
def test_mesma_maquina_atualiza_em_vez_de_duplicar(app, ligado):
    _manda(app, _inv(usuario='REYES\\primeiro'))
    _manda(app, _inv(usuario='REYES\\segundo'))
    m = MaquinaVista.query.one()
    assert m.usuario == 'REYES\\segundo'


def test_renomeada_continua_a_mesma_pela_service_tag(app, ligado):
    _manda(app, _inv(hostname='NOME-VELHO'))
    _manda(app, _inv(hostname='NOME-NOVO'))
    assert MaquinaVista.query.count() == 1 and MaquinaVista.query.one().hostname == 'NOME-NOVO'


def test_sem_tag_casa_pelo_hostname(app, ligado):
    _manda(app, _inv(tag='To be filled by O.E.M.'))
    _manda(app, _inv(tag=''))
    m = MaquinaVista.query.one()
    assert not m.tag


def test_envio_sem_ip_nao_apaga_o_que_se_sabia(app, ligado):
    _manda(app, _inv(ip='10.9.9.9'))
    _manda(app, _inv(ip=''))
    assert MaquinaVista.query.one().ip == '10.9.9.9'


def test_hostname_com_dominio_entra_curto(app, ligado):
    c, _e = limpar(_inv(hostname='lmbagente01.reyesholdings.com'))
    assert c['hostname'] == 'LMBAGENTE01'


def test_serial_de_placa_generica_nao_e_service_tag():
    """Aceitar 'Default string' como tag juntaria máquinas diferentes numa linha só."""
    for lixo in ('Default string', 'To be filled by O.E.M.', 'System Serial Number', '0', '00000000',
                 'VMware-56 4d 8e 1a', ''):
        assert tag_valida(lixo) == '', lixo
    assert tag_valida('ABC1234') == 'ABC1234'


# ------------------------------------------------------------------ conferência e cobertura
def _em_uso():
    from sqlalchemy import func
    repetidos = [h for h, n in db.session.query(Item.hostname, func.count('*')).group_by(Item.hostname).all()
                 if n > 1 and h]
    return (Item.query.filter(Item.hostname.isnot(None), Item.hostname != '', Item.categoria == 'Notebook',
                              Item.situacao == 'Em uso', ~Item.hostname.in_(repetidos)).order_by(Item.codigo).first())


def test_como_ativos_serve_a_conferencia(app, ligado):
    from app.conferir_sd import conferir
    it = _em_uso()
    it.tag = None
    db.session.commit()
    _manda(app, _inv(hostname=it.hostname, tag='TAGDABIOS1'))
    linhas, _r = conferir(como_ativos())
    l = next(x for x in linhas if x['item'] and x['item']['codigo'] == it.codigo)
    assert ('tag', 'TAGDABIOS1') in l['faltam']


def test_cobertura_com_o_agente_do_zelo(app, ligado):
    """Máquina que mandou inventário sai de 'nunca vista'; a que não mandou fica."""
    from app.conferir_sd import cobertura
    it = _em_uso()
    _manda(app, _inv(hostname=it.hostname, tag=it.tag or ''))
    c = cobertura(como_ativos(), ausente='o agente nunca a viu')
    assert c['veio_agente']
    nunca = {x['item']['codigo'] for x in c['sem_agente']}
    assert it.codigo not in nunca
    assert any(x['motivo'] == 'o agente nunca a viu' for x in c['sem_agente'])


def test_tela_vazia_explica_como_comecar(app, cli, ligado):
    h = cli.get('/itens/agente').data.decode()
    assert 'Nenhuma máquina mandou inventário' in h and 'Como instalar' in h


def test_tela_avisa_desligado(app, cli):
    assert 'O agente está desligado' in cli.get('/itens/agente').data.decode()


def test_tela_mostra_o_que_chegou_e_aplica_so_o_marcado(app, cli, ligado):
    it = _em_uso()
    it.tag = None
    db.session.commit()
    _manda(app, _inv(hostname=it.hostname, tag='TAGDABIOS2'))
    _manda(app, _inv(hostname='MAQUINA-DESCONHECIDA', tag='NINGUEM99'))
    h = cli.get('/itens/agente').data.decode()
    assert 'Cobertura do agente do Zelo' in h and 'MAQUINA-DESCONHECIDA' in h and 'TAGDABIOS2' in h
    assert '/itens/agente' in cli.get('/itens').data.decode()           # botão na tela de Itens
    r = cli.post('/itens/agente', follow_redirects=True, data={
        'acao': 'aplicar', 'escolhas': json.dumps([
            {'codigo': it.codigo, 'campos': {'tag': 'TAGDABIOS2'}},
            {'criar': True, 'sd': {'hostname': 'MAQUINA-DESCONHECIDA'}}])})   # criar é ignorado
    assert r.status_code == 200
    db.session.refresh(it)
    assert it.tag == 'TAGDABIOS2'
    assert not db.session.get(Item, 'NINGUEM99') and not Item.query.filter_by(hostname='MAQUINA-DESCONHECIDA').first()


def test_consulta_nao_aplica(app, ligado):
    c = app.test_client()
    c.post('/login', data={'email': 'cons@teste', 'senha': 'senha-forte-1'})
    assert c.get('/itens/agente').status_code == 403


# ------------------------------------------------------------------ como instalar e o pacote
@pytest.fixture()
def adm(app):
    from tests.conftest import entrar
    return entrar(app.test_client(), 'admin@teste')


def _zip(resp):
    import io
    import zipfile
    return zipfile.ZipFile(io.BytesIO(resp.data))


def test_aba_como_instalar(app, adm, ligado):
    h = adm.get('/itens/agente/instalar').data.decode()
    assert 'instalar-agente.bat' in h and 'Zelo - Agente' in h and 'já está ligado' in h
    assert 'Baixar zelo-agente.zip' in h
    # aberto pelo próprio servidor, o endereço sugerido não serve para as outras máquinas
    assert 'localhost' in h and 'troque pelo nome ou IP do servidor' in h
    assert '/itens/agente/instalar' in adm.get('/itens/agente').data.decode()


def test_pacote_vem_configurado(app, adm, ligado):
    r = adm.post('/itens/agente/pacote', data={'endereco': 'http://brdapp01:5001/'})
    assert r.status_code == 200 and r.mimetype == 'application/zip'
    z = _zip(r)
    nomes = set(z.namelist())
    assert {'zelo-agente/zelo-agente.ps1', 'zelo-agente/instalar-agente.ps1', 'zelo-agente/instalar-agente.bat',
            'zelo-agente/desinstalar-agente.bat', 'zelo-agente/agente.conf', 'zelo-agente/LEIAME.txt'} <= nomes
    conf = json.loads(z.read('zelo-agente/agente.conf'))
    assert conf == {'zelo': 'http://brdapp01:5001', 'senha': SENHA}


def test_ps1_do_pacote_tem_bom_e_crlf(app, adm, ligado):
    """Sem BOM o PowerShell 5.1 lê o script no código de página do sistema e todo acento vira lixo."""
    z = _zip(adm.post('/itens/agente/pacote', data={'endereco': 'http://brdapp01:5001'}))
    for nome in ('zelo-agente.ps1', 'instalar-agente.ps1', 'instalar-agente.bat'):
        b = z.read(f'zelo-agente/{nome}')
        assert b.count(b'\r\n') == b.count(b'\n'), nome
        assert b.startswith(b'\xef\xbb\xbf') == nome.endswith('.ps1'), nome


def test_pacote_recusa_endereco_ruim_e_agente_desligado(app, adm):
    r = adm.post('/itens/agente/pacote', data={'endereco': 'http://brdapp01:5001'}, follow_redirects=True)
    assert 'Defina a' in r.data.decode() and r.mimetype != 'application/zip'
    db.session.merge(Config(chave='agente_token', valor=SENHA))
    db.session.commit()
    for ruim in ('', 'brdapp01:5001', 'http://a b', 'javascript:alert(1)'):
        r = adm.post('/itens/agente/pacote', data={'endereco': ruim}, follow_redirects=True)
        assert r.mimetype != 'application/zip' and 'Endereço inválido' in r.data.decode(), ruim


def test_so_admin_baixa_o_pacote(app, cli, ligado):
    """O pacote leva a senha: Operador vê o passo a passo, mas não baixa."""
    h = cli.get('/itens/agente/instalar')
    assert h.status_code == 200 and 'Só o Administrador baixa' in h.data.decode()
    assert cli.post('/itens/agente/pacote', data={'endereco': 'http://x:5001'}).status_code == 403


def test_scripts_do_agente_compilam_no_powershell():
    """Erro de sintaxe num .ps1 só apareceria na máquina do usuário, em silêncio (o agente não mostra
    nada). O parser do próprio PowerShell pega antes."""
    import os
    import shutil
    import subprocess
    from app.agente import PASTA_SCRIPTS
    ps = shutil.which('powershell.exe') or shutil.which('pwsh')
    if not ps:
        pytest.skip('sem PowerShell nesta máquina')
    for nome in ('zelo-agente.ps1', 'instalar-agente.ps1'):
        caminho = os.path.join(PASTA_SCRIPTS, nome)
        cmd = ("$e=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e);"
               " $e | %% { $_.Message }; exit $e.Count" % caminho.replace("'", "''"))
        r = subprocess.run([ps, '-NoProfile', '-Command', cmd], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f'{nome}: {r.stdout}{r.stderr}'


def test_empacotador_leva_os_scripts_do_agente():
    import importlib.util
    import os
    from app.agente import PASTA_SCRIPTS
    raiz = os.path.dirname(os.path.dirname(PASTA_SCRIPTS))
    spec = importlib.util.spec_from_file_location('empacotar', os.path.join(raiz, 'scripts', 'empacotar.py'))
    emp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(emp)
    assert os.path.join('scripts', 'agente') in emp.PASTAS
