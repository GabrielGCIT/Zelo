"""Importação da planilha "Gestão de Ativos de TI" (modelo atual, com as tabelas tHist, tItens...).

Uso: python manage.py importar <planilha.xlsx> [--substituir]

A planilha é lida com os valores salvos pelo Excel (data_only): as colunas
calculadas (Situação, Com quem...) servem para CONFERIR o recálculo do Zelo,
não são importadas — no Zelo elas saem das mesmas regras, a partir do Histórico.
"""
import datetime as dt
import re

from openpyxl import load_workbook

from app import db
from app.models import (Compra, Consumivel, Contrato, EmprestimoAcessorio, Item, Linha, Manutencao,
                        MovConsumivel, Movimentacao, Pessoa)

H_COLS = {'Data': 'data', 'Tipo': 'tipo', 'Item': 'item', 'Linha': 'linha', 'Matrícula / ID': 'matricula',
          'Nome': 'nome', 'Centro de custo': 'cc', 'Local de uso': 'local', 'Etapa': 'etapa', 'Termo': 'termo',
          'Data assinatura': 'data_ass', 'Nº chamado': 'chamado', 'Data entrega': 'data_ent',
          'Prazo devolução': 'prazo', 'Motivo': 'motivo', 'B.O.': 'bo', 'Responsável': 'resp', 'Técnico': 'tecnico',
          'Observação': 'obs', 'Acessórios': 'acess', 'Fonte devolvida': 'fonte_dev', 'Mouse devolvido': 'mouse_dev',
          'Teclado devolvido': 'teclado_dev', 'Estado': 'estado', 'Recebido por': 'receb_por',
          'Link do termo': 'link', 'Registrado em': 'reg_em', 'Lote': 'lote'}
I_COLS = {'Código': 'codigo', 'Categoria': 'categoria', 'Fabricante': 'fabricante', 'Modelo': 'modelo',
          'Plaqueta': 'plaqueta', 'Service tag': 'tag', 'Hostname': 'hostname', 'IMEI 1': 'imei1', 'IMEI 2': 'imei2',
          'EID': 'eid', 'Propriedade': 'propriedade', 'Fornecedor / Locadora': 'fornecedor',
          'Finalidade': 'finalidade', 'Compatível com': 'compativel', 'Área / Departamento': 'area', 'CC': 'cc',
          'Site': 'site', 'Ativo JDE': 'ativo_jde', 'NF de compra': 'nf', 'Data NF': 'data_nf', 'Valor (R$)': 'valor',
          'CAPEX/OPEX': 'capex', 'Fim da garantia': 'garantia', 'Pedido de compra': 'pedido',
          'Fonte (série)': 'fonte', 'Teclado/mouse (série)': 'teclado', 'Contrato': 'contrato',
          'Origem do cadastro': 'origem', 'Observação': 'obs'}
LN_COLS = {'Número': 'numero', 'Operadora': 'operadora', 'Regional': 'regional', 'Tipo de chip': 'tipo_chip',
           'ICCID': 'iccid', 'CC': 'cc', 'Plano': 'plano', 'Observação': 'obs'}
P_COLS = {'ID': 'id', 'Nome': 'nome', 'Tipo': 'tipo', 'Empresa': 'empresa', 'CPF': 'cpf', 'Cadastro JDE': 'jde',
          'CC': 'cc', 'Cargo': 'cargo', 'Site': 'site', 'User': 'user', 'E-mail': 'email', 'Situação': 'situacao',
          'Observação': 'obs'}
M_COLS = {'Item': 'item', 'Defeito': 'defeito', 'Abertura': 'abertura', 'Nº chamado': 'chamado',
          'Fornecedor': 'fornecedor', 'Nº caso fornecedor': 'caso', 'Status': 'status', 'Visita agendada': 'visita',
          'Site': 'site', 'Técnico MB': 'tecnico', 'Enviado em': 'enviado', 'Retornou em': 'retorno',
          'O que foi feito': 'solucao', 'Peças': 'pecas', 'Custo (R$)': 'custo', 'Item substituto': 'substituto',
          'Observação': 'obs'}
CP_COLS = {'Compra': 'compra', 'Data pedido': 'data_pedido', 'Tarefa SD': 'tarefa', 'Solicitante': 'solicitante',
           'Categoria': 'categoria', 'Descrição': 'descricao', 'Qtd': 'qtd', 'Status': 'status',
           'Previsão entrega': 'previsao', 'Nº pedido': 'pedido', 'PO': 'po', 'CC': 'cc', 'Conta contábil': 'conta',
           'Aprovador': 'aprovador', 'CAPEX/OPEX': 'capex', 'Valor unit. (R$)': 'valor_unit', 'NF': 'nf',
           'Data NF': 'data_nf', 'Recebido em': 'recebido', 'Observação': 'obs'}
C_COLS = {'Consumível': 'nome', 'Item': 'item', 'Marca': 'marca', 'Compatível com': 'compativel',
          'Estoque mínimo': 'minimo'}
MC_COLS = {'Data': 'data', 'Consumível': 'consumivel', 'Site': 'site', 'Movimento': 'movimento', 'Quantidade': 'qtd',
           'Para quem / destino': 'destino', 'Nº chamado': 'chamado', 'Compra': 'compra', 'Responsável': 'resp',
           'Observação': 'obs'}
EA_COLS = {'Data': 'data', 'Acessório': 'consumivel', 'Qtd': 'qtd', 'Matrícula / ID': 'matricula', 'Nome': 'nome',
           'Centro de custo': 'cc', 'Prazo devolução': 'prazo', 'Nº chamado': 'chamado', 'Responsável': 'resp',
           'Observação': 'obs', 'Devolvido em': 'devolvido', 'Recebido por': 'receb', 'Obs. devolução': 'obs_dev'}
CT_COLS = {'Contrato': 'contrato', 'Locadora': 'locadora', 'Descrição': 'descricao', 'Início': 'inicio',
           'Fim': 'fim', 'Padrão da locadora': 'padrao', 'Valor mensal (R$)': 'valor', 'Observação': 'obs'}

NUMERICOS = {'valor', 'custo', 'valor_unit'}
INTEIROS = {'qtd', 'minimo'}


def _valor(chave, v):
    if v is None:
        return None
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime('%Y-%m-%d')
    if chave in NUMERICOS:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if chave in INTEIROS:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if s.startswith('='):
        return None
    return s or None


def ler_tabela(wb, aba, tabela, cols, calculadas=()):
    """Linhas da tabela como dicts {chave: valor}; `calculadas` traz também colunas calculadas (para conferência)."""
    if aba not in wb.sheetnames or tabela not in wb[aba].tables:
        return []
    ws = wb[aba]
    ref = ws.tables[tabela].ref
    c1, c2 = ref.split(':')
    r1, r2 = int(re.sub(r'\D', '', c1)), int(re.sub(r'\D', '', c2))
    hdr = [ws.cell(r1, j).value for j in range(1, ws.max_column + 1)]
    out = []
    for row in ws.iter_rows(min_row=r1 + 1, max_row=r2, values_only=True):
        d = {}
        for h, v in zip(hdr, row):
            if h in cols:
                d[cols[h]] = _valor(cols[h], v)
            elif h in calculadas:
                d['_' + h] = v
        out.append(d)
    return out


def importar(caminho, substituir=False, log=print):
    wb = load_workbook(caminho, data_only=True, read_only=False)
    if Movimentacao.query.count() and not substituir:
        raise SystemExit('O banco já tem dados. Use --substituir para apagar e importar de novo.')
    for M in (MovConsumivel, EmprestimoAcessorio, Movimentacao, Manutencao, Item, Linha, Pessoa, Consumivel,
              Compra, Contrato):
        M.query.delete()
    db.session.commit()

    pessoas = ler_tabela(wb, 'Pessoas', 'tPessoas', P_COLS)
    vistos = set()
    for p in pessoas:
        if not p.get('id') or not p.get('nome') or p['id'] in vistos:
            continue
        vistos.add(p['id'])
        p['situacao'] = p.get('situacao') or 'Ativo'
        db.session.add(Pessoa(**p))

    itens = ler_tabela(wb, 'Itens', 'tItens', I_COLS, calculadas=('Situação',))
    conferir = {}
    vistos = set()
    for i in itens:
        if not i.get('codigo') or i['codigo'] in vistos:
            continue
        vistos.add(i['codigo'])
        conferir[i['codigo']] = i.pop('_Situação', None)
        db.session.add(Item(**i))

    linhas = ler_tabela(wb, 'Linhas', 'tLinhas', LN_COLS, calculadas=('Situação',))
    conf_l = {}
    vistos = set()
    for ln in linhas:
        n = re.sub(r'\D', '', str(ln.get('numero') or ''))
        if len(n) != 11 or n in vistos:
            continue
        vistos.add(n)
        ln['numero'] = n
        conf_l[n] = ln.pop('_Situação', None)
        db.session.add(Linha(**ln))

    hist = ler_tabela(wb, 'Histórico', 'tHist', H_COLS)
    n = 0
    for k, h in enumerate(hist, 1):
        if not h.get('tipo'):
            continue
        if h.get('linha'):
            h['linha'] = re.sub(r'\D', '', h['linha'])[-11:] or None
        db.session.add(Movimentacao(id=k, **h))
        n += 1

    manut = [m for m in ler_tabela(wb, 'Manutenção', 'tManut', M_COLS) if m.get('item')]
    for k, m in enumerate(manut, 1):
        db.session.add(Manutencao(id=k, **m))

    for c in ler_tabela(wb, 'Consumíveis', 'tCat', C_COLS):
        if c.get('item'):
            c['nome'] = c.get('nome') or (f"{c['item']} – {c['marca']}" if c.get('marca') else c['item'])
            if not Consumivel.query.filter_by(nome=c['nome']).first():
                db.session.add(Consumivel(**c))
                db.session.flush()
    for m in ler_tabela(wb, 'Mov. consumíveis', 'tMovCons', MC_COLS):
        if m.get('consumivel'):
            db.session.add(MovConsumivel(**m))
    for k, e in enumerate([e for e in ler_tabela(wb, 'Acessórios emprestados', 'tEmpAc', EA_COLS) if e.get('data')], 1):
        db.session.add(EmprestimoAcessorio(id=k, **e))
    for c in ler_tabela(wb, 'Compras', 'tCompras', CP_COLS):
        if c.get('compra') or c.get('descricao'):
            db.session.add(Compra(**c))
    for c in ler_tabela(wb, 'Contratos', 'tContratos', CT_COLS):
        if c.get('contrato'):
            db.session.add(Contrato(**c))
    db.session.commit()

    from app.regras import recalcular_tudo
    recalcular_tudo()

    # conferência: situação recalculada pelo Zelo x a que o Excel tinha salvo
    div_i = [(c, s, db.session.get(Item, c).situacao) for c, s in conferir.items()
             if s and db.session.get(Item, c).situacao != s]
    div_l = [(c, s, db.session.get(Linha, c).situacao) for c, s in conf_l.items()
             if s and db.session.get(Linha, c).situacao != s]
    log(f'Importado: {Pessoa.query.count()} pessoas, {Item.query.count()} itens, {Linha.query.count()} linhas, '
        f'{n} movimentações, {Manutencao.query.count()} manutenções, {Consumivel.query.count()} consumíveis, '
        f'{MovConsumivel.query.count()} mov. de consumíveis, {Compra.query.count()} compras.')
    log(f'Conferência com a planilha: {len(div_i)} itens e {len(div_l)} linhas com situação diferente.')
    for d in (div_i + div_l)[:30]:
        log('  divergência:', d)
    return div_i, div_l
