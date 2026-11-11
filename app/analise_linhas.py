"""Conferência das linhas: relatório da Easy Team × cadastro do Zelo × relatório do AirWatch.

Mesma análise feita à mão em 11/11/2026:
- Bloquear: sem consumo nos 2 últimos meses E fora do AirWatch (ou sem acesso há mais de 30 dias);
- Validar com a Easy (ligar): tem consumo, mas nenhum aparelho do AirWatch confirma a linha, ou o Zelo diz livre/não tem;
- OK – ajustar cadastro: ativa no AirWatch, mas em aparelho/pessoa diferente do cadastro;
- OK: ativa no AirWatch, no aparelho que o cadastro registra. iPads kiosk ficam OK (uso sazonal).
"""
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

import openpyxl

from app import db
from app.models import AnaliseLinha, Item, Linha

ORDEM = ['Bloquear', 'Validar com a Easy (ligar)', 'OK – ajustar cadastro', 'OK']
CRITERIO = {
    'Bloquear': 'Sem consumo nos 2 últimos meses e fora do AirWatch (ou sem acesso há mais de 30 dias). Ninguém usa a linha.',
    'Validar com a Easy (ligar)': 'Tem consumo, mas nenhum aparelho do AirWatch confirma a linha, ou o cadastro diz livre/não tem a linha. A Easy liga e registra quem atende.',
    'OK – ajustar cadastro': 'Ativa no AirWatch, mas em aparelho/pessoa diferente do cadastro. Está em uso; só corrigir o cadastro.',
    'OK': 'Ativa no AirWatch, no aparelho que o cadastro registra. Se o nome na Easy estiver diferente, só atualizar lá.',
}
COD_POSTO = re.compile(r'^[A-Z]{2,4}CTRN\d+$')
VAZIO = {'', 'ATUALIZAR', 'LIVRE', 'DISPONIVEL', 'ESTOQUE', 'LINHAS NOVAS'}


def num(s):
    return re.sub(r'\D', '', str(s or ''))[-11:]


def palavras(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'[^A-Z0-9 ]', ' ', s).split()


def _ultimo_acesso(v):
    """O AirWatch exporta MM/DD/AAAA; quando o Excel converteu em data, dia e mês vieram trocados."""
    if isinstance(v, datetime):
        if v.day > 12:
            return v
        trocado = datetime(v.year, v.day, v.month, v.hour, v.minute)
        return v if trocado > datetime.now() else trocado
    t = str(v or '').strip()
    for f in ('%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(t, f)
        except ValueError:
            pass
    return None


def _tabela(ws, obrig):
    """Acha a linha de cabeçalho que tem todas as colunas obrigatórias e devolve a lista de dicionários."""
    linhas = list(ws.iter_rows(values_only=True))
    for i, r in enumerate(linhas[:15]):
        cab = [str(c or '').strip().upper() for c in r]
        if all(o in cab for o in obrig):
            return [dict(zip(cab, x)) for x in linhas[i + 1:] if any(x)]
    return None


def ler_easy(arq):
    wb = openpyxl.load_workbook(arq, read_only=True, data_only=True)
    for ws in wb.worksheets:
        t = _tabela(ws, ['Nº ORIGEM', 'USUÁRIO'])
        if t is not None:
            out = []
            for r in t:
                k = num(r.get('Nº ORIGEM'))
                if len(k) == 11:
                    sc = next((v for c, v in r.items() if c.startswith('SEM CONSUMO')), None)
                    out.append(dict(numero=k, conta=str(r.get('CONTA') or '').strip(), operadora=str(r.get('OPERADORA') or '').strip(),
                                    usuario=str(r.get('USUÁRIO') or '').strip(), cc=str(r.get('CENTRO DE CUSTO') or '').strip(),
                                    sem_consumo=bool(str(sc or '').strip())))
            return out
    raise ValueError('Não achei as colunas "Nº ORIGEM" e "USUÁRIO" no arquivo da Easy')


def ler_airwatch(arq):
    wb = openpyxl.load_workbook(arq, read_only=True, data_only=True)
    t = _tabela(wb.worksheets[0], ['LAST SEEN', 'PHONE', 'IMEI'])
    if t is None:
        raise ValueError('Não achei as colunas "Last Seen", "Phone" e "IMEI" no relatório do AirWatch')
    aw = defaultdict(list)
    for a in t:
        p = num(a.get('PHONE'))
        ls = _ultimo_acesso(a.get('LAST SEEN'))
        if len(p) == 11 and ls:
            aw[p].append(dict(ls=ls, imei=re.sub(r'\D', '', str(a.get('IMEI') or '')), serial=str(a.get('SERIAL NUMBER') or '').upper(),
                              usuario=a.get('DISPLAY NAME') or a.get('USERNAME') or '', modelo=a.get('MODEL') or ''))
    return aw


def analisar(easy, aw, ref=None):
    """easy: lista de ler_easy; aw: dict de ler_airwatch. Devolve lista de dicionários (uma por linha da Easy)."""
    ref = ref or max((a['ls'] for v in aw.values() for a in v), default=datetime.now())
    L = {ln.numero: ln for ln in Linha.query}
    ident, da_linha = {}, {}
    for it in Item.query.filter(Item.situacao != 'Baixada'):
        for v in (it.codigo, it.imei1, it.imei2, it.tag):
            v = re.sub(r'\s', '', str(v or '')).upper()
            if len(v) >= 6:
                ident[v] = it
        if it.linha_atual and len(num(it.linha_atual)) == 11:
            da_linha[num(it.linha_atual)] = it.codigo
    for ln in L.values():
        if ln.aparelho and ln.numero not in da_linha:
            da_linha[ln.numero] = ln.aparelho
    out = []
    for e in easy:
        k, u = e['numero'], e['usuario']
        uu = ' '.join(palavras(u))
        ln = L.get(k)
        s = ln.situacao if ln else 'Não cadastrada'
        q = (ln.com_quem or '').strip() if ln else ''
        if not ln:
            un = 'não consta no Zelo'
        elif s != 'Em uso':
            un = 'livre no Zelo' if uu not in VAZIO else 'livre nos dois'
        elif uu in VAZIO:
            un = 'Easy sem usuário'
        elif set(palavras(u)) & set(palavras(q)):
            un = 'mesmo usuário'
        elif COD_POSTO.match(u.replace(' ', '').upper()):
            un = 'posto (Easy) × motorista (Zelo)'
        else:
            un = 'usuário diferente'
        devs = sorted(aw.get(k, []), key=lambda a: a['ls'], reverse=True)
        awd = awu = ap = mod = ''
        ativo, dias = False, None
        if devs:
            a = devs[0]
            dias = (ref - a['ls']).days
            mb = da_linha.get(k, '')
            it = ident.get(a['imei']) or ident.get(a['serial'])
            cod = it.codigo if it else ''
            awd, awu, mod = a['ls'].strftime('%d/%m/%Y'), a['usuario'], a['modelo']
            if cod and cod == mb:
                ap = 'aparelho confere'
            elif not cod:
                ap = f'IMEI {a["imei"]} não cadastrado no Zelo'
            elif mb:
                ap = f'em outro aparelho ({cod})'
            else:
                ap = f'aparelho {cod} (Zelo sem aparelho na linha)'
            ativo = dias <= 30
            if len(devs) > 1:
                ap += f' · {len(devs)} aparelhos com essa linha'
        sc = e['sem_consumo']
        if 'IPAD KIOSK' in u.upper():
            dec, mot, ac = 'OK', 'iPad kiosk de pesquisa de clima: uso sazonal, fica fora do AirWatch e pode ficar sem consumo', 'Nenhuma (manter ativa)'
        elif devs and ativo:
            if ap.startswith('aparelho confere') and s == 'Em uso':
                dec, mot = 'OK', 'Linha ativa no AirWatch, no aparelho que o cadastro registra'
                ac = 'Nenhuma' if un in ('mesmo usuário', 'posto (Easy) × motorista (Zelo)') else f'Atualizar usuário na Easy para "{q}"'
                if sc:
                    mot += '; sem consumo de voz/dados na Easy (provável uso só em Wi-Fi)'
            else:
                dec, mot = 'OK – ajustar cadastro', f'Linha ativa no AirWatch ({ap})' + ('; o Zelo diz livre' if s == 'Livre' else '')
                ac = 'Corrigir no Zelo qual aparelho/pessoa está com a linha' + (
                    '' if un in ('mesmo usuário', 'posto (Easy) × motorista (Zelo)') else '; depois atualizar a Easy')
        elif sc:
            dec = 'Bloquear'
            if s != 'Em uso':
                mot, ac = 'Sem consumo há 2 meses, fora do AirWatch e livre/sem registro no Zelo', 'Pedir bloqueio (e cancelamento se seguir sem uso)'
            else:
                mot = f'Sem consumo há 2 meses e fora do AirWatch{" (último acesso " + awd + ")" if awd else ""}; no Zelo está com {q}'
                ac = f'Avisar {q} e pedir bloqueio; se reclamar, a linha volta'
        else:
            dec = 'Validar com a Easy (ligar)'
            if not ln:
                mot = 'Tem consumo e não existe no Zelo'
            elif s != 'Em uso':
                mot = 'Tem consumo, mas o Zelo diz livre e não aparece no AirWatch'
            elif devs:
                mot = f'Tem consumo, mas o aparelho não acessa o AirWatch desde {awd}'
            else:
                mot = f'Tem consumo, mas não aparece em nenhum aparelho do AirWatch (Zelo: {q})'
            ac = 'Ligar e registrar quem atende' + ('' if s != 'Em uso' else f' (esperado: {q})')
        visto = (f'Visto {awd}' + (f' (há {dias} dias)' if dias and dias > 30 else '')) if devs else 'Não aparece'
        out.append(dict(numero=k, operadora=e['operadora'], conta=e['conta'], usuario_easy=u, cc_easy=e['cc'], sem_consumo=sc,
                        sit_mb=s, com_quem=q, easy_x_mb=un, aw_visto=visto, aw_aparelho=ap[:120], aw_usuario=str(awu)[:150],
                        aw_modelo=str(mod)[:80], decisao=dec, motivo=mot[:300], acao=ac[:300]))
    out.sort(key=lambda x: (ORDEM.index(x['decisao']), x['sit_mb'], x['numero']))
    return out


def gravar_rodada(resultado):
    rodada = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for r in resultado:
        db.session.add(AnaliseLinha(rodada=rodada, **r))
    db.session.commit()
    return rodada, Counter(r['decisao'] for r in resultado)


def exportar(rodada, caminho):
    from openpyxl.styles import Alignment, Font, PatternFill
    rs = AnaliseLinha.query.filter_by(rodada=rodada).order_by(AnaliseLinha.id).all()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Análise'
    cab = ['Linha', 'Operadora', 'Conta', 'Usuário (Easy)', 'Centro de custo', 'Sem consumo 2 meses', 'Situação no Zelo',
           'Com quem (Zelo)', 'Easy × Zelo', 'AirWatch (último acesso)', 'Aparelho no AirWatch', 'Usuário no AirWatch',
           'Modelo', 'Decisão', 'Motivo', 'Ação', 'Quem atendeu', 'Retorno Easy']
    ws.append(cab)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='0D1628')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for r in rs:
        ws.append([r.numero, r.operadora, r.conta, r.usuario_easy, r.cc_easy, 'Sim' if r.sem_consumo else '', r.sit_mb, r.com_quem,
                   r.easy_x_mb, r.aw_visto, r.aw_aparelho, r.aw_usuario, r.aw_modelo, r.decisao, r.motivo, r.acao,
                   r.quem_atendeu, r.retorno])
    for col, w in zip('ABCDEFGHIJKLMNOPQR', (13, 9, 12, 28, 16, 10, 12, 28, 22, 20, 30, 26, 18, 22, 50, 40, 22, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = f'A1:R{len(rs) + 1}'
    wb.save(caminho)
