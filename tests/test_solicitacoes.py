"""Etapa G: solicitações do Zelo e o chamado no Service Desk como espelho."""
from datetime import date, timedelta

import pytest

from app import db
from app import servicedesk as sd
from app import solicitacoes as sol
from app.desligamento import devolver_tudo, o_que_tem, pendentes
from app.manutencao import registrar
from app.models import EnvioSD, Item, Manutencao, Solicitacao
from tests.conftest import entrar
from tests.test_servicedesk import sim  # noqa: F401  (fixture)

CONF = 'solicitante=ti@mb.com.br; categoria=Desktop Hardware; grupo=Hardware Problems'


def _ligar():
    sd.salvar_conf({'sd_abrir_chamado': 'Sim', 'sd_chamado_recolhimento': CONF,
                    'sd_chamado_manutencao': 'solicitante=ti@mb.com.br; prazo=2',
                    'sd_chamado_devolucao': 'solicitante=ti@mb.com.br'})


def _desligado():
    f = pendentes()
    if not f:
        pytest.skip('nenhum desligado com equipamento na planilha')
    return f[0]['p']


def _os_aberta():
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook').first()
    ok, msg = registrar({'acao': 'Abrir ocorrência', 'item': it.codigo, 'defeito': 'Tela piscando'}, 'Teste')
    assert ok, msg
    return Manutencao.query.filter_by(item=it.codigo).order_by(Manutencao.id.desc()).first()


def _pendente_devolucao():
    it = Item.query.filter(Item.situacao == 'Em uso', Item.matricula.isnot(None)).first()
    it.situacao = 'Pendente devolução'
    db.session.commit()
    return it


# ------------------------------------------------------------------ a solicitação vive sem o SD
def test_recolhimento_lista_tudo_que_a_pessoa_tem(app):
    p = _desligado()
    s, nova, erro = sol.criar('recolhimento', 'Teste', pessoa=p.id)
    assert nova and not erro
    t = o_que_tem(p.id)
    for it in t['itens']:
        assert it.codigo in s.descricao
    assert sol.itens_de(s) == [it.codigo for it in t['itens']]
    assert sol.situacao(s) == 'Aberta' and s.prazo == (date.today() + timedelta(days=5)).isoformat()


def test_pedir_de_novo_devolve_a_mesma(app):
    p = _desligado()
    s1, _n, _e = sol.criar('recolhimento', 'Teste', pessoa=p.id)
    s2, nova, _e = sol.criar('recolhimento', 'Outro', pessoa=p.id)
    assert s2.id == s1.id and not nova and Solicitacao.query.count() == 1


def test_resolvida_sai_do_zelo_e_nao_de_uma_marca(app):
    """Devolveu tudo → resolvida, sem ninguém marcar nada."""
    p = _desligado()
    s, _n, _e = sol.criar('recolhimento', 'Teste', pessoa=p.id)
    t = o_que_tem(p.id)
    devolver_tudo(p, {'itens': [i.codigo for i in t['itens']], 'linhas': {l.numero: 'Devolver' for l in t['linhas']},
                      'kit': [(str(m), c) for m, c, _q in t['kit']], 'acess': [str(a.id) for a in t['acess']]}, 'Teste')
    assert sol.situacao(s) == 'Resolvida'
    # e resolvida não bloqueia uma nova, se a pessoa voltar a ter algo um dia
    assert sol.em_aberto('recolhimento', pessoa=p.id) is None


def test_nao_cria_o_que_nao_faz_sentido(app):
    assert sol.criar('recolhimento', 'T', pessoa='NAO-EXISTE')[2] == 'Pessoa não encontrada'
    sem = Item.query.filter(Item.situacao == 'Em estoque').first()
    assert 'não está com devolução pendente' in sol.criar('devolucao', 'T', item=sem.codigo)[2]
    assert 'já fechada' in sol.criar('manutencao', 'T', os_id='999999')[2]
    assert 'desconhecido' in sol.criar('outra', 'T')[2]
    assert Solicitacao.query.count() == 0


def test_manutencao_resolve_quando_a_os_fecha(app):
    os_ = _os_aberta()
    s, _n, _e = sol.criar('manutencao', 'T', os_id=os_.id)
    assert sol.situacao(s) == 'Aberta' and 'Tela piscando' in s.descricao
    ok, msg = registrar({'acao': 'Fechar ocorrência', 'item': os_.item}, 'T')
    assert ok, msg
    assert sol.situacao(s) == 'Resolvida'


def test_atrasada_e_cancelada(app):
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    s.prazo = (date.today() - timedelta(days=1)).isoformat()
    db.session.commit()
    assert sol.situacao(s) == 'Atrasada' and sol.atrasadas() == 1
    assert not sol.cancelar(s, 'T', '')[0]                       # motivo é obrigatório
    assert sol.cancelar(s, 'T', 'pessoa devolveu em mãos')[0]
    assert sol.situacao(s) == 'Cancelada' and sol.atrasadas() == 0


# ------------------------------------------------------------------ o chamado como espelho
def test_abre_chamado_com_solicitante_categoria_e_ativos(app, sim):  # noqa: F811
    s_, _p = sim
    _ligar()
    p = _desligado()
    s, _n, _e = sol.criar('recolhimento', 'T', pessoa=p.id)
    assert sd.enfileirar_solicitacao(app, s) == 1
    e = EnvioSD.query.filter_by(tipo='abrir').one()
    assert e.status == 'Enviado', e.erro
    ch = s_.chamados[s.chamado]
    assert ch['subject'].startswith(f'[Zelo S-{s.id}/{sd.instancia()}]')
    assert ch['requester'] == {'email_id': 'ti@mb.com.br'}
    assert ch['category'] == {'name': 'Desktop Hardware'} and ch['group'] == {'name': 'Hardware Problems'}
    assert '<br>' in ch['description']                          # o SDP lê HTML


def test_resposta_perdida_nao_duplica_o_chamado(app, sim):  # noqa: F811
    """Criou no SD e a resposta não voltou (timeout): o reenvio acha pela marca e adota."""
    s_, _p = sim
    _ligar()
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    s_.perde_resposta = True
    sd.enfileirar_solicitacao(app, s)
    e = EnvioSD.query.filter_by(tipo='abrir').one()
    assert e.status == 'Erro' and len(s_.abertos) == 1
    sd.enviar(e)
    db.session.refresh(s)
    assert e.status == 'Enviado' and 'adotado' in e.erro
    assert len(s_.abertos) == 1 and s.chamado == s_.abertos[0]


def test_sem_solicitante_nao_abre_e_diz_por_que(app, sim):  # noqa: F811
    s_, _p = sim
    sd.salvar_conf({'sd_abrir_chamado': 'Sim', 'sd_chamado_devolucao': 'categoria=General'})
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    sd.enfileirar_solicitacao(app, s)
    e = EnvioSD.query.filter_by(tipo='abrir').one()
    assert e.status == 'Erro' and 'Falta o solicitante' in e.erro and not s_.abertos


def test_recolhimento_nunca_usa_a_pessoa_desligada_como_solicitante(app, sim):  # noqa: F811
    s_, _p = sim
    sd.salvar_conf({'sd_abrir_chamado': 'Sim', 'sd_chamado_recolhimento': 'solicitante=pessoa'})
    s, _n, _e = sol.criar('recolhimento', 'T', pessoa=_desligado().id)
    sd.enfileirar_solicitacao(app, s)
    e = EnvioSD.query.filter_by(tipo='abrir').one()
    assert e.status == 'Erro' and 'desligada' in e.erro and not s_.abertos


def test_desligado_no_zelo_nao_abre(app, sim):  # noqa: F811
    s_, _p = sim
    sd.salvar_conf({'sd_chamado_devolucao': 'solicitante=ti@mb.com.br'})   # sd_abrir_chamado = Não
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    sd.enfileirar_solicitacao(app, s)
    assert EnvioSD.query.filter_by(tipo='abrir').one().status == 'Erro' and not s_.abertos


def test_cancelada_nao_abre(app, sim):  # noqa: F811
    s_, _p = sim
    _ligar()
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    sol.cancelar(s, 'T', 'resolvido por telefone')
    sd.enfileirar_solicitacao(app, s)
    assert 'cancelada' in EnvioSD.query.filter_by(tipo='abrir').one().erro and not s_.abertos


def test_manutencao_grava_o_chamado_na_os(app, sim):  # noqa: F811
    s_, _p = sim
    _ligar()
    os_ = _os_aberta()
    s, _n, _e = sol.criar('manutencao', 'T', os_id=os_.id)
    assert s.prazo == (date.today() + timedelta(days=2)).isoformat()      # prazo do caso
    sd.enfileirar_solicitacao(app, s)
    db.session.refresh(os_)
    assert os_.chamado == s.chamado and s.chamado in s_.chamados


def test_resolvida_no_zelo_ganha_nota_no_chamado(app, sim):  # noqa: F811
    s_, _p = sim
    _ligar()
    os_ = _os_aberta()
    s, _n, _e = sol.criar('manutencao', 'T', os_id=os_.id)
    sd.enfileirar_solicitacao(app, s)
    c = entrar(app.test_client(), 'op@teste')
    c.post('/manutencao', data={'acao': 'Fechar ocorrência', 'item': os_.item})
    db.session.refresh(s)
    assert s.nota_resolvida and any(n == s.chamado and 'Resolvido no Zelo' in t for n, t in s_.notas)
    assert s_.chamados[s.chamado]['status'] == {'name': 'Open'}      # nota, não fecha
    assert sd.avisar_resolvidas(app) == 0                             # e não repete


def test_diagnostico_cria_confere_e_apaga(app, sim):  # noqa: F811
    s_, _p = sim
    _ligar()
    ok, linhas = sd.diagnostico_chamado()
    texto = '\n'.join(linhas)
    assert ok, texto
    assert 'Hardware Problems' in texto and 'categoria ok' in texto
    # um chamado de teste por caso configurado (os três estão), e nenhum fica para trás
    assert len(s_.apagados_chamados) == 3 and not any(k in s_.chamados for k in s_.apagados_chamados)


# ------------------------------------------------------------------ telas
def test_tela_do_desligamento_oferece_e_depois_mostra(app, sim):  # noqa: F811
    _ligar()
    p = _desligado()
    c = entrar(app.test_client(), 'op@teste')
    h = c.get(f'/desligamento/{p.id}').data.decode()
    assert 'Abrir chamado de recolhimento' in h
    r = c.post('/solicitacoes/nova', data={'tipo': 'recolhimento', 'pessoa': p.id, 'chamado': 'Sim',
                                           'volta': f'/desligamento/{p.id}'}, follow_redirects=True)
    h = r.data.decode()
    s = Solicitacao.query.one()
    assert f'S-{s.id}' in h and s.chamado and f'chamado <b>{s.chamado}</b>' in h
    assert 'Abrir chamado de recolhimento' not in h


def test_so_registrar_nao_abre_chamado(app, sim):  # noqa: F811
    s_, _p = sim
    _ligar()
    it = _pendente_devolucao()
    c = entrar(app.test_client(), 'op@teste')
    c.post('/solicitacoes/nova', data={'tipo': 'devolucao', 'item': it.codigo, 'chamado': 'Não'})
    assert Solicitacao.query.one().chamado is None and not s_.abertos
    assert 'Cobrar por chamado' not in c.get(f'/item/{it.codigo}').data.decode()


def test_lista_lembrete_e_menu(app):
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    s.prazo = '2000-01-01'
    db.session.commit()
    c = entrar(app.test_client(), 'op@teste')
    h = c.get('/solicitacoes').data.decode()
    assert f'S-{s.id}' in h and 'Atrasada' in h
    from app.lembretes import tudo
    assert any(x['chave'] == 'solicitacao_atrasada' and x['n'] == 1 for x in tudo()[0])
    assert '/solicitacoes' in c.get('/').data.decode()


def test_consulta_nao_cria_nem_cancela(app):
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    c = entrar(app.test_client(), 'cons@teste')
    assert c.post('/solicitacoes/nova', data={'tipo': 'devolucao', 'item': it.codigo}).status_code == 403
    assert c.post(f'/solicitacoes/{s.id}/cancelar', data={'motivo': 'x'}).status_code == 403
    assert c.get('/solicitacoes').status_code == 200


def test_volta_nao_redireciona_para_fora(app):
    """`volta` vem do formulário: aceitar qualquer URL seria um redirecionamento aberto."""
    it = _pendente_devolucao()
    c = entrar(app.test_client(), 'op@teste')
    for ruim in ('https://evil.example/x', '//evil.example/x', 'javascript:alert(1)', '/\\evil.example/x',
                 '/\tevil.example'):
        r = c.post('/solicitacoes/nova', data={'tipo': 'devolucao', 'item': it.codigo, 'volta': ruim})
        assert r.status_code == 302 and 'evil' not in r.headers['Location'] and 'javascript' not in r.headers['Location']


def test_diagnostico_aponta_nome_de_grupo_errado(app, sim):  # noqa: F811
    s_, _p = sim
    sd.salvar_conf({'sd_chamado_manutencao': 'solicitante=ti@mb.com.br; grupo=Grupo Que Nao Existe'})
    ok, linhas = sd.diagnostico_chamado()
    texto = '\n'.join(linhas)
    assert not ok and 'Invalid Input' in texto and 'confira o nome exato' in texto and not s_.abertos


# ------------------------------------------------------------------ achados da revisão de 20/11
def test_marca_de_outra_instalacao_nao_e_adotada(app, sim):  # noqa: F811
    """Um Zelo de teste contra o SD de produção e o banco da virada geram os dois uma S-1: o
    chamado do outro banco não pode ser adotado."""
    s_, _p = sim
    _ligar()
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    s_.chamados['900'] = {'subject': f'[Zelo S-{s.id}] chamado de outro banco', 'requester': {'name': 'x'}}
    s_.chamados['901'] = {'subject': f'[Zelo S-{s.id}/OUTRO] de outra instalação', 'requester': {'name': 'x'}}
    sd.enfileirar_solicitacao(app, s)
    db.session.refresh(s)
    assert s.chamado not in ('900', '901') and s.chamado in s_.abertos


def test_pedir_de_novo_depois_do_erro_tenta_outra_vez(app, sim):  # noqa: F811
    s_, _p = sim
    sd.salvar_conf({'sd_abrir_chamado': 'Sim', 'sd_chamado_devolucao': 'categoria=General'})   # sem solicitante
    it = _pendente_devolucao()
    s, _n, _e = sol.criar('devolucao', 'T', item=it.codigo)
    sd.enfileirar_solicitacao(app, s)
    assert EnvioSD.query.filter_by(tipo='abrir').one().status == 'Erro'
    _ligar()                                                # o admin corrige
    assert sd.enfileirar_solicitacao(app, s) == 1
    e = EnvioSD.query.filter_by(tipo='abrir').one()
    assert e.status == 'Enviado' and s.chamado and len(s_.abertos) == 1


def test_diagnostico_com_solicitante_pessoa(app, sim):  # noqa: F811
    s_, _p = sim
    s_.usuarios.append({'id': '77', 'name': 'Alguem Do SD', 'email_id': ''})
    sd.salvar_conf({'sd_chamado_devolucao': 'solicitante=pessoa; categoria=General'})
    ok, linhas = sd.diagnostico_chamado()
    assert ok, linhas
    assert any('testado com Alguem Do SD' in x for x in linhas)


def test_nota_de_resolucao_escapa_o_assunto_e_nao_repete(app, sim):  # noqa: F811
    s_, _p = sim
    _ligar()
    it = Item.query.filter(Item.situacao == 'Em estoque', Item.categoria == 'Notebook').first()
    registrar({'acao': 'Abrir ocorrência', 'item': it.codigo, 'defeito': 'Tela <b>quebrada</b> & sem imagem'}, 'T')
    os_ = Manutencao.query.filter_by(item=it.codigo).order_by(Manutencao.id.desc()).first()
    s, _n, _e = sol.criar('manutencao', 'T', os_id=os_.id)
    sd.enfileirar_solicitacao(app, s)
    registrar({'acao': 'Fechar ocorrência', 'item': it.codigo}, 'T')
    e1 = EnvioSD(tipo='resolvida', alvo=f'S-{s.id}', status='Pendente', tentativas=0)
    e2 = EnvioSD(tipo='resolvida', alvo=f'S-{s.id}', status='Pendente', tentativas=0)  # a corrida
    db.session.add_all([e1, e2])
    db.session.commit()
    sd.enviar(e1)
    sd.enviar(e2)
    notas = [t for n, t in s_.notas if n == s.chamado]
    assert len(notas) == 1 and '&lt;b&gt;' in notas[0] and '<b>' not in notas[0]


def test_reimportar_apaga_as_solicitacoes(app):
    """As OS recomeçam do 1 na reimportação: a solicitação antiga não pode sobrar apontando para
    uma OS nova."""
    import os
    from app.importar import importar
    os_ = _os_aberta()
    sol.criar('manutencao', 'T', os_id=os_.id)
    importar(os.environ['ZELO_PLANILHA_TESTE'], substituir=True, log=lambda *a: None)
    assert Solicitacao.query.count() == 0
