"""Estoque: consumíveis (catálogo, saldo por site, movimentos e contagem) e cadastro de item novo.
Regras iguais às da aba Lançar Estoque da planilha."""
import re
from collections import defaultdict
from datetime import date, datetime

from app import db
from app.models import Compra, Consumivel, Item, MovConsumivel, Movimentacao
from app.regras import tocar

MOVIMENTOS = ['Entrada', 'Saída', 'Contagem de inventário']


def imei_ok(x):
    """15 dígitos com dígito verificador Luhn."""
    x = (x or '').strip()
    if not re.fullmatch(r'\d{15}', x):
        return False
    s = 0
    for i, ch in enumerate(x):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d = d // 10 + d % 10
        s += d
    return s % 10 == 0


def saldos():
    """{consumível: {site: saldo}}"""
    r = defaultdict(lambda: defaultdict(int))
    for nome, site, mov, q in db.session.query(MovConsumivel.consumivel, MovConsumivel.site, MovConsumivel.movimento,
                                               MovConsumivel.qtd):
        q = q or 0
        r[nome][site or '?'] += q if mov == 'Entrada' else (-q if mov == 'Saída' else q)
    return r


def saldo_site(nome, site):
    return saldos().get(nome, {}).get(site, 0)


def falta_receber(cp):
    c = Compra.query.filter_by(compra=cp).first()
    if not c:
        return None, None
    rec = Item.query.filter_by(pedido=cp).count()
    rec += sum(m.qtd or 0 for m in MovConsumivel.query.filter_by(compra=cp, movimento='Entrada'))
    return c, (c.qtd or 0) - rec


def mover(d, resp):
    """d: consumivel, movimento, site, qtd, data, destino, chamado, compra, obs → (ok, msg)"""
    cs, mv, site = d.get('consumivel'), d.get('movimento'), d.get('site')
    if not cs:
        return False, 'Escolha o consumível'
    if not Consumivel.query.filter_by(nome=cs).first():
        return False, 'Esse consumível não está no catálogo: cadastre (Item e Marca)'
    if mv not in MOVIMENTOS:
        return False, 'Escolha o Movimento'
    if not site:
        return False, 'Escolha o Site'
    try:
        qt = int(d.get('qtd'))
    except (TypeError, ValueError):
        return False, 'Informe a quantidade'
    hoje = date.today().isoformat()
    data = d.get('data') or hoje
    if data > hoje:
        return False, 'Data no futuro'
    sal = saldo_site(cs, site)
    if mv != 'Contagem de inventário' and qt <= 0:
        return False, 'A quantidade precisa ser maior que zero'
    if qt < 0:
        return False, 'Contagem não pode ser negativa'
    if mv == 'Saída' and qt > sal:
        return False, f'Saldo insuficiente em {site}: tem {sal}'
    if mv == 'Contagem de inventário' and qt == sal:
        return False, 'Contagem igual ao saldo do sistema: nada a ajustar'
    aviso = ''
    cp = d.get('compra') or ''
    if cp:
        c, falta = falta_receber(cp)
        if not c:
            return False, 'Compra não encontrada'
        if mv != 'Entrada':
            return False, 'Compra só vale para Entrada'
        if c.status == 'Cancelado':
            return False, 'Essa compra está cancelada'
        if qt > falta:
            aviso = ' (aviso: chegou mais do que faltava receber nessa compra)'
    obs = d.get('obs') or ''
    if mv == 'Contagem de inventário':
        obs = f'Contagem: contou {qt}, sistema tinha {sal}' + (f'; {obs}' if obs else '')
        mov, q = 'Ajuste', qt - sal
    else:
        mov, q = mv, qt
    db.session.add(MovConsumivel(data=data, consumivel=cs, site=site, movimento=mov, qtd=q, destino=d.get('destino') or None,
                                 chamado=d.get('chamado') or None, compra=cp or None, resp=resp, obs=obs or None))
    db.session.commit()
    novo = sal + (q if mov != 'Saída' else -q)
    return True, f'{mov} de {q:+d} · {cs} em {site}: saldo {novo}{aviso}'


def cadastrar_consumivel(item, marca, compativel, minimo):
    item, marca = (item or '').strip(), (marca or '').strip()
    if not item or not marca:
        return False, 'Informe Item e Marca'
    nome = f'{item} – {marca}'
    if Consumivel.query.filter(db.func.lower(Consumivel.nome) == nome.lower()).first():
        return False, f'{nome} já está no catálogo'
    db.session.add(Consumivel(nome=nome, item=item, marca=marca, compativel=compativel or None,
                              minimo=int(minimo) if (minimo or '').isdigit() else None))
    db.session.commit()
    return True, f'{nome} cadastrado no catálogo'


CAMPOS_ITEM = [('codigo', 'Código (plaqueta; sem plaqueta, a tag; celular, o IMEI)'), ('categoria', 'Categoria'),
               ('fabricante', 'Fabricante'), ('modelo', 'Modelo'), ('plaqueta', 'Plaqueta'), ('tag', 'Service tag / serial'),
               ('hostname', 'Hostname'), ('imei1', 'IMEI 1'), ('imei2', 'IMEI 2'), ('eid', 'EID'),
               ('propriedade', 'Propriedade (vazio = Próprio)'), ('fornecedor', 'Fornecedor / Locadora'),
               ('finalidade', 'Finalidade'), ('compativel', 'Compatível com'), ('site', 'Site'), ('nf', 'NF de compra'),
               ('data_nf', 'Data NF'), ('valor', 'Valor (R$)'), ('garantia', 'Fim da garantia'),
               ('pedido', 'Compra CP-… (se veio de compra)'), ('obs', 'Observação')]


def conferir_item(d):
    """Devolve (status, msg) com status ok/aviso/erro."""
    cod = (d.get('codigo') or '').strip()
    if not cod:
        return 'erro', 'Informe o Código'
    if db.session.get(Item, cod):
        return 'erro', 'Esse código já existe em Itens'
    if not d.get('categoria'):
        return 'erro', 'Escolha a Categoria'
    if not d.get('modelo'):
        return 'erro', 'Preencha o Modelo (vai no termo)'
    if d['categoria'] == 'Celular' and not d.get('imei1'):
        return 'erro', 'Celular precisa do IMEI 1'
    if d.get('imei1') and not imei_ok(d['imei1']):
        return 'erro', 'IMEI 1 inválido: precisa ter 15 dígitos e o dígito verificador certo (confira a digitação)'
    if d.get('imei2') and not imei_ok(d['imei2']):
        return 'erro', 'IMEI 2 inválido: precisa ter 15 dígitos e o dígito verificador certo'
    if d['categoria'] == 'Celular' and cod != d.get('imei1'):
        return 'erro', 'Para celular, o Código é o próprio IMEI 1'
    if d.get('data_nf') and d['data_nf'] > date.today().isoformat():
        return 'erro', 'Data da NF no futuro'
    if d.get('tag'):
        x = Item.query.filter_by(tag=d['tag'].upper()).first() or Item.query.filter_by(tag=d['tag']).first()
        if x:
            return 'erro', f'Essa service tag já está cadastrada no item {x.codigo}'
    if d.get('imei1') and Item.query.filter((Item.imei1 == d['imei1']) | (Item.imei2 == d['imei1'])).first():
        return 'erro', 'Esse IMEI já está cadastrado'
    if d.get('plaqueta') and Item.query.filter_by(plaqueta=d['plaqueta']).first():
        return 'erro', 'Essa plaqueta já está cadastrada'
    if d.get('pedido') and not Compra.query.filter_by(compra=d['pedido']).first():
        return 'erro', 'Compra não encontrada'
    if d.get('valor'):
        try:
            float(str(d['valor']).replace('.', '').replace(',', '.'))
        except ValueError:
            return 'erro', 'Valor inválido'
    if d.get('propriedade', 'Próprio') in ('', 'Próprio') and d.get('fornecedor'):
        return 'aviso', 'OK, com aviso: tem Fornecedor/Locadora mas está como Próprio. Se for locado (ex.: BTB), escolha Locado'
    return 'ok', 'OK'


def cadastrar_item(d, resp):
    st, msg = conferir_item(d)
    if st == 'erro':
        return False, msg
    v = {k: (d.get(k) or '').strip() or None for k, _r in CAMPOS_ITEM}
    if v['tag']:
        v['tag'] = v['tag'].upper()
    if v['valor']:
        v['valor'] = float(v['valor'].replace('.', '').replace(',', '.'))
    v['propriedade'] = v['propriedade'] or 'Próprio'
    v['finalidade'] = v['finalidade'] or 'Uso definitivo'
    v['origem'] = 'Cadastro no Zelo'
    it = Item(**v)
    db.session.add(it)
    db.session.add(Movimentacao(data=date.today().isoformat(), tipo='Entrada', item=it.codigo, resp=resp,
                                obs='Item novo' + (f' (compra {v["pedido"]})' if v['pedido'] else ''),
                                reg_em=datetime.now().isoformat(timespec='seconds')))
    db.session.flush()
    tocar([it.codigo])
    db.session.commit()
    return True, f'{it.codigo} cadastrado e em estoque' + (f' · {msg}' if st == 'aviso' else '')
