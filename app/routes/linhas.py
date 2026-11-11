import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from app import db
from app.auth import exige, pode, registrar_log
from app.models import OPERADORAS, TIPOS_CHIP, Item, Linha, Movimentacao

linhas_bp = Blueprint('linhas', __name__)
CAMPOS_LINHA = [('operadora', 'Operadora'), ('regional', 'Regional'), ('tipo_chip', 'Tipo de chip'), ('iccid', 'ICCID'),
                ('cc', 'Centro de custo'), ('plano', 'Plano'), ('obs', 'Observação')]


@linhas_bp.route('/linhas')
@exige('ver')
def lista():
    f = {k: request.args.get(k, '') for k in ('q', 'situacao', 'operadora')}
    qy = Linha.query
    if f['q']:
        like = f"%{f['q']}%"
        dig = re.sub(r'\D', '', f['q'])
        qy = qy.filter(or_(Linha.numero.ilike(f'%{dig}%') if dig else False, Linha.com_quem.ilike(like),
                           Linha.aparelho.ilike(like), Linha.cc.ilike(like)))
    if f['situacao']:
        qy = qy.filter(Linha.situacao == f['situacao'])
    if f['operadora']:
        qy = qy.filter(Linha.operadora == f['operadora'])
    try:
        p = max(1, int(request.args.get('p', 1)))
    except ValueError:
        p = 1
    pag = qy.order_by(Linha.numero).paginate(page=p, per_page=50, error_out=False)
    modelos = {i.codigo: i.modelo for i in Item.query.filter(Item.codigo.in_([l.aparelho for l in pag.items if l.aparelho]))}
    return render_template('linhas.html', pag=pag, f=f, operadoras=OPERADORAS, modelos=modelos)


@linhas_bp.route('/linha/<numero>', methods=['GET', 'POST'])
@exige('ver')
def ficha(numero):
    ln = db.session.get(Linha, numero) or abort(404)
    if request.method == 'POST':
        if not pode('lancar'):
            abort(403)
        mudou = []
        for k, _r in CAMPOS_LINHA:
            if k in request.form:
                v = request.form.get(k, '').strip() or None
                if getattr(ln, k) != v:
                    mudou.append(f'{k}: {getattr(ln, k)!r} → {v!r}')
                    setattr(ln, k, v)
        if mudou:
            db.session.commit()
            registrar_log('cadastro linha', f'{numero}: ' + '; '.join(mudou))
            flash('Cadastro atualizado.', 'success')
        return redirect(url_for('linhas.ficha', numero=numero))
    movs = Movimentacao.query.filter_by(linha=numero).order_by(Movimentacao.id.desc()).all()
    ap = db.session.get(Item, ln.aparelho) if ln.aparelho else None
    return render_template('linha.html', ln=ln, movs=movs, ap=ap, campos=CAMPOS_LINHA,
                           opcoes={'operadora': OPERADORAS, 'tipo_chip': TIPOS_CHIP})


@linhas_bp.route('/linhas/nova', methods=['POST'])
@exige('lancar')
def nova():
    n = re.sub(r'\D', '', request.form.get('numero', ''))
    if len(n) != 11:
        flash('A linha precisa ter 11 dígitos (DDD + número).', 'danger')
        return redirect(url_for('linhas.lista'))
    if db.session.get(Linha, n):
        flash('Essa linha já está cadastrada.', 'warning')
        return redirect(url_for('linhas.ficha', numero=n))
    db.session.add(Linha(numero=n, operadora=request.form.get('operadora') or None, situacao='Livre'))
    db.session.commit()
    registrar_log('linha cadastrada', n)
    flash('Linha cadastrada.', 'success')
    return redirect(url_for('linhas.ficha', numero=n))


@linhas_bp.route('/linhas/analise', methods=['GET', 'POST'])
@exige('lancar')
def analise():
    from app.analise_linhas import CRITERIO, ORDEM, analisar, gravar_rodada, ler_airwatch, ler_easy
    from app.models import AnaliseLinha
    if request.method == 'POST':
        fe, fa = request.files.get('easy'), request.files.get('airwatch')
        if not fe or not fe.filename or not fa or not fa.filename:
            flash('Envie os dois arquivos: o controle da Easy e o relatório do AirWatch.', 'danger')
            return redirect(url_for('linhas.analise'))
        try:
            res = analisar(ler_easy(fe.stream), ler_airwatch(fa.stream))
        except Exception as e:  # arquivo fora do formato
            flash(f'Não consegui ler os arquivos: {e}', 'danger')
            return redirect(url_for('linhas.analise'))
        rodada, cnt = gravar_rodada(res)
        registrar_log('análise de linhas', f'rodada {rodada}: ' + ', '.join(f'{k} {v}' for k, v in cnt.items()))
        flash(f'Análise feita: {len(res)} linhas.', 'success')
        return redirect(url_for('linhas.analise', rodada=rodada))
    rodadas = [r for (r,) in db.session.query(AnaliseLinha.rodada).distinct().order_by(AnaliseLinha.rodada.desc()).limit(20)]
    rodada = request.args.get('rodada') or (rodadas[0] if rodadas else None)
    dec, q = request.args.get('decisao', ''), request.args.get('q', '')
    qy = AnaliseLinha.query.filter_by(rodada=rodada)
    todos = qy.all()
    cnt = {d: sum(1 for r in todos if r.decisao == d) for d in ORDEM}
    if dec:
        qy = qy.filter_by(decisao=dec)
    if q:
        like = f'%{q}%'
        qy = qy.filter(or_(AnaliseLinha.numero.ilike(like), AnaliseLinha.usuario_easy.ilike(like), AnaliseLinha.com_quem.ilike(like),
                           AnaliseLinha.aw_usuario.ilike(like)))
    return render_template('linhas_analise.html', rodadas=rodadas, rodada=rodada, linhas=qy.order_by(AnaliseLinha.id).all(),
                           cnt=cnt, total=len(todos), ordem=ORDEM, criterio=CRITERIO, dec=dec, q=q)


@linhas_bp.route('/linhas/analise/retorno/<int:aid>', methods=['POST'])
@exige('lancar')
def analise_retorno(aid):
    from app.models import AnaliseLinha
    a = db.session.get(AnaliseLinha, aid) or abort(404)
    a.quem_atendeu = (request.form.get('quem_atendeu') or '').strip() or None
    a.retorno = (request.form.get('retorno') or '').strip() or None
    db.session.commit()
    registrar_log('retorno Easy', f'{a.numero}: {a.quem_atendeu or ""} / {a.retorno or ""}')
    flash(f'{a.numero}: retorno salvo.', 'success')
    return redirect(url_for('linhas.analise', rodada=a.rodada, decisao=request.form.get('decisao', ''), q=request.form.get('q', '')))


@linhas_bp.route('/linhas/analise/<rodada>.xlsx')
@exige('ver')
def analise_xlsx(rodada):
    import os
    import tempfile
    from flask import send_file
    from app.analise_linhas import exportar
    fd, caminho = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    exportar(rodada, caminho)
    return send_file(caminho, as_attachment=True, download_name=f'Analise linhas {rodada[:10]}.xlsx')
