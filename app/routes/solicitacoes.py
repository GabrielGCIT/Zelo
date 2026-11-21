"""Solicitações: a lista, criar (com ou sem chamado no SD) e cancelar."""
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from app import db
from app.auth import exige, registrar_log
from app.models import Solicitacao

solicitacoes_bp = Blueprint('solicitacoes', __name__)


@solicitacoes_bp.app_template_global()
def solicitacao_de(tipo, pessoa=None, item=None, os_id=None):
    """Para as telas de desligamento, manutenção e item mostrarem a solicitação que já existe em
    vez de oferecer abrir outra."""
    from app.solicitacoes import em_aberto
    return em_aberto(tipo, pessoa, item, os_id)


def _volta():
    """Volta para a tela de onde veio — só caminho interno: um `volta` com outro host seria um
    redirecionamento aberto para quem montar o link."""
    v = request.form.get('volta') or ''
    u = urlparse(v)
    # Barra invertida e caractere de controle ficam de fora: o navegador lê `/\evil.com` como
    # `//evil.com`, e o filtro de `//` sozinho deixava passar (revisão de 20/11).
    if (v.startswith('/') and not v.startswith('//') and not u.scheme and not u.netloc
            and '\\' not in v and not any(ord(c) < 32 for c in v)):
        return v
    return url_for('solicitacoes.lista')


@solicitacoes_bp.route('/solicitacoes')
@exige('ver')
def lista():
    from app import servicedesk as sd
    from app.solicitacoes import TIPOS, situacao
    filtro = request.args.get('ver', 'abertas')
    q = Solicitacao.query
    if filtro == 'abertas':
        # cancelada nunca está em aberto: corta no banco, antes de calcular a situação de cada uma
        q = q.filter(Solicitacao.cancelada_em.is_(None))
    todas = q.order_by(Solicitacao.id.desc()).limit(500).all()
    linhas = [(s, situacao(s)) for s in todas]
    if filtro == 'abertas':
        linhas = [x for x in linhas if x[1] in ('Aberta', 'Atrasada')]
    from app.models import EnvioSD
    pendentes = {e.alvo: e for e in EnvioSD.query.filter(EnvioSD.tipo == 'abrir').order_by(EnvioSD.id)}
    return render_template('solicitacoes.html', linhas=linhas, filtro=filtro, tipos=TIPOS, envios=pendentes,
                           sd_url=(sd.conf('sd_url') or '').rstrip('/'), abrir_ligado=sd.abrir_ligado())


@solicitacoes_bp.route('/solicitacoes/nova', methods=['POST'])
@exige('lancar')
def nova():
    from app import servicedesk as sd
    from app.solicitacoes import TIPOS, criar
    tipo = request.form.get('tipo') or ''
    s, nova_, erro = criar(tipo, g.usuario.nome, pessoa=request.form.get('pessoa') or None,
                           item=request.form.get('item') or None, os_id=request.form.get('os_id') or None)
    if erro:
        flash(erro, 'danger')
        return redirect(_volta())
    if nova_:
        registrar_log('solicitação', f'S-{s.id} {TIPOS[s.tipo]}: {s.assunto}')
    msg = f'S-{s.id} ' + ('criada' if nova_ else 'já existia')
    if request.form.get('chamado') == 'Sim' and not s.chamado:
        if not sd.abrir_ligado():
            flash(msg + '. Abrir chamado pelo Zelo está desligado em Administração → Service Desk.', 'warning')
            return redirect(_volta())
        sd.enfileirar_solicitacao(current_app._get_current_object(), s)
        db.session.refresh(s)
        msg += f' · chamado {s.chamado}' if s.chamado else ' · abertura do chamado na fila do Service Desk'
    flash(msg, 'success')
    return redirect(_volta())


@solicitacoes_bp.route('/solicitacoes/<int:sid>/cancelar', methods=['POST'])
@exige('lancar')
def cancelar(sid):
    from app.solicitacoes import cancelar as _cancelar
    s = db.session.get(Solicitacao, sid)
    if not s:
        flash('Solicitação não encontrada', 'danger')
        return redirect(_volta())
    ok, msg = _cancelar(s, g.usuario.nome, request.form.get('motivo'))
    if ok:
        registrar_log('solicitação', f'{msg}: {s.motivo_cancel}')
    flash(msg, 'success' if ok else 'danger')
    return redirect(_volta())
