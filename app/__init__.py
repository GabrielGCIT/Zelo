"""Zelo — gestão de ativos de TI (itens, linhas, pessoas, movimentações).

Mesma base do Lastro: Flask + SQLite num arquivo em instance/, servido pelo
waitress, sem nenhum serviço externo para subir antes.
"""
import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
csrf = CSRFProtect()

_APP_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(_APP_DIR, '..'))
INSTANCE_FOLDER = os.path.join(ROOT_DIR, 'instance')
os.makedirs(INSTANCE_FOLDER, exist_ok=True)

BANCO_PADRAO = 'sqlite:///' + os.path.join(INSTANCE_FOLDER, 'zelo.db').replace('\\', '/')
SECRET_KEY_ARQUIVO = os.path.join(INSTANCE_FOLDER, 'secret_key')


def _secret_key():
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    if os.path.exists(SECRET_KEY_ARQUIVO):
        with open(SECRET_KEY_ARQUIVO, encoding='utf-8') as fh:
            k = fh.read().strip()
        if k:
            return k
    import secrets
    k = secrets.token_hex(32)
    with open(SECRET_KEY_ARQUIVO, 'w', encoding='utf-8') as fh:
        fh.write(k)
    return k


def _configurar_sqlite(app):
    from sqlalchemy import event
    with app.app_context():
        engine = db.engine
    if engine.dialect.name != 'sqlite':
        return

    @event.listens_for(engine, 'connect')
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        if engine.url.database not in (None, '', ':memory:'):
            cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA busy_timeout=5000')
        cur.close()


# Colunas novas em tabelas que já existem (o create_all só cria tabelas). Só acrescenta, nunca apaga.
COLUNAS_NOVAS = [('envios_sd', 'tipo', "VARCHAR(10) DEFAULT 'chamado'"), ('envios_sd', 'alvo', 'VARCHAR(60)'),
                 ('movimentacoes', 'termo_arquivo', 'VARCHAR(120)')]


def _migrar():
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    for tabela, coluna, tipo in COLUNAS_NOVAS:
        if tabela in insp.get_table_names() and coluna not in {c['name'] for c in insp.get_columns(tabela)}:
            with db.engine.begin() as cx:
                cx.execute(text(f'ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}'))


def create_app(database_url=None, testing=False):
    app = Flask(__name__, template_folder=os.path.join(ROOT_DIR, 'templates'),
                static_folder=os.path.join(ROOT_DIR, 'static'))
    app.secret_key = _secret_key()
    app.config.update(
        SQLALCHEMY_DATABASE_URI=database_url or os.environ.get('DATABASE_URL') or BANCO_PADRAO,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=30 * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=28800,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '0') == '1',
        TESTING=testing,
        WTF_CSRF_ENABLED=not testing,
    )
    db.init_app(app)
    csrf.init_app(app)
    _configurar_sqlite(app)

    from app import models  # noqa: F401  (registra as tabelas)
    with app.app_context():
        db.create_all()
        _migrar()

    from app.auth import auth_bp, registrar_hooks
    from app.routes.consulta import consulta_bp
    from app.routes.painel import painel_bp
    from app.routes.lancar import lancar_bp
    from app.routes.acompanhar import acompanhar_bp
    from app.routes.manutencao import manutencao_bp
    from app.routes.estoque import estoque_bp
    from app.routes.linhas import linhas_bp
    from app.routes.termo import termo_bp
    from app.routes.admin import admin_bp
    from app.routes.bipar import bipar_bp
    from app.routes.busca import busca_bp
    from app.routes.desligar import desligar_bp
    from app.routes.assinar import assinar_bp
    from app.routes.importar import importar_bp
    for bp in (auth_bp, painel_bp, consulta_bp, lancar_bp, acompanhar_bp, manutencao_bp, estoque_bp,
               linhas_bp, termo_bp, admin_bp, bipar_bp, busca_bp, desligar_bp, assinar_bp, importar_bp):
        app.register_blueprint(bp)
    registrar_hooks(app)

    from app import formato
    formato.registrar(app)
    return app
