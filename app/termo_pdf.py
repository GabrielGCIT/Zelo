"""O mesmo termo da tela Termo, em PDF (para anexar no chamado do Service Desk).

Com as vias assinadas na tela, o desenho de cada assinatura entra acima da linha e o rodapé ganha
o bloco de conferência: quem assinou, quando, de qual endereço e o código da via. É esse bloco —
não o desenho — que permite conferir depois se o papel é o mesmo.
"""
import io
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE = ParagraphStyle('base', fontName='Helvetica', fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=8)
NEG = ParagraphStyle('neg', parent=BASE, fontName='Helvetica-Bold')
TIT = ParagraphStyle('tit', parent=BASE, fontName='Helvetica-BoldOblique', fontSize=11.5, alignment=TA_CENTER, spaceBefore=14,
                     spaceAfter=14)
DIR = ParagraphStyle('dir', parent=BASE, alignment=TA_RIGHT)
END = ParagraphStyle('end', parent=BASE, fontSize=8.5, leading=11, alignment=TA_RIGHT, spaceAfter=0)
LOGO = ParagraphStyle('logo', parent=BASE, fontName='Helvetica-Bold', fontSize=22, leading=24, alignment=0, spaceAfter=0)
ASS = ParagraphStyle('ass', parent=BASE, fontSize=9.5, alignment=TA_CENTER, spaceAfter=0)
REF = ParagraphStyle('ref', parent=BASE, fontSize=7.5, textColor='#666666', spaceBefore=18)


CONF = ParagraphStyle('conf', parent=BASE, fontSize=7.5, leading=10, alignment=TA_JUSTIFY, spaceBefore=10, spaceAfter=0,
                      textColor='#333333')


def _p(t, st=BASE):
    return Paragraph(escape(t or '').replace('\n', '<br/>'), st)


def _traco(a, larg=6.4 * cm, alt=1.5 * cm):
    """O desenho da assinatura, encaixado sem distorcer, ou um espaço em branco do mesmo tamanho."""
    if not (a and a.assinado and a.traco):
        return Spacer(1, alt)
    try:
        iw, ih = ImageReader(io.BytesIO(a.traco)).getSize()
        escala = min(larg / iw, alt / ih)
        return Image(io.BytesIO(a.traco), width=iw * escala, height=ih * escala, hAlign='CENTER')
    except Exception:                                  # noqa: BLE001 — sem o desenho, o bloco de conferência basta
        return Spacer(1, alt)


def _conferencia(assinaturas):
    """Uma linha por via assinada: quem, quando, de onde e o código para conferir."""
    from app.assinatura import ROTULO, codigo
    from app.formato import quando_br
    linhas = []
    for a in assinaturas:
        if not (a and a.assinado):
            continue
        linhas.append(f'<b>{escape(ROTULO.get(a.papel, a.papel))}:</b> {escape(a.assinante or a.nome or "")} · '
                      f'assinou em {escape(quando_br(a.assinado))}' + (f' · IP {escape(a.ip)}' if a.ip else '')
                      + f' · código {codigo(a)}')
    if not linhas:
        return None
    return Paragraph('Assinaturas coletadas eletronicamente no Zelo, com registro de data, hora e endereço de origem.'
                     '<br/>' + '<br/>'.join(linhas), CONF)


def gerar_pdf(d, assinaturas=None):
    """d: o dicionário de app.routes.termo.montar(). Devolve os bytes do PDF.

    assinaturas: [via do colaborador, via da empresa] quando o termo foi assinado na tela.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, title=d.get('titulo') or 'Termo', author='Zelo')
    cab = Table([[Paragraph('MB Martin<br/>Brower.', LOGO),
                  Paragraph('Martin Brower Brasil<br/>Avenida das Comunicações, 333<br/>Parque Industrial Anhanguera<br/>'
                            'Osasco, SP<br/>06276-190<br/>Tel: +55 (11) 3659-2800<br/><br/>martinbrower.com.br', END)]],
                colWidths=[8 * cm, 8.6 * cm])
    cab.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                             ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    s = [cab, _p(d.get('titulo'), TIT), _p(d.get('data_ext'), DIR)]
    ilmo = f'Ilmo Sr(a).  {d.get("nome") or ""}'
    if d.get('matricula_fmt'):
        ilmo += f'\nMatrícula nº {d["matricula_fmt"]}'
    s.append(_p(ilmo))
    s.append(_p(d.get('abertura')))
    for k in ('equipamento', 'linha', 'acessorios'):
        if d.get(k):
            s.append(_p(d[k], NEG))
    if d.get('periodo'):
        s.append(Paragraph(f'<b>Período do empréstimo:</b> {escape(d["periodo"])}'
                           + (f' · {escape(d["ref"])}' if d.get('ref') else ''), BASE))
    elif d.get('chamado'):
        s.append(Paragraph(f'<b>Chamado:</b> {escape(d["chamado"])}', BASE))
    for k in ('p1', 'p2'):
        if d.get(k):
            s.append(_p(d[k]))
    if d.get('obs'):
        s.append(Paragraph(f'<b>Observação:</b> {escape(d["obs"])}', BASE))
    if d.get('fecho'):
        s.append(_p(d['fecho']))
    vias = list(assinaturas or [])
    v_colab = next((a for a in vias if a and a.papel == 'colaborador'), None)
    v_emp = next((a for a in vias if a and a.papel == 'empresa'), None)
    empresa = 'Martin Brower Brasil' if d.get('ass_empresa') == '(empresa)' else (d.get('ass_empresa') or '')
    nome_emp = (v_emp.assinante or v_emp.nome) if (v_emp and v_emp.assinado) else ''
    s.append(Spacer(1, 0.8 * cm if (v_colab or v_emp) else 2.2 * cm))
    desenhos = Table([[_traco(v_colab), '', _traco(v_emp)]], colWidths=[7.4 * cm, 1.8 * cm, 7.4 * cm])
    desenhos.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
    s.append(desenhos)
    ass = Table([[_p(f'{(v_colab.assinante if v_colab and v_colab.assinado else None) or d.get("nome") or ""}\n'
                     'Colaborador(a)', ASS), '',
                  _p((f'{nome_emp}\n{empresa}' if nome_emp else empresa), ASS)]],
                colWidths=[7.4 * cm, 1.8 * cm, 7.4 * cm])
    ass.setStyle(TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.8, '#000000'), ('LINEABOVE', (2, 0), (2, 0), 0.8, '#000000'),
                             ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 2)]))
    s.append(ass)
    conf = _conferencia(vias)
    if conf:
        s.append(conf)
    num = str(d.get('num') or '')
    s.append(_p('Ref.: ' + (f'lançamento Nº {num}' if num.isdigit() else num) + ' · gerado pelo Zelo', REF))
    doc.build(s)
    return buf.getvalue()
