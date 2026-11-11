from collections import Counter, defaultdict
from datetime import date, timedelta

from flask import request, Blueprint, redirect, render_template, url_for
from sqlalchemy import func

from app import db
from app.auth import exige
from app.models import (CATEGORIAS, EmprestimoAcessorio, Item, Linha, Manutencao, Movimentacao, Pessoa, cfg)

painel_bp = Blueprint('painel', __name__)

ORDEM_SIT = ['Em uso', 'Emprestado', 'Reservada', 'Pendente devolução', 'Em trânsito para o EC', 'Devolvido',
             'Em preparação', 'Em estoque', 'Manutenção', 'Em transferência', 'A localizar', 'Aguardando baixa', 'Baixada']
FLUXO = ('Reservada', 'Pendente devolução', 'Em trânsito para o EC', 'Devolvido', 'Em preparação', 'Em transferência')


def _hoje():
    return date.today().isoformat()


@painel_bp.route('/')
@exige('ver')
def inicio():
    sit = dict(db.session.query(Item.situacao, func.count()).group_by(Item.situacao).all())
    lin = dict(db.session.query(Linha.situacao, func.count()).group_by(Linha.situacao).all())
    pool = Item.finalidade == 'Pool de empréstimo'
    hoje = _hoje()
    parado_dias = int(cfg('dias_fluxo_parado') or 7)
    limite = (date.today() - timedelta(days=parado_dias)).isoformat()
    kpis = [
        ('Itens em uso', sit.get('Em uso', 0) + sit.get('Emprestado', 0), url_for('consulta.itens', situacao='Em uso'), False),
        ('Em estoque (fora o pool)', Item.query.filter(Item.situacao == 'Em estoque', ~pool).count(),
         url_for('consulta.itens', situacao='Em estoque'), False),
        ('Em manutenção', sit.get('Manutenção', 0), url_for('manutencao.inicio'), False),
        ('A localizar', sit.get('A localizar', 0), url_for('consulta.itens', situacao='A localizar'), True),
        ('Linhas em uso', lin.get('Em uso', 0), url_for('linhas.lista', situacao='Em uso'), False),
        ('Linhas livres', lin.get('Livre', 0), url_for('linhas.lista', situacao='Livre'), False),
        ('Entregas em andamento', sit.get('Reservada', 0), url_for('acompanhar.inicio'), False),
        ('Devolução pendente / em trânsito', sit.get('Pendente devolução', 0) + sit.get('Em trânsito para o EC', 0),
         url_for('acompanhar.inicio'), False),
        ('Devolvidos / em preparação', sit.get('Devolvido', 0) + sit.get('Em preparação', 0), url_for('acompanhar.inicio'), False),
        ('Empréstimos vencidos', Item.query.filter(Item.situacao == 'Emprestado', Item.prazo < hoje).count(),
         url_for('consulta.emprestimos'), True),
        ('Fluxo parado', Item.query.filter(Item.situacao.in_(FLUXO), Item.desde < limite).count(), url_for('painel.fila'), True),
        ('Termos pendentes', Item.query.filter(Item.situacao.in_(('Em uso', 'Emprestado')), Item.termo == 'Pendente').count(),
         url_for('painel.fila'), True),
    ]
    matriz = defaultdict(Counter)
    for cat, s, n in db.session.query(Item.categoria, Item.situacao, func.count()).group_by(Item.categoria, Item.situacao):
        matriz[cat or 'Outro'][s] += n
    cats = [c for c in CATEGORIAS if c in matriz] + sorted(c for c in matriz if c not in CATEGORIAS)
    cols = [s for s in ORDEM_SIT if any(matriz[c][s] for c in cats)]
    por_site = (db.session.query(Item.site, func.count()).filter(Item.situacao == 'Em estoque', ~pool)
                .group_by(Item.site).order_by(func.count().desc()).all())
    ultimas = Movimentacao.query.order_by(Movimentacao.id.desc()).limit(12).all()
    return render_template('painel.html', kpis=kpis, matriz=matriz, cats=cats, cols=cols, por_site=por_site,
                           ultimas=ultimas, total=sum(sit.values()))


@painel_bp.route('/fila')
@exige('ver')
def fila():
    hoje = _hoje()
    parado_dias = int(cfg('dias_fluxo_parado') or 7)
    limite = (date.today() - timedelta(days=parado_dias)).isoformat()
    em7 = (date.today() + timedelta(days=7)).isoformat()
    aviso_ct = (date.today() + timedelta(days=int(cfg('aviso_contrato_dias') or 90))).isoformat()
    secoes = []

    def add(titulo, dica, linhas, colunas):
        secoes.append(dict(titulo=titulo, dica=dica, linhas=linhas, colunas=colunas))

    add('Reservas em andamento', 'Avance as etapas na tela Acompanhar.',
        Item.query.filter(Item.situacao == 'Reservada').order_by(Item.desde).all(), 'item')
    add('Devoluções pedidas / em trânsito', 'Quando chegar, lance Devolver.',
        Item.query.filter(Item.situacao.in_(('Pendente devolução', 'Em trânsito para o EC'))).order_by(Item.desde).all(), 'item')
    add('Devolvidos aguardando preparação', 'Confira a chegada e prepare na tela Acompanhar.',
        Item.query.filter(Item.situacao.in_(('Devolvido', 'Em preparação'))).order_by(Item.desde).all(), 'item')
    add(f'Fluxo parado há mais de {parado_dias} dias', 'Itens que não andam: cobre quem está com eles.',
        Item.query.filter(Item.situacao.in_(FLUXO), Item.desde < limite).order_by(Item.desde).all(), 'item')
    add('Empréstimos vencidos ou vencendo em 7 dias', 'Cobre a devolução ou renove.',
        Item.query.filter(Item.situacao == 'Emprestado', Item.prazo <= em7).order_by(Item.prazo).all(), 'item')
    add('Termos pendentes', 'Itens entregues com termo ainda não assinado.',
        Item.query.filter(Item.situacao.in_(('Em uso', 'Emprestado')), Item.termo == 'Pendente').order_by(Item.desde).all(), 'item')
    acs = EmprestimoAcessorio.query.filter(EmprestimoAcessorio.devolvido.is_(None), EmprestimoAcessorio.prazo <= em7).all()
    add('Acessórios emprestados vencidos', 'Cobre a devolução (Lançamentos → acessório).', acs, 'acessorio')
    desl = (db.session.query(Pessoa, func.count(Item.codigo)).join(Item, Item.matricula == Pessoa.id)
            .filter(Pessoa.situacao == 'Desligado', Item.situacao.in_(('Em uso', 'Emprestado', 'Reservada')))
            .group_by(Pessoa.id).all())
    add('Desligados ainda com itens', 'Peça a devolução de tudo que está com a pessoa.', desl, 'pessoa')
    from app.models import Contrato
    cts = Contrato.query.filter(Contrato.fim.isnot(None), Contrato.fim <= aviso_ct).order_by(Contrato.fim).all()
    add('Contratos vencendo', 'Planeje a renovação ou a devolução à locadora.', cts, 'contrato')
    from flask import g
    from app.pendencias import abertas
    todas = request.args.get('pend') == 'todas'
    pend = abertas(None if todas else g.usuario.nome)
    return render_template('fila.html', secoes=secoes, hoje=hoje, pend=pend, pend_todas=todas)


@painel_bp.route('/inicio')
def raiz():
    return redirect(url_for('painel.inicio'))
