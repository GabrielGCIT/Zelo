"""Login, perfis e auditoria.

Perfis fechados (Administrador, Operador, Consulta). O primeiro administrador é
criado pelo endereço de primeiro acesso que o run.py imprime no console, como no
Lastro: quem não tem acesso ao servidor não consegue se autonomear admin.
"""
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import INSTANCE_FOLDER, db
from app.models import LogAuditoria, Usuario

auth_bp = Blueprint('auth', __name__)
TOKEN_ARQUIVO = os.path.join(INSTANCE_FOLDER, 'primeiro_acesso.token')
MAX_TENTATIVAS = 5
BLOQUEIO = timedelta(minutes=15)


# --------------------------------------------------------------------------- helpers
def registrar_log(acao, detalhe=''):
    try:
        u = getattr(g, 'usuario', None)
        db.session.add(LogAuditoria(usuario=u.nome if u else 'sistema', acao=acao, detalhe=str(detalhe)[:4000]))
        db.session.commit()
    except Exception:  # auditoria nunca derruba a operação
        db.session.rollback()


def pode(acao):
    """'ver' = todos; 'lancar' = Operador e Administrador; 'admin' = Administrador."""
    u = getattr(g, 'usuario', None)
    if not u:
        return False
    if acao == 'ver':
        return True
    if acao == 'lancar':
        return u.perfil in ('Operador', 'Administrador')
    return u.perfil == 'Administrador'


def exige(acao='ver'):
    def deco(f):
        @wraps(f)
        def inner(*a, **kw):
            if not getattr(g, 'usuario', None):
                return redirect(url_for('auth.login', next=request.full_path))
            if not pode(acao):
                abort(403)
            return f(*a, **kw)
        return inner
    return deco


def problema_na_senha(senha, confirmacao=None):
    if not senha or len(senha) < 8:
        return 'A senha precisa ter pelo menos 8 caracteres.'
    if confirmacao is not None and senha != confirmacao:
        return 'A confirmação não confere.'
    return None


def preparar_primeiro_acesso():
    """Sem usuário nenhum, gera (ou reaproveita) o token do endereço de primeiro acesso."""
    if Usuario.query.count():
        if os.path.exists(TOKEN_ARQUIVO):
            os.remove(TOKEN_ARQUIVO)
        return None
    if os.path.exists(TOKEN_ARQUIVO):
        with open(TOKEN_ARQUIVO, encoding='utf-8') as fh:
            t = fh.read().strip()
        if t:
            return t
    t = secrets.token_urlsafe(24)
    with open(TOKEN_ARQUIVO, 'w', encoding='utf-8') as fh:
        fh.write(t)
    return t


def criar_usuario(nome, email, senha, perfil='Operador', provisoria=False):
    u = Usuario(nome=nome.strip(), email=email.strip().lower(), senha_hash=generate_password_hash(senha),
                perfil=perfil, senha_provisoria=provisoria)
    db.session.add(u)
    db.session.commit()
    return u


# --------------------------------------------------------------------------- hooks
def _versao():
    import os
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'VERSAO'), encoding='utf-8') as fh:
            return fh.read().strip()
    except OSError:
        return ''


def registrar_hooks(app):
    @app.before_request
    def _carregar_usuario():
        g.usuario = None
        uid = session.get('uid')
        if uid:
            u = db.session.get(Usuario, uid)
            if u and u.ativo:
                g.usuario = u
            else:
                session.clear()
        if (g.usuario and g.usuario.senha_provisoria
                and request.endpoint not in ('auth.trocar_senha', 'auth.logout', 'static')):
            return redirect(url_for('auth.trocar_senha'))

    @app.context_processor
    def _globais():
        from app.models import cfg
        return dict(usuario=getattr(g, 'usuario', None), pode=pode, empresa=cfg('empresa'), versao=_versao(),
                    lembretes_n=_lembretes_n)

    def _lembretes_n():
        """(quantos, urgentes) para o número ao lado de Minha fila. Nunca derruba a tela."""
        if not getattr(g, 'usuario', None):
            return (0, 0)
        try:
            from app.lembretes import contagem
            return contagem()
        except Exception:                        # noqa: BLE001
            app.logger.exception('Falha ao contar lembretes')
            return (0, 0)

    @app.errorhandler(403)
    def _proibido(_e):
        return render_template('erro.html', titulo='Sem permissão',
                               texto='O seu perfil não permite esta ação. Fale com o administrador do Zelo.'), 403

    @app.errorhandler(404)
    def _nao_achou(_e):
        return render_template('erro.html', titulo='Não encontrado', texto='O endereço não existe.'), 404


# --------------------------------------------------------------------------- telas
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if not Usuario.query.count():
        return render_template('login.html', sem_usuario=True)
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        senha = request.form.get('senha') or ''
        u = Usuario.query.filter_by(email=email).first()
        agora = datetime.now()
        if u and u.login_bloqueado_ate and u.login_bloqueado_ate > agora:
            flash('Muitas tentativas. Tente de novo em alguns minutos.', 'danger')
            return render_template('login.html')
        if not u or not u.ativo or not check_password_hash(u.senha_hash, senha):
            if u:
                u.login_tentativas = (u.login_tentativas or 0) + 1
                if u.login_tentativas >= MAX_TENTATIVAS:
                    u.login_bloqueado_ate, u.login_tentativas = agora + BLOQUEIO, 0
                db.session.commit()
            flash('E-mail ou senha incorretos.', 'danger')
            return render_template('login.html')
        u.login_tentativas, u.login_bloqueado_ate = 0, None
        db.session.commit()
        session.clear()
        session['uid'] = u.id
        session.permanent = True
        g.usuario = u
        registrar_log('login', u.email)
        nxt = request.args.get('next') or ''
        return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('painel.inicio'))
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/primeiro-acesso/<token>', methods=['GET', 'POST'])
def primeiro_acesso(token):
    esperado = preparar_primeiro_acesso()
    if not esperado or not secrets.compare_digest(esperado, token):
        abort(404)
    erro = None
    if request.method == 'POST':
        nome, email = request.form.get('nome', '').strip(), request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        erro = problema_na_senha(senha, request.form.get('confirmacao', ''))
        if not erro and (not nome or '@' not in email):
            erro = 'Informe nome e e-mail.'
        if not erro:
            u = criar_usuario(nome, email, senha, 'Administrador')
            preparar_primeiro_acesso()
            session.clear()
            session['uid'] = u.id
            return redirect(url_for('painel.inicio'))
    return render_template('primeiro_acesso.html', erro=erro)


@auth_bp.route('/trocar-senha', methods=['GET', 'POST'])
@exige('ver')
def trocar_senha():
    erro = None
    if request.method == 'POST':
        u = g.usuario
        if not u.senha_provisoria and not check_password_hash(u.senha_hash, request.form.get('atual', '')):
            erro = 'Senha atual incorreta.'
        else:
            erro = problema_na_senha(request.form.get('senha', ''), request.form.get('confirmacao', ''))
        if not erro:
            u.senha_hash = generate_password_hash(request.form['senha'])
            u.senha_provisoria = False
            db.session.commit()
            registrar_log('senha trocada', u.email)
            flash('Senha trocada.', 'success')
            return redirect(url_for('painel.inicio'))
    return render_template('trocar_senha.html', erro=erro)
