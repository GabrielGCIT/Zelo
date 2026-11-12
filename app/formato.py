"""Filtros de exibição: datas no padrão brasileiro e cor de cada situação."""
from datetime import date, datetime

COR_SITUACAO = {
    'Em estoque': 'success', 'Livre': 'success', 'Em uso': 'primary', 'Emprestado': 'loaner', 'Reservada': 'info',
    'Pendente devolução': 'warning', 'Em trânsito para o EC': 'warning', 'Devolvido': 'warning',
    'Em preparação': 'warning', 'Manutenção': 'danger', 'Em transferência': 'secondary', 'A localizar': 'danger',
    'Aguardando baixa': 'secondary', 'Baixada': 'dark', 'Sem movimentação': 'light', 'Cancelada': 'dark',
    'Ativo': 'success', 'Desligado': 'dark',
}


def data_br(v):
    if not v:
        return ''
    if isinstance(v, (date, datetime)):
        return v.strftime('%d/%m/%Y')
    s = str(v)
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return f'{s[8:10]}/{s[5:7]}/{s[0:4]}'
    return s


def fone_br(v):
    """11 dígitos → (11) 98765-4321. Qualquer outro tamanho sai como está."""
    d = ''.join(c for c in str(v or '') if c.isdigit())
    if len(d) == 11:
        return f'({d[:2]}) {d[2:7]}-{d[7:]}'
    if len(d) == 10:
        return f'({d[:2]}) {d[2:6]}-{d[6:]}'
    return str(v or '')


def hoje_iso():
    return date.today().isoformat()


def dias_desde(v):
    try:
        return (date.today() - date.fromisoformat(str(v)[:10])).days
    except (TypeError, ValueError):
        return None


def registrar(app):
    app.jinja_env.filters['data'] = data_br
    app.jinja_env.filters['fone'] = fone_br
    app.jinja_env.filters['cor'] = lambda s: COR_SITUACAO.get(s or '', 'secondary')
    app.jinja_env.globals['dias_desde'] = dias_desde
    app.jinja_env.globals['hoje'] = hoje_iso
