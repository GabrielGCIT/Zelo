"""O mesmo termo da tela Termo, em PDF (para anexar no chamado do Service Desk)."""
import io
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE = ParagraphStyle('base', fontName='Helvetica', fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=8)
NEG = ParagraphStyle('neg', parent=BASE, fontName='Helvetica-Bold')
TIT = ParagraphStyle('tit', parent=BASE, fontName='Helvetica-BoldOblique', fontSize=11.5, alignment=TA_CENTER, spaceBefore=14,
                     spaceAfter=14)
DIR = ParagraphStyle('dir', parent=BASE, alignment=TA_RIGHT)
END = ParagraphStyle('end', parent=BASE, fontSize=8.5, leading=11, alignment=TA_RIGHT, spaceAfter=0)
LOGO = ParagraphStyle('logo', parent=BASE, fontName='Helvetica-Bold', fontSize=22, leading=24, alignment=0, spaceAfter=0)
ASS = ParagraphStyle('ass', parent=BASE, fontSize=9.5, alignment=TA_CENTER, spaceAfter=0)
REF = ParagraphStyle('ref', parent=BASE, fontSize=7.5, textColor='#666666', spaceBefore=18)


def _p(t, st=BASE):
    return Paragraph(escape(t or '').replace('\n', '<br/>'), st)


def gerar_pdf(d):
    """d: o dicionário de app.routes.termo.montar(). Devolve os bytes do PDF."""
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
    s.append(Spacer(1, 2.2 * cm))
    empresa = 'Martin Brower Brasil' if d.get('ass_empresa') == '(empresa)' else (d.get('ass_empresa') or '')
    ass = Table([[_p(f'{d.get("nome") or ""}\nColaborador(a)', ASS), '', _p(empresa, ASS)]],
                colWidths=[7.4 * cm, 1.8 * cm, 7.4 * cm])
    ass.setStyle(TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.8, '#000000'), ('LINEABOVE', (2, 0), (2, 0), 0.8, '#000000'),
                             ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    s.append(ass)
    num = str(d.get('num') or '')
    s.append(_p('Ref.: ' + (f'lançamento Nº {num}' if num.isdigit() else num) + ' · gerado pelo Zelo', REF))
    doc.build(s)
    return buf.getvalue()
