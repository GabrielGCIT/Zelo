"""Motor dos lançamentos: as ações da grade do Lançar, a Conferência e a gravação.

Mesmo comportamento da planilha:
- cada linha da grade é conferida antes de gravar; só as linhas OK são gravadas;
- uma ação vira um ou mais lançamentos no Histórico (Transferir = devolução + entrega);
- a entrega/reserva de notebook baixa mouse e teclado do estoque do EC (admissão leva kit);
- tudo o que um clique grava leva o mesmo número de lote, e o Desfazer apaga o lote inteiro.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app import db
from app.models import Consumivel, Item, Linha, MovConsumivel, Movimentacao, Pessoa, cfg
from app.regras import tocar

# ação → (tipo, etapa, termo padrão, pede pessoa, exige motivo)
ACOES = {
    'Entregar agora': ('Entrega', 'Entregue', 'Assinado', True, False),
    'Reservar': ('Entrega', 'Reservado', 'Pendente', True, False),
    'Emprestar': ('Empréstimo', 'Entregue', 'Pendente', True, False),
    'Transferir para outra pessoa': ('Entrega', 'Entregue', 'Assinado', True, False),
    'Renovar empréstimo': ('Empréstimo', 'Entregue', None, False, False),
    'Pedir devolução': ('Pedido de devolução', None, None, False, True),
    'Enviado ao EC': ('Envio ao EC', None, None, False, False),
    'Devolver': ('Devolução', None, None, False, False),
    'Entrada no estoque': ('Entrada', None, None, False, False),
    'Enviar para outro site': ('Transferência', None, None, False, False),
    'Desativar linha': ('Desativar linha', None, None, False, False),
    'Cancelar linha': ('Cancelar linha', None, None, False, True),
    'A localizar': ('A localizar', None, None, False, True),
    'Separar para baixa': ('Separar p/ baixa', None, None, False, True),
    'Baixar': ('Baixa', None, None, False, True),
}
ABAS = {
    'entrega': ('Entrega e devolução', ['Reservar', 'Entregar agora', 'Transferir para outra pessoa', 'Pedir devolução',
                                        'Enviado ao EC', 'Devolver']),
    'emprestimo': ('Empréstimo (pool)', ['Emprestar', 'Renovar empréstimo', 'Devolver']),
    'mobile': ('Mobile e linha', ['Entregar agora', 'Reservar', 'Transferir para outra pessoa', 'Devolver',
                                  'Desativar linha', 'Cancelar linha']),
    'estoque': ('Estoque', ['Entrada no estoque', 'Enviar para outro site', 'A localizar', 'Separar para baixa', 'Baixar']),
}
KIT_OPCOES = ['Mouse + teclado', 'Só mouse', 'Só teclado', 'Nenhum']

# ------------------------------------------------------------------ lançamento em cards
# card → (título, subtítulo, ícone, aba do motor)
CARDS = {
    'notebook': ('Notebook e desktop', 'Entregar, reservar, transferir, devolver', 'fa-laptop', 'entrega'),
    'mobile': ('Celular e linha', 'Aparelho, chip, linha avulsa', 'fa-mobile-screen-button', 'mobile'),
    'pool': ('Empréstimo do pool', 'Emprestar, renovar, devolver', 'fa-rotate', 'emprestimo'),
    'acessorio': ('Acessório', 'Fonte, mouse, headset emprestados', 'fa-plug', None),
    'estoque': ('Estoque e baixa', 'Entrada, outro site, localizar, baixar', 'fa-boxes-stacked', 'estoque'),
}
# ação → campos que a tela mostra (o resto nem aparece)
CAMPOS_ACAO = {
    'Entregar agora': ['para', 'linha', 'local', 'chamado', 'tecnico', 'termo', 'acess', 'data', 'obs'],
    'Reservar': ['para', 'linha', 'chamado', 'tecnico', 'acess', 'data', 'obs'],
    'Transferir para outra pessoa': ['para', 'chamado', 'tecnico', 'termo', 'data', 'obs'],
    'Emprestar': ['para', 'prazo', 'chamado', 'tecnico', 'data', 'obs'],
    'Renovar empréstimo': ['prazo', 'chamado', 'obs'],
    'Pedir devolução': ['motivo', 'chamado', 'obs'],
    'Enviado ao EC': ['data', 'obs'],
    'Devolver': ['receb_por', 'fica', 'chamado', 'motivo', 'data', 'obs'],
    'Entrada no estoque': ['data', 'obs'],
    'Enviar para outro site': ['destino', 'data'],
    'Desativar linha': ['motivo', 'obs'],
    'Cancelar linha': ['motivo', 'obs'],
    'A localizar': ['motivo', 'bo', 'data', 'obs'],
    'Separar para baixa': ['motivo', 'data', 'obs'],
    'Baixar': ['motivo', 'bo', 'data', 'obs'],
}
_POR_SITUACAO = {
    'Em estoque': {'Entregar agora', 'Reservar', 'Emprestar', 'Enviar para outro site', 'A localizar', 'Separar para baixa',
                   'Baixar'},
    'Sem movimentação': {'Entregar agora', 'Reservar', 'Emprestar', 'Entrada no estoque', 'Enviar para outro site',
                         'A localizar', 'Separar para baixa', 'Baixar'},
    'Em uso': {'Transferir para outra pessoa', 'Pedir devolução', 'Enviado ao EC', 'Devolver', 'A localizar',
               'Separar para baixa', 'Baixar'},
    'Emprestado': {'Renovar empréstimo', 'Devolver', 'Transferir para outra pessoa', 'Pedir devolução', 'Enviado ao EC',
                   'A localizar', 'Baixar'},
    'Reservada': {'Transferir para outra pessoa', 'Devolver'},
    'Pendente devolução': {'Enviado ao EC', 'Devolver', 'A localizar', 'Baixar'},
    'Em trânsito para o EC': {'Devolver', 'A localizar'},
    'A localizar': {'Entrada no estoque', 'Devolver', 'Baixar', 'Separar para baixa'},
    'Aguardando baixa': {'Baixar', 'Entrada no estoque'},
    'Em transferência': {'Entrada no estoque', 'Enviar para outro site', 'A localizar'},
}


def card_do_item(it):
    if it.finalidade == 'Pool de empréstimo':
        return 'pool'
    return 'mobile' if it.categoria in ('Celular', 'Tablet') else 'notebook'


def acoes_possiveis(it, ln, card):
    """Ações do card que fazem sentido para a situação atual do item (ou da linha). Devolve (ações, recado)."""
    aba = CARDS[card][3]
    todas = ABAS[aba][1]
    if it:
        sit = it.situacao or 'Sem movimentação'
        if sit in ('Devolvido', 'Em preparação'):
            return [], 'Notebook devolvido, em preparação: confira a chegada e libere em Acompanhar.'
        if sit == 'Manutenção':
            return [a for a in todas if a in ('Devolver', 'Baixar', 'A localizar')], \
                'Item em manutenção: feche a ocorrência em Manutenção para poder entregar.'
        if sit == 'Baixada':
            return [], 'Item baixado: não aceita lançamentos.'
        ok = _POR_SITUACAO.get(sit, set(todas))
        return [a for a in todas if a in ok], ''
    if ln:
        if ln.situacao == 'Em uso':
            return [a for a in todas if a in ('Devolver', 'Desativar linha', 'Cancelar linha')], ''
        return [a for a in todas if a in ('Entregar agora', 'Reservar', 'Desativar linha', 'Cancelar linha')], ''
    return [], ''

CAMPOS = ['acao', 'item', 'para', 'linha', 'termo', 'chamado', 'data', 'motivo', 'bo', 'tecnico', 'obs', 'acess',
          'prazo', 'receb_por', 'link', 'local']


@dataclass
class Resultado:
    status: str = ''          # '' (linha vazia) | 'ok' | 'aviso' | 'erro'
    msg: str = ''
    movs: list = field(default_factory=list)       # Movimentacao a gravar
    kit: list = field(default_factory=list)        # nomes de consumível a baixar no EC
    pessoa_nova: dict = None
    itens: set = field(default_factory=set)
    linhas: set = field(default_factory=set)

    def json(self):
        return {'status': self.status, 'msg': self.msg}


def so_digitos(s):
    return re.sub(r'\D', '', s or '')


def achar_item(termo):
    from app.routes.consulta import achar_item as _a
    return _a(termo)


def achar_pessoa(texto):
    """Pessoa por ID, por 'NOME · matrícula' ou pelo nome exato (único). Devolve (pessoa, nova_dict, erro)."""
    t = (texto or '').strip()
    if not t:
        return None, None, None
    m = re.match(r'^(.*?)\s*[·|-]\s*([A-Za-z]?-?\d{3,})$', t)
    if m and db.session.get(Pessoa, m.group(2).upper()):
        return db.session.get(Pessoa, m.group(2).upper()), None, None
    p = db.session.get(Pessoa, t) or db.session.get(Pessoa, t.upper())
    if p:
        return p, None, None
    iguais = Pessoa.query.filter(db.func.upper(Pessoa.nome) == t.upper()).all()
    if len(iguais) == 1:
        return iguais[0], None, None
    if len(iguais) > 1:
        return None, None, f'Há {len(iguais)} pessoas com esse nome: escolha pelo ID ({", ".join(p.id for p in iguais[:4])})'
    if m:   # NOME · matrícula de alguém que ainda não está em Pessoas → CLT nova
        return None, {'id': m.group(2).upper(), 'nome': m.group(1).strip().upper(), 'tipo': 'CLT',
                      'empresa': 'Martin Brower'}, None
    return None, {'id': None, 'nome': t.upper(), 'tipo': 'Terceiro'}, None


def proximo_id_pessoa(prefixo, reservados=()):
    nums = [int(p.id[2:]) for p in Pessoa.query.filter(Pessoa.id.like(f'{prefixo}-%')).all() if p.id[2:].isdigit()]
    nums += [int(r[2:]) for r in reservados if r.startswith(prefixo + '-')]
    return f'{prefixo}-{(max(nums) if nums else 0) + 1:04d}'


def saldo(consumivel, site='EC', descontar=None):
    q = MovConsumivel.query.filter_by(consumivel=consumivel, site=site)
    s = 0
    for m in q:
        n = m.qtd or 0
        s += n if m.movimento == 'Entrada' else (-n if m.movimento == 'Saída' else n)
    return s - (descontar or {}).get(consumivel, 0)


def escolher_kit(fab, quer_mouse, quer_teclado, ja_usado):
    """Mesma escolha da planilha: kit teclado+mouse da marca; senão mouse/teclado avulsos; senão outra marca com saldo."""
    if not (quer_mouse or quer_teclado):
        return [], None
    fab = fab or 'Dell'

    def tem(nome):
        return Consumivel.query.filter_by(nome=nome).first() and saldo(nome, 'EC', ja_usado) > 0

    def outra(base):
        for c in Consumivel.query.filter(Consumivel.nome.like(f'{base} – %')).all():
            if saldo(c.nome, 'EC', ja_usado) > 0:
                return c.nome
        return None
    kit = f'Kit teclado + mouse sem fio – {fab}'
    if quer_mouse and quer_teclado and tem(kit):
        return [kit], None
    out = []
    for quer, base in ((quer_mouse, 'Mouse sem fio'), (quer_teclado, 'Teclado sem fio')):
        if quer:
            n = f'{base} – {fab}'
            n = n if tem(n) else outra(base)
            if not n:
                return [], f'Sem saldo de {base.split()[0].lower()} no EC: lance a entrada em Consumíveis'
            out.append(n)
    return out, None


def conferir_linha(d, aba, hoje=None, contexto=None):
    """Confere uma linha da grade. `contexto` acumula o que as linhas anteriores do mesmo clique já usam."""
    ctx = contexto if contexto is not None else {'itens': set(), 'kit': {}, 'novos': []}
    r = Resultado()
    d = {k: (str(d.get(k) or '').strip()) for k in CAMPOS}
    if not any(d[k] for k in CAMPOS if k != 'acao') and not d['acao']:
        return r
    hoje = hoje or date.today().isoformat()

    def erro(m):
        r.status, r.msg = 'erro', m
        return r
    acao = d['acao']
    if not acao:
        return erro('Escolha a Ação')
    if acao not in ACOES or (aba in ABAS and acao not in ABAS[aba][1]):
        return erro('Essa ação não é desta aba')
    tipo, etapa, termo_pad, precisa, exige_motivo = ACOES[acao]
    transf, renova = acao == 'Transferir para outra pessoa', acao == 'Renovar empréstimo'

    it = None
    if d['item']:
        it = achar_item(d['item'])
        if not it:
            return erro('Item não encontrado (plaqueta, service tag, IMEI ou código)')
        if it.codigo in ctx['itens']:
            return erro('Item repetido em outra linha da grade')
    fica = d['linha'].lower() == 'fica'
    ln = None
    if d['linha'] and not fica:
        n = so_digitos(d['linha'])
        if len(n) != 11:
            return erro('Linha precisa ter 11 dígitos (DDD + número)')
        ln = db.session.get(Linha, n)
        if not ln:
            return erro('Linha não cadastrada: cadastre em Linhas')
    if not it and not ln:
        return erro('Falta o Item ou a Linha')
    data_mov = d['data'] or hoje
    try:
        date.fromisoformat(data_mov)
    except ValueError:
        return erro('Data inválida')
    if data_mov > hoje:
        return erro('Data no futuro')

    sit = it.situacao if it else None
    pessoa, nova, perro = (None, None, None)
    if precisa:
        if not d['para'] and not d['local']:
            return erro('Falta o Para (quem recebe)')
        if d['para']:
            pessoa, nova, perro = achar_pessoa(d['para'])
            if perro:
                return erro(perro)
            if pessoa and pessoa.situacao == 'Desligado':
                return erro('Pessoa marcada como Desligada em Pessoas')
    elif d['para']:
        return erro('Deixe o Para vazio: nessa ação vale quem está com o item' + (f' ({it.com_quem})' if it and it.com_quem else ''))
    pid = pessoa.id if pessoa else (nova or {}).get('id')

    pool = it is not None and it.finalidade == 'Pool de empréstimo'
    if pool and acao in ('Entregar agora', 'Reservar', 'Transferir para outra pessoa'):
        return erro('Máquina do pool de empréstimo: use a aba Empréstimo')
    if renova and (not it or sit != 'Emprestado'):
        return erro(f'Só dá para renovar o que está Emprestado (o item está {sit or "sem item"})')
    if it and sit == 'Manutenção' and precisa:
        return erro('Item está em Manutenção: feche a ocorrência antes de entregar')
    if it and sit in ('Devolvido', 'Em preparação') and (precisa or tipo == 'Entrada'):
        return erro('Item em preparação: termine e libere em Acompanhar')
    if transf:
        if not it:
            return erro('Transferir precisa do Item')
        if sit not in ('Em uso', 'Emprestado', 'Reservada'):
            return erro(f'O item está {sit}: use Entregar agora')
        if pid and pid == it.matricula:
            return erro('O item já está com essa pessoa')
    if precisa and not transf and it and sit not in ('Em estoque', 'Sem movimentação'):
        return erro(f'Item está {sit}' + (f' com {it.com_quem}' if it.com_quem else '') + ': use Devolver ou Transferir')
    if precisa and ln and ln.situacao == 'Em uso' and ln.matricula != pid and not (transf and it and ln.aparelho == it.codigo):
        return erro(f'Linha em uso com {ln.com_quem}: devolva antes')
    if tipo == 'Pedido de devolução' and (not it or sit not in ('Em uso', 'Emprestado')):
        return erro(f'Só dá para pedir devolução de item em uso (o item está {sit or "sem item"})')
    if tipo == 'Envio ao EC' and (not it or sit not in ('Em uso', 'Emprestado', 'Pendente devolução')):
        return erro(f'Enviado ao EC vale para item em uso ou com devolução pedida (o item está {sit or "sem item"})')
    if tipo == 'Devolução':
        if it and sit in ('Em estoque', 'Baixada', 'Sem movimentação', 'Aguardando baixa', 'Devolvido', 'Em preparação'):
            return erro(f'O item já está {sit}: nada a devolver')
        if not it and ln and ln.situacao != 'Em uso':
            return erro('A linha não está em uso: nada a devolver')
    if tipo in ('Desativar linha', 'Cancelar linha') and not ln:
        return erro('Falta a Linha')
    if tipo in ('Entrada', 'Transferência', 'A localizar', 'Separar p/ baixa', 'Baixa') and not it:
        return erro('Falta o Item')
    if tipo == 'Entrada' and sit in ('Em uso', 'Emprestado', 'Reservada', 'Pendente devolução'):
        return erro(f'O item está com {it.com_quem}: use Devolver')
    if exige_motivo and not d['motivo']:
        return erro('Informe o Motivo')
    if d['motivo'].lower() == 'roubo/furto' and not d['bo']:
        return erro('Roubo/furto exige o B.O.')
    if tipo == 'Baixa' and sit == 'Baixada':
        return erro('O item já está baixado')
    if tipo == 'Transferência' and not d['obs']:
        return erro('Escreva o site de destino na Observação')
    eh_nb = it is not None and it.categoria == 'Notebook'
    kitok = precisa and tipo == 'Entrega' and not transf and eh_nb
    if d['acess'] and not kitok:
        return erro('Acessórios só na entrega/reserva de notebook: deixe vazio')
    recebe = tipo == 'Devolução' and eh_nb and not pool
    if d['receb_por'] and not recebe:
        return erro('Recebido por só na devolução de notebook: deixe vazio')
    prazo_dias = None
    if d['prazo']:
        if tipo != 'Empréstimo':
            return erro('Prazo só vale para Emprestar/Renovar: deixe vazio')
        if not d['prazo'].isdigit() or int(d['prazo']) <= 0:
            return erro('Prazo: escolha 30, 60 ou 90 dias')
        prazo_dias = int(d['prazo'])
    if tipo == 'Empréstimo':
        prazo_dias = prazo_dias or int(cfg('prazo_emprestimo') or 30)

    # kit de mouse/teclado
    kit, acess_txt, sem_kit_adm = [], None, False
    if kitok:
        nbq = Item.query.filter(Item.matricula == pid, Item.categoria == 'Notebook',
                                Item.situacao.in_(('Em uso', 'Reservada'))).count() if pid else 0
        adm = (bool(pid) and nbq == 0) or nova is not None
        acess = d['acess'] or ('Mouse + teclado' if adm and it.kit != 'Completo' else 'Nenhum')
        if acess not in KIT_OPCOES:
            return erro('Acessórios: escolha Mouse + teclado, Só mouse, Só teclado ou Nenhum')
        # Kit é sugestão, não trava: tem notebook que sai sem kit. Vazio = automático; "Nenhum" = sai sem (com aviso).
        sem_kit_adm = adm and it.kit != 'Completo' and acess == 'Nenhum'
        if it.kit != 'Completo':
            kit, falta = escolher_kit(it.fabricante, acess in ('Mouse + teclado', 'Só mouse'),
                                      acess in ('Mouse + teclado', 'Só teclado'), ctx['kit'])
            if falta:
                return erro(falta + ': dê entrada em Consumíveis ou escolha Nenhum em Acessórios')
        acess_txt = '; '.join(kit) if kit else (acess if acess != 'Nenhum' else None)

    # monta os lançamentos
    base = dict(data=data_mov, chamado=d['chamado'] or None, motivo=d['motivo'] or None, bo=d['bo'] or None,
                tecnico=d['tecnico'] or None, obs=d['obs'] or None, link=d['link'] or None)
    nome = pessoa.nome if pessoa else (nova or {}).get('nome')
    cc = pessoa.cc if pessoa else None
    linha_mov = ln.numero if ln else None
    if precisa:
        if it and not ln and not fica and it.categoria in ('Celular', 'Tablet'):
            atual = Linha.query.filter_by(aparelho=it.codigo, situacao='Em uso').first()
            linha_mov = atual.numero if atual and transf else linha_mov
        termo = d['termo'] or termo_pad
        if transf:
            r.movs.append(Movimentacao(tipo='Devolução', item=it.codigo, linha=linha_mov, matricula=it.matricula,
                                       nome=it.com_quem, obs=f'Transferido para {nome}', **{k: v for k, v in base.items()
                                                                                             if k in ('data',)}))
        prazo = (date.fromisoformat(data_mov) + timedelta(days=prazo_dias)).isoformat() if prazo_dias else None
        r.movs.append(Movimentacao(tipo=tipo, item=it.codigo if it else None, linha=linha_mov, matricula=pid, nome=nome,
                                   cc=cc, local=d['local'] or None, etapa=etapa, termo=termo,
                                   data_ass=data_mov if termo == 'Assinado' else None,
                                   data_ent=data_mov if etapa == 'Entregue' else None, prazo=prazo, acess=acess_txt,
                                   **{k: v for k, v in base.items() if k != 'obs'},
                                   obs=('Transferido de ' + (it.com_quem or '') + ('; ' + d['obs'] if d['obs'] else ''))
                                   if transf else base['obs']))
    elif renova:
        prazo = (date.fromisoformat(data_mov) + timedelta(days=prazo_dias)).isoformat()
        r.movs.append(Movimentacao(tipo='Empréstimo', item=it.codigo, matricula=it.matricula, nome=it.com_quem,
                                   etapa='Entregue', termo=it.termo or 'Pendente', prazo=prazo, data_ent=data_mov,
                                   **{k: v for k, v in base.items() if k != 'obs'},
                                   obs='Renovação do empréstimo' + ('; ' + d['obs'] if d['obs'] else '')))
    else:
        mat, nm = (it.matricula, it.com_quem) if it and it.matricula else ((ln.matricula, ln.com_quem) if ln else (None, None))
        lm = linha_mov
        if tipo in ('Devolução', 'Baixa') and it and not ln and not fica:
            atual = Linha.query.filter_by(aparelho=it.codigo, situacao='Em uso').first()
            lm = atual.numero if atual else None
        r.movs.append(Movimentacao(tipo=tipo, item=it.codigo if it else None, linha=lm if tipo not in (
            'Entrada', 'Transferência', 'A localizar', 'Separar p/ baixa', 'Pedido de devolução', 'Envio ao EC') else None,
            matricula=mat if tipo in ('Pedido de devolução', 'Envio ao EC', 'Devolução', 'Desativar linha',
                                      'Cancelar linha') else None,
            nome=nm if tipo in ('Pedido de devolução', 'Envio ao EC', 'Devolução', 'Desativar linha',
                                'Cancelar linha') else None,
            receb_por=d['receb_por'] or None, **base))

    # mensagem de resultado (igual à coluna Conferência)
    avisos = []
    if kitok and sem_kit_adm:
        avisos.append('primeiro notebook da pessoa saindo sem mouse/teclado')
    if nova:
        avisos.append(f'{nova["nome"]} será cadastrado(a) em Pessoas')
    if data_mov < (date.fromisoformat(hoje) - timedelta(days=365)).isoformat():
        avisos.append('data de mais de 1 ano')
    if acao == 'Emprestar' and it and not pool:
        avisos.append('item de uso definitivo (fora do pool)')
    m = r.movs[-1]
    if tipo == 'Entrega':
        res = (('em uso com ' if etapa == 'Entregue' else 'reservado para ') if it else f'linha {linha_mov} com ') + (nome or d['local'])
        if it and linha_mov:
            res += f' + linha {linha_mov}'
        if transf:
            res = f'sai de {it.com_quem} e fica em uso com {nome}'
    elif tipo == 'Empréstimo':
        res = f'emprestado a {m.nome} até {date.fromisoformat(m.prazo):%d/%m} ({prazo_dias} dias)'
    elif tipo == 'Devolução':
        res = ('devolvido: vai para a preparação (Acompanhar)' if recebe else 'volta ao estoque') if it else ''
        if m.linha:
            res += (' e ' if it else '') + f'linha {m.linha} fica livre'
    else:
        from app.regras import SIT_ITEM_TIPO, SIT_LINHA_TIPO
        res = (SIT_ITEM_TIPO.get(tipo) or SIT_LINHA_TIPO.get(tipo) or tipo).lower()
    if kit:
        res += ' · baixa EC: ' + '; '.join(kit)
    elif kitok and it.kit == 'Completo':
        res += ' · kit já vai junto'
    r.status = 'aviso' if avisos else 'ok'
    r.msg = ('OK, com aviso: ' + '; '.join(avisos) + ' · ' if avisos else 'OK → ') + res
    r.kit, r.pessoa_nova = kit, nova
    r.itens = {x.item for x in r.movs if x.item}
    r.linhas = {x.linha for x in r.movs if x.linha}
    ctx['itens'] |= r.itens
    for k in kit:
        ctx['kit'][k] = ctx['kit'].get(k, 0) + 1
    return r


def conferir(linhas, aba, hoje=None):
    ctx = {'itens': set(), 'kit': {}, 'novos': []}
    return [conferir_linha(d, aba, hoje, ctx) for d in linhas]


def gravar(linhas, aba, resp):
    """Confere de novo (o banco pode ter mudado desde a tela) e grava só as linhas OK num lote."""
    resultados = conferir(linhas, aba)
    lote = datetime.now().strftime('%Y%m%d%H%M%S') + '-' + re.sub(r'\W', '', resp)[:12]
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')
    gravadas, novas_ids = 0, []
    for r in resultados:
        if r.status not in ('ok', 'aviso'):
            continue
        if r.pessoa_nova:
            pn = dict(r.pessoa_nova)
            if not pn.get('id'):
                pn['id'] = proximo_id_pessoa('T', novas_ids)
            novas_ids.append(pn['id'])
            if not db.session.get(Pessoa, pn['id']):
                db.session.add(Pessoa(situacao='Ativo', obs=f'Cadastrado no lançamento (lote {lote})', **pn))
            for m in r.movs:
                if m.nome == r.pessoa_nova['nome'] and not m.matricula:
                    m.matricula = pn['id']
        for m in r.movs:
            m.resp, m.reg_em, m.lote = resp, agora, lote
            db.session.add(m)
        db.session.flush()
        for k in r.kit:
            db.session.add(MovConsumivel(data=r.movs[-1].data, consumivel=k, site='EC', movimento='Saída', qtd=1,
                                         destino=r.movs[-1].nome, resp=resp, mov_id=r.movs[-1].id, lote=lote,
                                         obs=f'Kit da entrega Nº {r.movs[-1].id}'))
        tocar(r.itens, r.linhas)
        gravadas += 1
    db.session.commit()
    return resultados, gravadas, lote


def desfazer_ultimo(resp):
    """Apaga o último lote gravado por esta pessoa (todas as linhas daquele clique)."""
    ult = (Movimentacao.query.filter(Movimentacao.resp == resp, Movimentacao.lote.isnot(None))
           .order_by(Movimentacao.id.desc()).first())
    if not ult:
        return 0, None
    lote = ult.lote
    movs = Movimentacao.query.filter_by(lote=lote).all()
    itens = {m.item for m in movs if m.item}
    linhas = {m.linha for m in movs if m.linha}
    n = len(movs)
    MovConsumivel.query.filter_by(lote=lote).delete()
    for m in movs:
        db.session.delete(m)
    db.session.flush()
    tocar(itens, linhas)
    db.session.commit()
    return n, lote
