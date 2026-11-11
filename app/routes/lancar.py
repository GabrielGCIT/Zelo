import re
from datetime import date, timedelta

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from app import db
from app.auth import exige, registrar_log
from app.lancamento import (ABAS, ACOES, CAMPOS_ACAO, CARDS, KIT_OPCOES, acoes_possiveis, card_do_item, conferir,
                            desfazer_ultimo, gravar, proximo_id_pessoa)
from app.models import (ESTADOS_DEV, MOTIVOS, PRAZOS, SITES, TERMOS, TIPOS_PESSOA, Consumivel, EmprestimoAcessorio,
                        Item, Linha, MovConsumivel, Pessoa, cfg_lista)

lancar_bp = Blueprint('lancar', __name__)
LINHAS_GRADE = 10


def _listas():
    return dict(motivos=MOTIVOS, termos=TERMOS, tecnicos=cfg_lista('tecnicos'), recebido=cfg_lista('recebido_por'),
                kit=KIT_OPCOES, prazos=PRAZOS, sites=SITES,
                consumiveis=[c.nome for c in Consumivel.query.order_by(Consumivel.nome)])


@lancar_bp.route('/lancar')
@exige('lancar')
def grade():
    """Lançamento em cards: escolhe o tipo, digita o item, e a tela mostra só o que dá para fazer com ele."""
    pre = {k: request.args.get(k, '') for k in ('item', 'para', 'linha', 'acao')}
    card = request.args.get('card', '')
    if pre['item'] and card not in CARDS:
        from app.routes.consulta import achar_item
        it = achar_item(pre['item'])
        card = card_do_item(it) if it else 'notebook'
    if card not in CARDS:
        card = 'mobile' if pre['linha'] else 'notebook'
    return render_template('lancar_cards.html', cards=CARDS, card=card, pre=pre, campos_acao=CAMPOS_ACAO, **_listas())


@lancar_bp.route('/lancar/lote')
@exige('lancar')
def lote():
    """A grade (várias linhas de uma vez): rollout, inventário, lançamentos em série."""
    aba = request.args.get('aba', 'entrega')
    if aba not in ABAS:
        aba = 'entrega'
    pre = {k: request.args.get(k, '') for k in ('item', 'para', 'linha')}
    return render_template('lancar.html', aba=aba, abas=ABAS, pre=pre, n=LINHAS_GRADE, **_listas())


@lancar_bp.route('/api/lancar/contexto')
@exige('lancar')
def api_contexto():
    """O que é o item/linha digitado e quais ações cabem agora."""
    from app.lancamento import so_digitos
    from app.routes.consulta import achar_item
    card = request.args.get('card', 'notebook')
    if card not in CARDS or not CARDS[card][3]:
        card = 'notebook'
    it = achar_item(request.args.get('item')) if request.args.get('item') else None
    n = so_digitos(request.args.get('linha', ''))
    ln = db.session.get(Linha, n) if len(n) == 11 else None
    if it and card != 'estoque':
        card = card_do_item(it)
    acoes, recado = acoes_possiveis(it, ln, card)
    return jsonify({
        'card': card, 'acoes': acoes, 'recado': recado,
        'achou_item': bool(it) if request.args.get('item') else None,
        'achou_linha': bool(ln) if request.args.get('linha') else None,
        'item': it and {'codigo': it.codigo, 'categoria': it.categoria, 'modelo': it.modelo, 'tag': it.tag,
                        'situacao': it.situacao, 'com_quem': it.com_quem, 'site': it.site,
                        'pool': it.finalidade == 'Pool de empréstimo', 'linha': it.linha_atual},
        'linha': ln and {'numero': ln.numero, 'operadora': ln.operadora, 'situacao': ln.situacao, 'com_quem': ln.com_quem,
                         'aparelho': ln.aparelho}})


def _aba_do_pedido():
    j = request.get_json(silent=True) or {}
    if j.get('card') in CARDS and CARDS[j['card']][3]:
        return CARDS[j['card']][3]
    return j.get('aba', 'entrega')


def _linhas_do_pedido():
    return (request.get_json(silent=True) or {}).get('linhas') or []


@lancar_bp.route('/api/lancar/conferir', methods=['POST'])
@exige('lancar')
def api_conferir():
    from app.espelho import espelho
    aba = _aba_do_pedido()
    linhas = _linhas_do_pedido()
    return jsonify([dict(r.json(), espelho=espelho(d) if r.status else None)
                    for r, d in zip(conferir(linhas, aba), linhas)])


@lancar_bp.route('/api/lancar/gravar', methods=['POST'])
@exige('lancar')
def api_gravar():
    aba = _aba_do_pedido()
    resultados, n, lote = gravar(_linhas_do_pedido(), aba, g.usuario.nome)
    if n:
        registrar_log('lançamento', f'{n} linha(s) gravada(s) na aba {aba}, lote {lote}')
        from flask import current_app
        from app import servicedesk as sd
        sd.enfileirar_tudo(current_app._get_current_object(),
                           [m for r in resultados if r.status in ('ok', 'aviso') for m in r.movs if m.id])
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
    return redirect(url_for('lancar.grade', card='acessorio'))


# ------------------------------------------------------------------ um lançamento: ver, completar, corrigir, desfazer
@lancar_bp.route('/lancamento/<int:num>', methods=['GET', 'POST'])
@exige('ver')
def lancamento(num):
    from flask import abort
    from app.auth import pode
    from app.models import Movimentacao
    from app.pendencias import EDITAVEIS, desfazer, editar, pode_desfazer, texto
    m = db.session.get(Movimentacao, num) or abort(404)
    if request.method == 'POST':
        if not pode('lancar'):
            abort(403)
        if request.form.get('acao') == 'desfazer':
            if not pode_desfazer(m):
                flash('Só dá para desfazer o último lançamento do item. Para este, lance a ação inversa.', 'danger')
                return redirect(url_for('lancar.lancamento', num=num))
            alvo = m.item or m.linha
            desfazer(m)
            registrar_log('lançamento desfeito', f'Nº {num} ({m.tipo} de {alvo})')
            flash(f'Lançamento Nº {num} desfeito.', 'success')
            return redirect(url_for('consulta.item', codigo=m.item) if m.item else url_for('painel.inicio'))
        mudou = editar(m, {k: request.form.get(k) for k, _r, _t in EDITAVEIS if k in request.form}, g.usuario.nome)
        if mudou:
            registrar_log('lançamento corrigido', f'Nº {num}: ' + '; '.join(mudou))
            from flask import current_app
            from app import servicedesk as sd
            if any(x.startswith('Nº do chamado') for x in mudou) and m.chamado and sd.configurado():
                ids = sd.enfileirar([m])
                if ids:
                    sd.processar(current_app._get_current_object(), ids)
        flash('Corrigido: ' + '; '.join(mudou) if mudou else 'Nada mudou.', 'success')
        return redirect(url_for('lancar.lancamento', num=num))
    it = db.session.get(Item, m.item) if m.item else None
    return render_template('lancamento.html', m=m, it=it, pend=texto(m, it), editaveis=EDITAVEIS,
                           pode_desfazer=pode_desfazer(m), **_listas())
