import re
from datetime import date, timedelta

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from app import db
from app.auth import exige, registrar_log
from app.lancamento import ABAS, ACOES, KIT_OPCOES, conferir, desfazer_ultimo, gravar, proximo_id_pessoa
from app.models import (ESTADOS_DEV, MOTIVOS, PRAZOS, SITES, TERMOS, TIPOS_PESSOA, Consumivel, EmprestimoAcessorio,
                        Item, Linha, MovConsumivel, Pessoa, cfg_lista)

lancar_bp = Blueprint('lancar', __name__)
LINHAS_GRADE = 10


@lancar_bp.route('/lancar')
@exige('lancar')
def grade():
    aba = request.args.get('aba', 'entrega')
    if aba not in ABAS:
        aba = 'entrega'
    pre = {k: request.args.get(k, '') for k in ('item', 'para', 'linha')}
    if pre['item']:
        it = db.session.get(Item, pre['item'])
        if it and it.finalidade == 'Pool de empréstimo' and 'aba' not in request.args:
            aba = 'emprestimo'
        elif it and it.categoria in ('Celular', 'Tablet') and 'aba' not in request.args:
            aba = 'mobile'
    consumiveis = [c.nome for c in Consumivel.query.order_by(Consumivel.nome)]
    return render_template('lancar.html', aba=aba, abas=ABAS, pre=pre, n=LINHAS_GRADE, motivos=MOTIVOS, termos=TERMOS,
                           tecnicos=cfg_lista('tecnicos'), recebido=cfg_lista('recebido_por'), kit=KIT_OPCOES,
                           prazos=PRAZOS, consumiveis=consumiveis)


def _linhas_do_pedido():
    return (request.get_json(silent=True) or {}).get('linhas') or []


@lancar_bp.route('/api/lancar/conferir', methods=['POST'])
@exige('lancar')
def api_conferir():
    aba = (request.get_json(silent=True) or {}).get('aba', 'entrega')
    return jsonify([r.json() for r in conferir(_linhas_do_pedido(), aba)])


@lancar_bp.route('/api/lancar/gravar', methods=['POST'])
@exige('lancar')
def api_gravar():
    aba = (request.get_json(silent=True) or {}).get('aba', 'entrega')
    resultados, n, lote = gravar(_linhas_do_pedido(), aba, g.usuario.nome)
    if n:
        registrar_log('lançamento', f'{n} linha(s) gravada(s) na aba {aba}, lote {lote}')
    return jsonify({'gravadas': n, 'lote': lote,
                    'resultados': [dict(r.json(), gravada=r.status in ('ok', 'aviso'),
                                        nums=[m.id for m in r.movs if m.id]) for r in resultados]})


@lancar_bp.route('/api/lancar/desfazer', methods=['POST'])
@exige('lancar')
def api_desfazer():
    n, lote = desfazer_ultimo(g.usuario.nome)
    if n:
        registrar_log('desfazer', f'lote {lote}: {n} lançamento(s) apagado(s)')
    return jsonify({'apagados': n, 'lote': lote})


@lancar_bp.route('/api/pessoas')
@exige('ver')
def api_pessoas():
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])
    like = f'%{q}%'
    ps = (Pessoa.query.filter(Pessoa.situacao != 'Desligado', (Pessoa.nome.ilike(like)) | (Pessoa.id.ilike(like)))
          .order_by(Pessoa.nome).limit(15).all())
    return jsonify([{'id': p.id, 'nome': p.nome, 'rotulo': f'{p.nome} · {p.id}'} for p in ps])


@lancar_bp.route('/api/item')
@exige('ver')
def api_item():
    from app.routes.consulta import achar_item
    it = achar_item(request.args.get('q'))
    if not it:
        return jsonify(None)
    return jsonify({'codigo': it.codigo, 'categoria': it.categoria, 'modelo': it.modelo, 'situacao': it.situacao,
                    'com_quem': it.com_quem})


# ------------------------------------------------------------------ pessoa: cadastrar / atualizar / desligar
CPF_RE = re.compile(r'^\d{11}$')


def cpf_valido(c):
    c = re.sub(r'\D', '', c or '')
    if not CPF_RE.match(c) or c == c[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(c[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(c[n]):
            return False
    return True


@lancar_bp.route('/lancar/pessoa', methods=['GET', 'POST'])
@exige('lancar')
def pessoa():
    if request.method == 'POST':
        acao = request.form.get('acao')
        f = {k: (request.form.get(k) or '').strip() for k in ('pessoa', 'id', 'nome', 'tipo', 'empresa', 'cpf', 'jde',
                                                             'cc', 'cargo', 'site', 'user', 'email', 'obs')}
        if f['cpf'] and not cpf_valido(f['cpf']):
            flash('CPF inválido.', 'danger')
            return redirect(url_for('lancar.pessoa'))
        if acao == 'cadastrar':
            if not f['nome'] or not f['tipo']:
                flash('Informe nome e tipo.', 'danger')
                return redirect(url_for('lancar.pessoa'))
            pid = f['id'].upper() or proximo_id_pessoa('P' if f['tipo'] == 'Posto' else 'T')
            if db.session.get(Pessoa, pid):
                flash(f'Já existe alguém com o ID {pid}.', 'danger')
                return redirect(url_for('lancar.pessoa'))
            cpf = re.sub(r'\D', '', f['cpf']) or None
            if cpf and Pessoa.query.filter_by(cpf=cpf).first():
                flash('Esse CPF já está cadastrado.', 'danger')
                return redirect(url_for('lancar.pessoa'))
            if Pessoa.query.filter(db.func.upper(Pessoa.nome) == f['nome'].upper()).first():
                flash('Aviso: já existe uma pessoa com esse nome (cadastrada mesmo assim).', 'warning')
            p = Pessoa(id=pid, nome=f['nome'].upper(), tipo=f['tipo'],
                       empresa=f['empresa'] or ('Martin Brower' if f['tipo'] == 'CLT' else None), cpf=cpf,
                       jde=f['jde'] or None, cc=f['cc'] or None, cargo=f['cargo'] or None, site=f['site'] or None,
                       user=f['user'] or None, email=f['email'] or None, obs=f['obs'] or None, situacao='Ativo')
            db.session.add(p)
            db.session.commit()
            registrar_log('pessoa cadastrada', f'{pid} {p.nome}')
            flash(f'{p.nome} cadastrado(a) com o ID {pid}.', 'success')
            return redirect(url_for('consulta.pessoa', pid=pid))
        p = db.session.get(Pessoa, f['pessoa']) if f['pessoa'] else None
        if not p:
            flash('Escolha a pessoa.', 'danger')
            return redirect(url_for('lancar.pessoa'))
        if acao == 'desligar':
            p.situacao = 'Desligado'
            itens = Item.query.filter(Item.matricula == p.id, Item.situacao.in_(('Em uso', 'Emprestado'))).all()
            linhas_ = Linha.query.filter(Linha.matricula == p.id, Linha.situacao == 'Em uso').all()
            db.session.commit()
            # o desligamento abre o pedido de devolução de tudo que está com a pessoa
            from app.lancamento import gravar as _gravar
            ped = [{'acao': 'Pedir devolução', 'item': i.codigo, 'motivo': 'Desligamento'} for i in itens]
            _r, n, lote = _gravar(ped, 'entrega', g.usuario.nome) if ped else ([], 0, None)
            registrar_log('pessoa desligada', f'{p.id} {p.nome}: {n} pedido(s) de devolução, {len(linhas_)} linha(s) em uso')
            flash(f'{p.nome} desligado(a). {n} pedido(s) de devolução aberto(s)' +
                  (f'; {len(linhas_)} linha(s) em uso: devolva ou desative em Lançamentos → Mobile.' if linhas_ else '.'),
                  'success')
            return redirect(url_for('consulta.pessoa', pid=p.id))
        mudou = []
        for k in ('nome', 'tipo', 'empresa', 'cpf', 'jde', 'cc', 'cargo', 'site', 'user', 'email', 'obs'):
            if f[k]:
                v = f[k].upper() if k == 'nome' else (re.sub(r'\D', '', f[k]) if k == 'cpf' else f[k])
                if getattr(p, k) != v:
                    mudou.append(f'{k}: {getattr(p, k)!r} → {v!r}')
                    setattr(p, k, v)
        db.session.commit()
        registrar_log('pessoa atualizada', f'{p.id}: ' + '; '.join(mudou))
        flash('Cadastro atualizado.' if mudou else 'Nada mudou.', 'success')
        return redirect(url_for('consulta.pessoa', pid=p.id))
    return render_template('lancar_pessoa.html', tipos=TIPOS_PESSOA, sites=SITES)


# ------------------------------------------------------------------ acessórios (fonte, mouse, headset...)
@lancar_bp.route('/lancar/acessorio', methods=['POST'])
@exige('lancar')
def acessorio():
    from app.lancamento import achar_pessoa, saldo
    acao = request.form.get('acao_ac')
    hoje = date.today().isoformat()
    if acao == 'emprestar':
        cons = request.form.get('consumivel', '')
        qtd = int(request.form.get('qtd') or 1)
        p, nova, erro = achar_pessoa(request.form.get('para_ac'))
        if erro or not (p or nova):
            flash(erro or 'Informe para quem.', 'danger')
        elif not Consumivel.query.filter_by(nome=cons).first():
            flash('Escolha um acessório do catálogo.', 'danger')
        elif saldo(cons, 'EC') < qtd:
            flash(f'Sem saldo suficiente de {cons} no EC (tem {saldo(cons, "EC")}).', 'danger')
        else:
            if nova:
                nova['id'] = nova['id'] or proximo_id_pessoa('T')
                db.session.add(Pessoa(situacao='Ativo', **nova))
                p = nova
            pid, nome = (p.id, p.nome) if isinstance(p, Pessoa) else (p['id'], p['nome'])
            dias = int(request.form.get('prazo_ac') or 30)
            ea = EmprestimoAcessorio(data=hoje, consumivel=cons, qtd=qtd, matricula=pid, nome=nome,
                                     prazo=(date.today() + timedelta(days=dias)).isoformat(),
                                     chamado=request.form.get('chamado_ac') or None, resp=g.usuario.nome,
                                     obs=request.form.get('obs_ac') or None)
            db.session.add(ea)
            db.session.flush()
            db.session.add(MovConsumivel(data=hoje, consumivel=cons, site='EC', movimento='Saída', qtd=qtd, destino=nome,
                                         resp=g.usuario.nome, obs=f'Empréstimo EA-{ea.id:04d}'))
            db.session.commit()
            registrar_log('acessório emprestado', f'EA-{ea.id:04d} {cons} x{qtd} para {nome}')
            flash(f'Emprestado: EA-{ea.id:04d} ({cons} para {nome}). Termo: digite EA-{ea.id:04d} na tela Termo.', 'success')
    elif acao == 'devolver':
        num = re.sub(r'\D', '', request.form.get('ea', ''))
        ea = db.session.get(EmprestimoAcessorio, int(num)) if num else None
        if not ea or ea.devolvido:
            flash('Empréstimo de acessório não encontrado ou já devolvido.', 'danger')
        else:
            ea.devolvido, ea.receb = hoje, request.form.get('receb_ac') or g.usuario.nome
            ea.obs_dev = request.form.get('obs_ac') or None
            db.session.add(MovConsumivel(data=hoje, consumivel=ea.consumivel, site='EC', movimento='Entrada', qtd=ea.qtd,
                                         destino=ea.nome, resp=g.usuario.nome, obs=f'Devolução EA-{ea.id:04d}'))
            db.session.commit()
            registrar_log('acessório devolvido', f'EA-{ea.id:04d}')
            flash(f'EA-{ea.id:04d} devolvido; o saldo do EC voltou.', 'success')
    return redirect(url_for('lancar.grade', aba='emprestimo'))
