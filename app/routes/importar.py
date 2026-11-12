"""Importar do Service Desk: hoje, pessoas (nome, e-mail e login)."""
import json

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auth import exige
from app.importar_sd import CASOS, MAX_PAGINAS, POR_PAGINA, aplicar, baixar, conferir

importar_bp = Blueprint('importar', __name__)


@importar_bp.route('/pessoas/importar-sd', methods=['GET', 'POST'])
@exige('lancar')
def pessoas():
    from app import servicedesk as sd
    if request.method == 'POST' and request.form.get('acao') == 'aplicar':
        try:
            escolhas = json.loads(request.form.get('escolhas') or '[]')
        except ValueError:
            escolhas = []
        if not escolhas:
            flash('Nada marcado para trazer.', 'warning')
            return redirect(url_for('importar.pessoas'))
        n, msg, detalhes = aplicar(escolhas, g.usuario.nome)
        flash(msg, 'success' if n else 'warning')
        for d in detalhes[:10]:
            flash(d, 'secondary')
        return redirect(url_for('importar.pessoas', de_novo='1'))

    linhas, resumo, erro, truncou = [], {}, '', False
    if request.method == 'POST' or request.args.get('de_novo'):
        usuarios, truncou, erro = baixar()
        if usuarios:
            linhas, resumo = conferir(usuarios)
    return render_template('importar_pessoas.html', linhas=linhas, resumo=resumo, erro=erro, truncou=truncou,
                           casos=CASOS, ligado=sd.configurado(), teto=MAX_PAGINAS * POR_PAGINA,
                           buscou=bool(request.method == 'POST' or request.args.get('de_novo')))


@importar_bp.route('/itens/conferir-sd', methods=['GET', 'POST'])
@exige('lancar')
def itens():
    """Ativos: o que falta importar e onde o Zelo e o Service Desk discordam. Uma busca, duas perguntas."""
    import json as _json
    from app import servicedesk as sd
    from app.conferir_sd import GRUPOS, MAX_PAGINAS, POR_PAGINA
    from app.conferir_sd import aplicar as aplicar_itens
    from app.conferir_sd import baixar as baixar_itens
    from app.conferir_sd import conferir as conferir_itens
    from app.models import CATEGORIAS, SITES
    if request.method == 'POST' and request.form.get('acao') == 'aplicar':
        try:
            escolhas = _json.loads(request.form.get('escolhas') or '[]')
        except ValueError:
            escolhas = []
        if not escolhas:
            flash('Nada marcado.', 'warning')
            return redirect(url_for('importar.itens'))
        n, msg, detalhes = aplicar_itens(escolhas, g.usuario.nome)
        flash(msg, 'success' if n else 'warning')
        for d in detalhes[:10]:
            flash(d, 'secondary')
        return redirect(url_for('importar.itens', de_novo='1'))

    linhas, resumo, erro, truncou = [], {}, '', False
    buscou = bool(request.method == 'POST' or request.args.get('de_novo'))
    if buscou:
        ativos, truncou, erro = baixar_itens()
        if ativos:
            linhas, resumo = conferir_itens(ativos)
    return render_template('conferir_itens.html', linhas=linhas, resumo=resumo, erro=erro, truncou=truncou,
                           grupos=GRUPOS, ligado=sd.configurado(), teto=MAX_PAGINAS * POR_PAGINA, buscou=buscou,
                           categorias=CATEGORIAS, sites=SITES)
