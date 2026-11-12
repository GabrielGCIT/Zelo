"""Importar pessoas do Service Desk: casar com o cadastro do Zelo sem atropelar o que já existe."""
import pytest

from app import db
from app import servicedesk as sd
from app.importar_sd import _chave, aplicar, baixar, conferir
from app.models import Pessoa
from tests.test_servicedesk import SimuladorSD


@pytest.fixture()
def sd_com_usuarios(app):
    """Service Desk ligado, com uma base de usuários montada a partir do cadastro real do Zelo."""
    s = SimuladorSD({})
    sd.transporte = s
    sd.salvar_conf({'sd_url': 'http://sd.teste:8080', 'sd_chave': 'CHAVE-TESTE', 'sd_ativo': 'Sim'})
    yield s
    sd.transporte = None


def _u(nome, email='', login='', ativo=True):
    return {'id': str(abs(hash(nome)) % 9999), 'name': nome, 'email_id': email, 'login_name': login,
            'is_active': ativo}


def _sem_email():
    return Pessoa.query.filter(Pessoa.situacao == 'Ativo',
                               (Pessoa.email.is_(None)) | (Pessoa.email == '')).order_by(Pessoa.id).first()


# ------------------------------------------------------------------ comparação de nomes
def test_chave_de_nome():
    assert _chave('José  da Silva-Júnior') == 'JOSE DA SILVA JUNIOR'
    assert _chave('ANA MARIA') == _chave('Ana  María')
    assert _chave('') == '' and _chave(None) == ''


# ------------------------------------------------------------------ baixar
def test_baixar_pagina_a_pagina(app, sd_com_usuarios):
    s = sd_com_usuarios
    s.usuarios = [_u(f'PESSOA NUMERO {i}', f'p{i}@mb.com') for i in range(250)]
    lista, truncou, erro = baixar()
    assert not erro and not truncou and len(lista) == 250        # 3 páginas de 100
    lista, truncou, _e = baixar(limite_paginas=1)
    assert len(lista) == 100 and truncou                          # parou no teto e avisou


def test_baixar_sem_integracao(app):
    sd.salvar_conf({'sd_ativo': 'Não'})
    lista, _t, erro = baixar()
    assert lista == [] and 'desligada' in erro
    sd.salvar_conf({'sd_ativo': 'Sim'})


def test_baixar_com_o_sd_fora(app, sd_com_usuarios):
    sd_com_usuarios.fora = True
    lista, _t, erro = baixar()
    assert lista == [] and 'Sem conexão' in erro


# ------------------------------------------------------------------ casar
def test_completa_o_email_de_quem_ja_existe(app, sd_com_usuarios):
    p = _sem_email()
    linhas, resumo = conferir([_u(p.nome, 'achado@mb.com', 'dominio\\achado')])
    l = linhas[0]
    assert l['caso'] == 'completa' and l['pessoa'] == p.id and l['pessoa_email'] == ''
    assert resumo['completa'] == 1 and resumo['sem_email_no_zelo'] >= 1


def test_quem_ja_tem_o_mesmo_email_so_confere(app, sd_com_usuarios):
    p = _sem_email()
    p.email = 'igual@mb.com'
    db.session.commit()
    linhas, _r = conferir([_u(p.nome, 'IGUAL@mb.com')])            # o e-mail não diferencia maiúsculas
    assert linhas[0]['caso'] == 'confere'


def test_email_diferente_vira_conflito_e_nao_sobrescreve(app, sd_com_usuarios):
    p = _sem_email()
    p.email = 'antigo@mb.com'
    db.session.commit()
    linhas, _r = conferir([_u(p.nome, 'novo@mb.com')])
    assert linhas[0]['caso'] == 'conflito' and linhas[0]['pessoa_email'] == 'antigo@mb.com'
    db.session.refresh(p)
    assert p.email == 'antigo@mb.com'                              # conferir não escreve nada


def test_nome_repetido_nao_vira_palpite(app, sd_com_usuarios):
    nome = 'HOMONIMO DE TESTE'
    for i in (1, 2):
        db.session.add(Pessoa(id=f'HOM{i}', nome=nome, tipo='CLT', situacao='Ativo', cc=f'CC{i}'))
    db.session.commit()
    linhas, _r = conferir([_u(nome, 'qualquer@mb.com')])
    l = linhas[0]
    assert l['caso'] == 'ambiguo' and not l['pessoa']
    assert {c['id'] for c in l['candidatos']} == {'HOM1', 'HOM2'}  # mostra as duas e deixa escolher


def test_quem_nao_esta_no_zelo_fica_como_novo(app, sd_com_usuarios):
    linhas, resumo = conferir([_u('ALGUEM QUE NAO EXISTE NO ZELO', 'x@mb.com', 'x')])
    assert linhas[0]['caso'] == 'novo' and not linhas[0]['pessoa']
    assert resumo['novo'] == 1


def test_casa_pelo_email_mesmo_com_o_nome_diferente(app, sd_com_usuarios):
    p = _sem_email()
    p.email = 'mesmo@mb.com'
    db.session.commit()
    linhas, _r = conferir([_u('NOME ESCRITO DE OUTRO JEITO', 'mesmo@mb.com')])
    assert linhas[0]['caso'] == 'confere' and linhas[0]['pessoa'] == p.id


def test_usuario_repetido_entre_paginas_entra_uma_vez(app, sd_com_usuarios):
    p = _sem_email()
    linhas, _r = conferir([_u(p.nome, 'a@mb.com'), _u(p.nome, 'a@mb.com'), _u('', 'vazio@mb.com')])
    assert len(linhas) == 1                                        # sem nome não entra, repetido também não


# ------------------------------------------------------------------ aplicar
def test_aplicar_preenche_email_e_login(app, sd_com_usuarios):
    p = _sem_email()
    p.user = None
    db.session.commit()
    n, msg, det = aplicar([{'pessoa': p.id, 'email': 'Novo@MB.com', 'login': 'mb\\novo', 'nome': p.nome}], 'Gabriel')
    assert n == 1 and 'atualizada' in msg
    db.session.refresh(p)
    assert p.email == 'novo@mb.com' and p.user == 'mb\\novo'       # e-mail entra em minúsculas
    assert 'e-mail (vazio) → novo@mb.com' in det[0]

    n, _m, det = aplicar([{'pessoa': p.id, 'email': 'novo@mb.com', 'nome': p.nome}], 'Gabriel')
    assert n == 0 and 'nada a mudar' in det[0]                     # repetir não faz nada


def test_login_ja_preenchido_nao_e_sobrescrito(app, sd_com_usuarios):
    """O login do Zelo veio da planilha e pode ser o certo: importação não decide isso sozinha."""
    p = _sem_email()
    p.user = 'RH\\dusilva'
    db.session.commit()
    n, _m, det = aplicar([{'pessoa': p.id, 'email': 'x@mb.com', 'login': 'MB\\outro.login', 'nome': p.nome}], 'G')
    assert n == 1
    db.session.refresh(p)
    assert p.user == 'RH\\dusilva' and p.email == 'x@mb.com'
    assert 'usuário' not in det[0]


def test_aplicar_troca_email_quando_voce_manda(app, sd_com_usuarios):
    p = _sem_email()
    p.email = 'velho@mb.com'
    db.session.commit()
    n, _m, _d = aplicar([{'pessoa': p.id, 'email': 'certo@mb.com', 'nome': p.nome}], 'Gabriel')
    assert n == 1
    db.session.refresh(p)
    assert p.email == 'certo@mb.com'                               # só porque foi marcado na tela


def test_aplicar_cadastra_quem_falta(app, sd_com_usuarios):
    n, _m, det = aplicar([{'criar': True, 'nome': 'MARIA DA PONTE NOVA', 'email': 'ponte@mb.com', 'login': 'mpn'}], 'G')
    assert n == 1
    p = Pessoa.query.filter_by(nome='MARIA DA PONTE NOVA').one()
    assert p.id == 'SD-MARIADAPON' and p.email == 'ponte@mb.com' and p.tipo == 'A confirmar'
    assert 'Service Desk' in (p.obs or '')
    # com matrícula informada por você, vale a sua
    aplicar([{'criar': True, 'nome': 'JOAO DA MATRICULA', 'email': 'j@mb.com', 'pessoa': '99881'}], 'G')
    assert db.session.get(Pessoa, '99881').nome == 'JOAO DA MATRICULA'


def test_aplicar_recusa_o_que_nao_da(app, sd_com_usuarios):
    p = _sem_email()
    n, msg, det = aplicar([{'pessoa': 'NAO-EXISTE', 'email': 'a@b.com', 'nome': 'Fulano'},
                           {'criar': True, 'nome': '', 'email': 'b@b.com'},
                           {'criar': True, 'nome': p.nome, 'pessoa': p.id}], 'G')
    assert n == 0 and 'sem efeito' in msg and len(det) == 3
    assert any('já existe' in d for d in det)


# ------------------------------------------------------------------ tela
def test_tela_de_importacao(app, cli, sd_com_usuarios):
    p = _sem_email()
    sd_com_usuarios.usuarios = [_u(p.nome, 'dosd@mb.com', 'mb\\dosd'),
                                _u('GENTE QUE NAO ESTA NO ZELO', 'fora@mb.com')]
    assert 'Buscar no Service Desk' in cli.get('/pessoas/importar-sd').data.decode()
    assert '/pessoas/importar-sd' in cli.get('/pessoas').data.decode()      # botão na tela de Pessoas

    h = cli.post('/pessoas/importar-sd', data={'acao': 'buscar'}).data.decode()
    assert 'Completa o e-mail' in h and p.nome in h and 'dosd@mb.com' in h
    assert 'Não estão no Zelo' in h and 'GENTE QUE NAO ESTA NO ZELO' in h

    import json
    r = cli.post('/pessoas/importar-sd', follow_redirects=True, data={
        'acao': 'aplicar',
        'escolhas': json.dumps([{'pessoa': p.id, 'email': 'dosd@mb.com', 'login': 'mb\\dosd', 'nome': p.nome}])})
    assert r.status_code == 200 and '1 pessoa(s) atualizada(s)' in r.data.decode()
    db.session.refresh(p)
    assert p.email == 'dosd@mb.com'


def test_tela_avisa_integracao_desligada(app, cli):
    sd.salvar_conf({'sd_ativo': 'Não'})
    h = cli.get('/pessoas/importar-sd').data.decode()
    assert 'desligada ou sem chave' in h
    sd.salvar_conf({'sd_ativo': 'Sim'})
