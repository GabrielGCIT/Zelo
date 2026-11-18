"""Agente do Zelo: o endereço que recebe o inventário das máquinas e a tela que mostra o que chegou."""
import json

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from app import csrf
from app.auth import exige

agente_bp = Blueprint('agente', __name__)

# Um inventário tem algumas centenas de bytes. Corpo grande não é inventário: é engano ou abuso, e
# não vale a pena ler para descobrir qual.
TAMANHO_MAXIMO = 16 * 1024


def _ip():
    enc = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return enc or request.remote_addr or ''


@agente_bp.route('/api/agente/inventario', methods=['POST'])
@csrf.exempt          # quem chama é um script na máquina, não um formulário com sessão
def inventario():
    """Sem login de propósito: o script roda no logon de qualquer pessoa, ou como SYSTEM. O que
    protege é a senha em `agente_token` e o fato de o endereço só aceitar inventário."""
    from app.agente import ligado, receber, senha_confere
    if not ligado():
        return jsonify(ok=False, erro='agente desligado no Zelo'), 503
    if not senha_confere(request.headers.get('X-Zelo-Agente')):
        return jsonify(ok=False, erro='senha do agente não confere'), 403
    if (request.content_length or 0) > TAMANHO_MAXIMO:
        return jsonify(ok=False, erro='corpo grande demais'), 413
    try:
        dados = json.loads(request.get_data(cache=False, as_text=True) or '{}')
    except ValueError:
        return jsonify(ok=False, erro='o corpo não é JSON'), 400
    ok, recado = receber(dados, _ip())
    return jsonify(ok=ok, **({'recado': recado} if ok else {'erro': recado})), (200 if ok else 400)


@agente_bp.route('/itens/agente', methods=['GET', 'POST'])
@exige('lancar')
def tela():
    """O que as máquinas disseram de si, cruzado com o cadastro. Reaproveita a conferência e a
    cobertura do Service Desk: a pergunta é a mesma, só a fonte muda."""
    from app.agente import como_ativos, ligado
    from app.conferir_sd import aplicar, cobertura, conferir
    from app.models import MaquinaVista
    if request.method == 'POST' and request.form.get('acao') == 'aplicar':
        try:
            escolhas = json.loads(request.form.get('escolhas') or '[]')
        except ValueError:
            escolhas = []
        # só completar o que falta no cadastro: o agente não cadastra item, ele descreve máquina
        escolhas = [e for e in escolhas if not e.get('criar')]
        if not escolhas:
            flash('Nada marcado.', 'warning')
            return redirect(url_for('agente.tela'))
        n, msg, detalhes = aplicar(escolhas, g.usuario.nome)
        flash(msg, 'success' if n else 'warning')
        for d in detalhes[:10]:
            flash(d, 'secondary')
        return redirect(url_for('agente.tela'))

    ativos = como_ativos()
    linhas, _resumo = conferir(ativos) if ativos else ([], {})
    cob = cobertura(ativos, ausente='o agente nunca a viu') if ativos else None
    grupos = {k: [x for x in linhas if x['caso'] == k] for k in ('novo', 'completa', 'divergente', 'repetido')}
    recentes = MaquinaVista.query.order_by(MaquinaVista.visto_em.desc()).limit(50).all()
    return render_template('agente.html', ligado=ligado(), total=MaquinaVista.query.count(), cob=cob,
                           grupos=grupos, recentes=recentes)


@agente_bp.route('/itens/agente/instalar')
@exige('lancar')
def instalar():
    """Como pôr o agente numa máquina do zero. O endereço sugerido é o que está no navegador de
    quem abriu a tela — que é errado quando a pessoa abre o Zelo pelo próprio servidor
    (localhost): a tela avisa, porque as máquinas nunca vão achar 'localhost'."""
    from app.agente import ligado
    from app.models import MaquinaVista
    sugerido = request.url_root.rstrip('/')
    return render_template('agente_instalar.html', ligado=ligado(), sugerido=sugerido,
                           local=request.host.split(':')[0] in ('localhost', '127.0.0.1', '[::1]'),
                           total=MaquinaVista.query.count())


@agente_bp.route('/itens/agente/pacote', methods=['POST'])
@exige('admin')        # o pacote leva a senha do agente dentro do agente.conf
def baixar_pacote():
    from flask import send_file
    import io
    from app.agente import endereco_valido, ligado, pacote
    from app.auth import registrar_log
    from app.models import cfg
    endereco = (request.form.get('endereco') or '').strip()
    if not ligado():
        flash('Defina a "Senha do agente do Zelo" em Configurações antes de gerar o pacote.', 'warning')
        return redirect(url_for('agente.instalar'))
    if not endereco_valido(endereco):
        flash('Endereço inválido: use o formato http://servidor:5001', 'warning')
        return redirect(url_for('agente.instalar'))
    registrar_log('agente', f'pacote do agente gerado para {endereco}')
    return send_file(io.BytesIO(pacote(endereco, cfg('agente_token').strip())), mimetype='application/zip',
                     as_attachment=True, download_name='zelo-agente.zip')
