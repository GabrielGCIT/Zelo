"""Agente do Zelo: o inventário que as próprias máquinas mandam.

Nasceu porque o agente do SDP ficou incerto na MB (licenças, 18/11). Sem ele, ninguém descreve a
máquina: a service tag vem digitada da planilha, e nada diz quem fez login nem quando ela foi vista.
O agente do Zelo é um script PowerShell (`scripts/agente/zelo-agente.ps1`) que lê isso do próprio
Windows e manda para cá. O instalador (`instalar-agente.ps1`) só copia o script e cria uma tarefa
agendada que o roda no logon, no boot e uma vez por dia — nenhum serviço, nenhum executável.

Regras que não são óbvias:
- **a senha não é segredo forte.** O script vai ficar legível onde for distribuído (SYSVOL, por
  exemplo). Por isso este endereço só aceita inventário, valida tudo e nunca decide nada sobre
  pessoa ou situação a partir do que recebe — o pior que um envio falso faz é uma linha errada na
  tela de conferência, que alguém olha antes de mexer;
- **a máquina é identificada pela service tag**, que não muda quando alguém a renomeia. Sem tag
  (VM, placa genérica), cai no hostname;
- serial de placa genérica ("To be filled by O.E.M.", "Default string") não é service tag: aceitá-lo
  juntaria máquinas diferentes numa linha só.
"""
import hmac
import os
import re
from datetime import datetime

from app import db
from app.models import MaquinaVista, cfg
from app.servicedesk import host_curto

# Seriais que o fabricante deixa de fábrica em placa genérica e em máquina virtual.
TAG_LIXO = {'', '0', 'NONE', 'DEFAULT STRING', 'TO BE FILLED BY O.E.M.', 'SYSTEM SERIAL NUMBER',
            'NOT APPLICABLE', 'NOT SPECIFIED', 'CHASSIS SERIAL NUMBER', 'SERIAL NUMBER', '123456789',
            'INVALID'}
LIMITES = {'tag': 60, 'hostname': 60, 'fabricante': 100, 'modelo': 100, 'chassi': 30, 'so': 100,
           'usuario': 120, 'ip': 200, 'mac': 200, 'versao': 20}


def ligado():
    return bool((cfg('agente_token') or '').strip())


def senha_confere(recebida):
    esperada = (cfg('agente_token') or '').strip()
    # compare_digest: comparar com == entrega a senha por tempo de resposta, caractere a caractere
    return bool(esperada) and hmac.compare_digest(esperada.encode(), (recebida or '').strip().encode())


def _texto(v, limite):
    if isinstance(v, (list, tuple)):
        v = ', '.join(str(x) for x in v if x not in (None, ''))
    if v is None or isinstance(v, (dict, bool)):
        return ''
    s = re.sub(r'[\x00-\x1f\x7f]', ' ', str(v)).strip()
    return s[:limite]


def tag_valida(t):
    t = (t or '').strip()
    if t.upper() in TAG_LIXO or t.upper().startswith('VMWARE-') or len(set(t.replace('-', ''))) <= 1:
        return ''
    return t


def limpar(dados):
    """O que veio do script, só com os campos conhecidos, cortados no tamanho da coluna. Devolve
    (campos, erro)."""
    if not isinstance(dados, dict):
        return None, 'o corpo tem que ser um objeto JSON'
    c = {k: _texto(dados.get(k), n) for k, n in LIMITES.items()}
    c['hostname'] = host_curto(c['hostname'])
    c['tag'] = tag_valida(c['tag']).upper()
    if not c['hostname']:
        return None, 'falta o hostname'
    return c, ''


def receber(dados, origem=''):
    """Grava o que uma máquina mandou. Devolve (ok, recado).

    Atualiza a linha da máquina em vez de criar outra: o que interessa é o estado de agora e a
    última vez que foi vista, não o histórico de cada logon (isso encheria o banco em semanas).
    """
    c, erro = limpar(dados)
    if erro:
        return False, erro
    agora = datetime.now().isoformat(timespec='seconds')
    m = None
    if c['tag']:
        m = MaquinaVista.query.filter_by(tag=c['tag']).first()
    if m is None:
        # sem tag, ou tag nova: a máquina pode já existir pelo nome, de um envio sem tag
        m = MaquinaVista.query.filter(MaquinaVista.hostname == c['hostname'],
                                      (MaquinaVista.tag.is_(None)) | (MaquinaVista.tag == '')).first()
    if m is None:
        m = MaquinaVista(primeira_vez=agora)
        db.session.add(m)
    for k, v in c.items():
        # campo que não veio desta vez não apaga o que já se sabia (um envio sem rede não tem IP)
        if v or k in ('hostname',):
            setattr(m, k, v)
    m.visto_em, m.origem = agora, (origem or '')[:45]
    db.session.commit()
    return True, f'{m.hostname} registrada'


def como_ativos():
    """As máquinas vistas no mesmo formato que `conferir_sd.do_sd` devolve, para a conferência e a
    cobertura servirem às duas fontes sem duplicar a regra."""
    saida = []
    for m in MaquinaVista.query.all():
        saida.append({'id': str(m.id), 'hostname': m.hostname or '', 'tag': m.tag or '', 'plaqueta': '',
                      'modelo': m.modelo or '', 'tipo': m.chassi or '', 'estado': '', 'usuario': '',
                      'site': '', 'garantia': '', 'fornecedor': '', 'varredura': (m.visto_em or '')[:10],
                      'logado': m.usuario or '', 'campos_agente': True})
    return saida


# ------------------------------------------------------------------ pacote de instalação
PASTA_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'agente')
ARQUIVOS_PACOTE = ('zelo-agente.ps1', 'instalar-agente.ps1', 'instalar-agente.bat', 'desinstalar-agente.bat')

LEIAME = r'''Agente do Zelo
==============

Numa maquina:
  botao direito em  instalar-agente.bat  >  Executar como administrador.
  Ele copia o agente para C:\ProgramData\Zelo\Agente, cria a tarefa agendada
  "Zelo - Agente" e manda o primeiro inventario. No fim diz se o Zelo recebeu.

Em massa (GPO, Intune, SCCM), como SYSTEM:
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File instalar-agente.ps1 -Silencioso

Para remover:  desinstalar-agente.bat  (como administrador).

O agente.conf tem o endereco do Zelo e a senha do agente. Se a senha mudar no
Zelo, baixe o pacote de novo e reinstale: as maquinas com a senha antiga param
de ser aceitas.

Endereco gravado neste pacote: {endereco}
Gerado em: {quando}
'''


def endereco_valido(endereco):
    return bool(re.match(r'^https?://[^\s/]+(:\d+)?/?$', (endereco or '').strip()))


def pacote(endereco, senha):
    """O ZIP que se leva para a máquina: os scripts e um agente.conf já preenchido.

    Os .ps1 saem sempre com BOM e CRLF, venha o arquivo de onde vier: o PowerShell 5.1 lê .ps1 sem
    BOM no código de página do sistema, e todo acento do script vira lixo — inclusive nas
    mensagens que o instalador mostra. Um clone feito no Linux perderia isso sem ninguém notar.
    """
    import io
    import json
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for nome in ARQUIVOS_PACOTE:
            with open(os.path.join(PASTA_SCRIPTS, nome), encoding='utf-8-sig') as fh:
                texto = fh.read().replace('\r\n', '\n').replace('\n', '\r\n')
            z.writestr(f'zelo-agente/{nome}', texto.encode('utf-8-sig' if nome.endswith('.ps1') else 'utf-8'))
        conf = json.dumps({'zelo': endereco.strip().rstrip('/'), 'senha': senha}, indent=2, ensure_ascii=False)
        z.writestr('zelo-agente/agente.conf', conf.encode('utf-8'))
        quando = datetime.now().strftime('%d/%m/%Y %H:%M')
        z.writestr('zelo-agente/LEIAME.txt',
                   LEIAME.format(endereco=endereco.strip().rstrip('/'), quando=quando).replace('\n', '\r\n'))
    return buf.getvalue()
