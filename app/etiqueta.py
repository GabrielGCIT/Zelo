"""Etiqueta com código de barras para colar no equipamento.

Code 128 (conjunto B) desenhado em SVG, sem depender de biblioteca: o pacote offline do
Windows já está fechado e uma etiqueta não justifica refazê-lo. O leitor de mão lê Code 128
nativamente e entrega o conteúdo como se fosse digitado, então o que vai no código é a
PLAQUETA (ou o código do item, quando não há plaqueta) — exatamente o que a tela de bipagem
espera receber.
"""
import re

# Largura das barras/espaços de cada um dos 107 símbolos do Code 128 (começando por barra).
# Os 106 primeiros somam 11 módulos; o 106 (parada) tem 13.
PADROES = [
    '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
    '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
    '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
    '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
    '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
    '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
    '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
    '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
    '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
    '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
    '114131', '311141', '411131', '211412', '211214', '211232', '2331112',
]
INICIO_B, PARADA = 104, 106
LIMPA = re.compile(r'[^\x20-\x7e]')


def codigo_do_item(it):
    """O que vai no código de barras: a plaqueta quando existe (é o que está colado na máquina)."""
    return (it.plaqueta or it.codigo or '').strip()


def barras(texto):
    """Sequência de larguras do Code 128-B para o texto, com dígito verificador. '' se não der."""
    t = LIMPA.sub('', texto or '')
    if not t:
        return ''
    valores = [ord(c) - 32 for c in t]
    soma = INICIO_B + sum((i + 1) * v for i, v in enumerate(valores))
    simbolos = [INICIO_B] + valores + [soma % 103, PARADA]
    return ''.join(PADROES[s] for s in simbolos)


def svg(texto, altura=34, modulo=1.6, legenda=True):
    """SVG do código de barras. modulo = largura da barra fina em px (1.6 ≈ boa leitura em 203 dpi)."""
    seq = barras(texto)
    if not seq:
        return ''
    larg = sum(int(c) for c in seq) * modulo
    alt = altura + (12 if legenda else 0)
    partes, x, barra = [], 0.0, True
    for c in seq:
        w = int(c) * modulo
        if barra:
            partes.append(f'<rect x="{x:.2f}" y="0" width="{w:.2f}" height="{altura}"/>')
        x += w
        barra = not barra
    leg = (f'<text x="{larg / 2:.2f}" y="{alt - 2}" text-anchor="middle" font-family="monospace" '
           f'font-size="9" letter-spacing="0.6">{_esc(texto)}</text>') if legenda else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{larg:.2f}" height="{alt}" '
            f'viewBox="0 0 {larg:.2f} {alt}" role="img" aria-label="código de barras {_esc(texto)}">'
            f'<g fill="#000">{"".join(partes)}{leg}</g></svg>')


def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
