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


@linhas_bp.route('/linhas/analise')
@exige('lancar')
def analise():
    return render_template('erro.html', titulo='Em construção', texto='Esta tela chega no próximo passo.')
