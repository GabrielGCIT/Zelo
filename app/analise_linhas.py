"""Conferência das linhas: relatório da Easy Team × cadastro do Zelo × relatório do AirWatch.

Mesma análise feita à mão em 11/11/2026:
- Validar com a Easy (ligar): nenhum aparelho do AirWatch confirma a linha, o Zelo diz livre/não tem,
  ou está sem consumo e fora do AirWatch. **Nenhuma linha é bloqueada** (decisão de 19/11): o que era
  bloqueio virou ligação com prioridade;
- Ajustar cadastro na Easy: a linha está em uso no aparelho certo, só o nome na Easy está diferente;
- Ajustar cadastro no Zelo: ativa no AirWatch, mas em aparelho/pessoa diferente do cadastro;
- OK: ativa no AirWatch, no aparelho e na pessoa que o cadastro registra. iPads kiosk ficam OK (uso sazonal).
"""
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

import openpyxl
from openpyxl.utils import get_column_letter

from app import db
from app.models import AnaliseLinha, Item, Linha, Pessoa

VALIDAR, NA_EASY, NO_ZELO = 'Validar com a Easy (ligar)', 'Ajustar cadastro na Easy', 'Ajustar cadastro no Zelo'
ORDEM = [VALIDAR, NA_EASY, NO_ZELO, 'OK']
CRITERIO = {
    VALIDAR: 'Tem consumo mas nenhum aparelho do AirWatch confirma a linha, o cadastro diz livre/não tem a linha, '
             'ou está sem consumo e fora do AirWatch. A Easy liga e registra quem atende. Nenhuma linha é bloqueada antes disso.',
    NA_EASY: 'A linha está em uso e o cadastro sabe com quem. O nome na Easy é que está diferente ou com a grafia errada. '
             'Conserto na Easy, sem ligar para ninguém.',
    NO_ZELO: 'Ativa no AirWatch, mas em aparelho/pessoa diferente do cadastro. Está em uso; o cadastro é que precisa ser corrigido.',
    'OK': 'Ativa no AirWatch, no aparelho e na pessoa que o cadastro registra. Nenhuma ação.',
}
COD_POSTO = re.compile(r'^[A-Z]{2,4}CTRN\d+$')
VAZIO = {'', 'ATUALIZAR', 'LIVRE', 'DISPONIVEL', 'ESTOQUE', 'LINHAS NOVAS'}


def num(s):
    return re.sub(r'\D', '', str(s or ''))[-11:]


def mesmo_nome(a, b):
    """Mesma pessoa a menos de acento, caixa e pontuação.

    Antes bastava UMA palavra em comum, e um "DE" fazia RICARDO DE JESUS casar com JERONIMO DE LIMA
    SILVA: 45 erros na conferência de 19/11, todos escondidos atrás de um "mesmo usuário" que não
    era. Agora exige o nome inteiro, ou que um contenha o outro com pelo menos duas palavras
    (PLANTÃO ADM TRANSPORTE CARJ x PLANTÃO ADM TRANSPORTE), ou primeiro e último nome iguais, que é
    o caso de nome do meio abreviado.
    """
    pa, pb = palavras(a), palavras(b)
    if not pa or not pb:
        return False
    ja, jb = ' '.join(pa), ' '.join(pb)
    if ja == jb:
        return True
    if min(len(pa), len(pb)) >= 2 and (ja in jb or jb in ja):
        return True
    return len(pa) >= 2 and len(pb) >= 2 and pa[0] == pb[0] and pa[-1] == pb[-1]


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
        elif mesmo_nome(u, q):
            # mesma pessoa, escrita diferente: quem gerencia a conta precisa saber que é só grafia,
            # senão liga para um telefone de plantão para descobrir que falta um acento
            un = 'mesmo usuário' if ' '.join(palavras(u)) == ' '.join(palavras(q)) else 'mesmo usuário (grafia diferente na Easy)'
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
            confere = un in ('mesmo usuário', 'posto (Easy) × motorista (Zelo)')
            if ap.startswith('aparelho confere') and s == 'Em uso':
                mot = 'Linha ativa no AirWatch, no aparelho que o cadastro registra'
                if sc:
                    mot += '; sem consumo de voz/dados na Easy (provável uso só em Wi-Fi)'
                if confere:
                    dec, ac = 'OK', 'Nenhuma'
                elif un.startswith('mesmo usuário'):
                    dec, ac = NA_EASY, f'Corrigir a grafia do usuário na Easy para "{q}"'
                else:
                    dec, ac = NA_EASY, f'Atualizar usuário na Easy para "{q}"'
            else:
                dec, mot = NO_ZELO, f'Linha ativa no AirWatch ({ap})' + ('; o Zelo diz livre' if s == 'Livre' else '')
                ac = 'Corrigir no Zelo qual aparelho/pessoa está com a linha' + (
                    '' if confere else '; depois atualizar a Easy')
        elif sc:
            # nada de bloqueio: a decisão de 19/11 é que nenhuma linha é cortada antes de alguém
            # ligar. O critério antigo do bloqueio não se perde — vira a prioridade da ligação.
            dec = VALIDAR
            prio = 'prioridade: sem consumo nos 2 últimos meses e fora do AirWatch'
            if s != 'Em uso':
                mot = 'Sem consumo há 2 meses, fora do AirWatch e livre/sem registro no Zelo'
                ac = f'Ligar e registrar quem atende ({prio})'
            else:
                mot = f'Sem consumo há 2 meses e fora do AirWatch{" (último acesso " + awd + ")" if awd else ""}; no Zelo está com {q}'
                ac = f'Ligar e registrar quem atende (esperado: {q}; {prio})'
        else:
            dec = VALIDAR
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


def contexto_da_pessoa(numeros):
    """Quem está com cada linha, com o que interessa a quem administra telefonia: vínculo e
    situação (linha no nome de quem já saiu é conta correndo à toa), cargo, área, site e CC.

    Lido na hora do relatório, não guardado em `AnaliseLinha`: o cadastro muda depois da rodada, e
    uma pessoa que foi desligada ontem tem de aparecer desligada no relatório de hoje.
    """
    ctx = {}
    for ln in Linha.query.filter(Linha.numero.in_(list(numeros))):
        p = Pessoa.query.filter_by(id=ln.matricula).first() if ln.matricula else None
        it = db.session.get(Item, ln.aparelho) if ln.aparelho else None
        aparelho = ''
        if it:
            aparelho = f'{it.modelo} · {it.codigo}' if str(it.codigo or '').isdigit() else (it.modelo or it.codigo)
        elif ln.aparelho:
            aparelho = ln.aparelho
        ctx[ln.numero] = dict(
            pessoa=f'{p.tipo or "?"} · {p.situacao or "?"}' if p else '',
            desligado=bool(p and p.situacao == 'Desligado'), nome=p.nome if p else '',
            cargo=(p.cargo if p else '') or '', area=re.sub(r'^JDE:\s*', '', (p.obs if p else '') or ''),
            site=(p.site if p else '') or '', cc=(p.cc if p else '') or '',
            regional=ln.regional or '', chip=ln.tipo_chip or '', aparelho=aparelho)
    return ctx


def exportar(rodada, caminho):
    from openpyxl.styles import Alignment, Font, PatternFill
    rs = AnaliseLinha.query.filter_by(rodada=rodada).order_by(AnaliseLinha.id).all()
    ctx = contexto_da_pessoa({r.numero for r in rs})
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Análise'
    cab = ['Linha', 'Operadora', 'Conta', 'Usuário (Easy)', 'Centro de custo', 'Sem consumo 2 meses', 'Situação no Zelo',
           'Com quem (Zelo)', 'Pessoa (Zelo)', 'Cargo', 'Área', 'Site', 'CC (Zelo)', 'Regional', 'Tipo de chip',
           'Aparelho (Zelo)', 'Easy × Zelo', 'AirWatch (último acesso)', 'Aparelho no AirWatch', 'Usuário no AirWatch',
           'Modelo', 'Decisão', 'Motivo', 'Ação', 'Atenção', 'Quem atendeu', 'Retorno Easy']
    ws.append(cab)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='0D1628')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for r in rs:
        x = ctx.get(r.numero, {})
        aviso = []
        if x.get('desligado'):
            aviso.append(f'Pessoa desligada no cadastro ({x.get("nome")})')
        if r.sit_mb == 'Não cadastrada':
            aviso.append('Linha não existe no cadastro')
        if r.sem_consumo and r.decisao != VALIDAR:
            aviso.append('Sem consumo nos 2 últimos meses')
        ws.append([r.numero, r.operadora, r.conta, r.usuario_easy, r.cc_easy, 'Sim' if r.sem_consumo else '', r.sit_mb, r.com_quem,
                   x.get('pessoa', ''), x.get('cargo', ''), x.get('area', ''), x.get('site', ''), x.get('cc', ''),
                   x.get('regional', ''), x.get('chip', ''), x.get('aparelho', ''),
                   r.easy_x_mb, r.aw_visto, r.aw_aparelho, r.aw_usuario, r.aw_modelo, r.decisao, r.motivo, r.acao,
                   ' · '.join(aviso), r.quem_atendeu, r.retorno])
    larguras = (13, 9, 12, 28, 16, 10, 12, 28, 18, 28, 30, 8, 16, 22, 13, 26, 22, 20, 30, 26, 18, 24, 50, 44, 34, 22, 30)
    for i, w in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = f'A1:{get_column_letter(len(cab))}{len(rs) + 1}'
    wb.save(caminho)
