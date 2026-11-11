import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app import db
from app.auth import criar_usuario, exige, registrar_log
from app.models import CONFIG_PADRAO, PERFIS, Config, LogAuditoria, Usuario

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ROTULOS_CONFIG = {
    'empresa': 'Empresa (aparece no termo e no cabeçalho)',
    'prazo_emprestimo': 'Prazo padrão de empréstimo (dias)',
    'fluxo_preparacao': 'Notebook devolvido a partir desta data passa pela preparação (AAAA-MM-DD)',
    'dias_fluxo_parado': 'Dias para considerar o fluxo parado',
    'aviso_contrato_dias': 'Avisar contrato vencendo com quantos dias',
    'equipe': 'Equipe (responsáveis), separados por ;',
    'tecnicos': 'Técnicos, separados por ;',
    'recebido_por': 'Quem recebe devoluções no EC, separados por ;',
}


@admin_bp.route('/usuarios', methods=['GET', 'POST'])
@exige('admin')
def usuarios():
    senha_gerada = None
    if request.method == 'POST':
        acao = request.form.get('acao')
        if acao == 'criar':
            email = request.form.get('email', '').strip().lower()
            nome = request.form.get('nome', '').strip()
            perfil = request.form.get('perfil')
            if not nome or '@' not in email or perfil not in PERFIS:
                flash('Preencha nome, e-mail e perfil.', 'danger')
            elif Usuario.query.filter_by(email=email).first():
                flash('Esse e-mail já tem usuário.', 'warning')
            else:
                senha_gerada = secrets.token_urlsafe(8)
                criar_usuario(nome, email, senha_gerada, perfil, provisoria=True)
                registrar_log('usuário criado', f'{email} ({perfil})')
                flash(f'Usuário criado. Senha provisória: {senha_gerada} (passe para a pessoa; ela troca no primeiro login).', 'success')
        else:
            u = db.session.get(Usuario, int(request.form.get('id', 0))) or abort(404)
            if acao == 'perfil' and request.form.get('perfil') in PERFIS:
                u.perfil = request.form['perfil']
                registrar_log('perfil alterado', f'{u.email} → {u.perfil}')
            elif acao == 'ativo':
                u.ativo = not u.ativo
                registrar_log('usuário ' + ('reativado' if u.ativo else 'desativado'), u.email)
            elif acao == 'senha':
                senha_gerada = secrets.token_urlsafe(8)
                u.senha_hash = generate_password_hash(senha_gerada)
                u.senha_provisoria, u.login_tentativas, u.login_bloqueado_ate = True, 0, None
                registrar_log('senha redefinida', u.email)
                flash(f'Senha provisória de {u.nome}: {senha_gerada}', 'success')
            db.session.commit()
        return redirect(url_for('admin.usuarios'))
    return render_template('admin_usuarios.html', usuarios=Usuario.query.order_by(Usuario.nome).all(), perfis=PERFIS)


@admin_bp.route('/config', methods=['GET', 'POST'])
@exige('admin')
def config():
    if request.method == 'POST':
        for k in CONFIG_PADRAO:
            if k in request.form:
                v = request.form[k].strip()
                c = db.session.get(Config, k)
                if c is None:
                    db.session.add(Config(chave=k, valor=v))
                elif c.valor != v:
                    c.valor = v
        db.session.commit()
        registrar_log('configurações alteradas', '')
        flash('Configurações salvas.', 'success')
        return redirect(url_for('admin.config'))
    valores = {k: (db.session.get(Config, k).valor if db.session.get(Config, k) else v) for k, v in CONFIG_PADRAO.items()}
    return render_template('admin_config.html', valores=valores, rotulos=ROTULOS_CONFIG)


@admin_bp.route('/auditoria')
@exige('admin')
def auditoria():
    q = request.args.get('q', '')
    qy = LogAuditoria.query
    if q:
        qy = qy.filter(LogAuditoria.detalhe.ilike(f'%{q}%') | LogAuditoria.acao.ilike(f'%{q}%') | LogAuditoria.usuario.ilike(f'%{q}%'))
    logs = qy.order_by(LogAuditoria.id.desc()).limit(500).all()
    return render_template('admin_auditoria.html', logs=logs, q=q)


@admin_bp.route('/servicedesk', methods=['GET', 'POST'])
@exige('admin')
def servicedesk():
    from app import servicedesk as sd
    from app.models import EnvioSD
    if request.method == 'POST':
        acao = request.form.get('acao')
        if acao == 'salvar':
            v = {'sd_url': (request.form.get('sd_url') or '').strip().rstrip('/'),
                 'sd_ssl': request.form.get('sd_ssl') or 'Verificar', 'sd_ativo': request.form.get('sd_ativo') or 'Não'}
            if (request.form.get('sd_chave') or '').strip():
                v['sd_chave'] = request.form['sd_chave'].strip()
            sd.salvar_conf(v)
            registrar_log('service desk', f'configuração salva: {v["sd_url"]}, ativo={v["sd_ativo"]}'
                          + (', chave trocada' if 'sd_chave' in v else ''))
            flash('Configuração salva.', 'success')
        elif acao == 'testar':
            try:
                sd.testar()
                flash('Conexão OK: o Service Desk respondeu com a chave configurada.', 'success')
            except sd.ErroSD as e:
                flash(str(e), 'danger')
        elif acao == 'reenviar':
            ids = [int(i) for i in request.form.getlist('ids') if i.isdigit()] or \
                  [e.id for e in EnvioSD.query.filter(EnvioSD.status != 'Enviado')]
            ok = sum(sd.enviar(e) for e in EnvioSD.query.filter(EnvioSD.id.in_(ids)))
            registrar_log('service desk', f'reenvio: {ok} de {len(ids)} enviado(s)')
            flash(f'{ok} de {len(ids)} envio(s) concluído(s).', 'success' if ok == len(ids) else 'warning')
        return redirect(url_for('admin.servicedesk'))
    envios = EnvioSD.query.order_by(EnvioSD.id.desc()).limit(150).all()
    return render_template('admin_servicedesk.html', url=sd.conf('sd_url'), tem_chave=bool(sd.conf('sd_chave')),
                           ssl=sd.conf('sd_ssl') or 'Verificar', ativo=sd.conf('sd_ativo') or 'Não', envios=envios,
                           pendentes=sum(1 for e in envios if e.status != 'Enviado'))
