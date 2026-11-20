"""Cadastro em massa: pôr no Service Desk os itens do Zelo que ainda não estão lá.

Deixou de ser opcional em 18/11, quando o agente do SDP ficou incerto (licenças): sem agente,
ninguém cria notebook nem desktop no SD, e monitor, celular, dock e coletor nunca teriam como entrar.

O que esta tela responde ANTES de qualquer escrita, por categoria:
- quantos itens vivos o Zelo tem e quantos o SD já conhece;
- para qual tipo de produto (e, portanto, endereço da API) cada categoria iria — e se ele existe;
- se cada modelo tem produto próprio no SD ou vai cair no primeiro produto do tipo. É a decisão do
  PLANO (produto por modelo × genérico por tipo) com número em vez de palpite.

Regras que não são óbvias:
- **a escrita é a fila de sempre** (`EnvioSD` tipo ativo), um item por envio: o SDP não aceita lote,
  e uma criação que falha fica na fila com o motivo, para reenviar, em vez de abortar as outras;
- o envio procura o ativo de novo antes de criar (`enviar_ativo` → `achar_ativo`): a análise pode
  estar velha, e duplicar ativo no SD é o estrago que esta integração existe para evitar;
- o Zelo **não cria produto nem tipo de produto**. Categoria cujo tipo não existe no SD fica
  bloqueada aqui, com o motivo; quem resolve é o administrador do SD (ou o mapa de tipos);
- item **Baixado** não entra: criar ativo morto só para marcá-lo Expired é sujar a base.
"""
from app import db
from app import servicedesk as sd
from app.conferir_sd import baixar
from app.models import EnvioSD, Item


def _tipo_do_produto(p):
    t = p.get('product_type')
    return sd._nome(t.get('name') if isinstance(t, dict) else t)


def _no_sd(ativos):
    """Os nomes e as service tags que o Service Desk já tem. O nome compara pelo nome curto (o
    agente põe domínio); a tag, em maiúsculas."""
    nomes, tags = set(), set()
    for a in ativos:
        if a.get('hostname'):
            nomes.add(sd.host_curto(a['hostname']))
        if a.get('tag'):
            tags.add(a['tag'].strip().upper())
    return nomes, tags


def _ja_esta(it, nomes, tags):
    if sd.host_curto(sd.nome_no_sd(it)) in nomes:
        return True
    return bool((it.tag or '').strip()) and it.tag.strip().upper() in tags


def sem_dono(it, estados=None):
    """Item "Em uso" (ou que vira In Use) sem pessoa no cadastro — máquina de posto no CD.

    O SDP não aceita In Use sem usuário (laboratório, 18/11), nem para criar nem para atualizar.
    Na importação de 18/11 são 74 desktops, 73 thin clients e 3 notebooks. Mandá-los seria colher
    erro na fila; o lugar de resolver é o cadastro do Zelo, pondo quem responde pela máquina.
    """
    estados = estados if estados is not None else sd.mapa_estados()
    return it.situacao in sd.COM_PESSOA and not it.matricula and estados.get(it.situacao or '') == 'In Use'


def analisar():
    """O retrato do que o cadastro em massa faria. Só lê o Service Desk.

    Devolve dict com `erro` (texto; vazio se deu certo), `no_sd` (quantos ativos lá), `truncou`,
    `produtos` (quantos produtos lá) e `categorias` — uma por categoria do Zelo, com os itens que
    faltam e o porquê de não poder criar, quando for o caso.
    """
    saida = {'erro': '', 'no_sd': 0, 'truncou': False, 'produtos': 0, 'categorias': []}
    if not sd.configurado():
        saida['erro'] = 'A integração com o Service Desk está desligada ou sem chave.'
        return saida
    ativos, truncou, erro = baixar()
    if erro:
        saida['erro'] = f'Não deu para listar os ativos do Service Desk: {erro}'
        return saida
    try:
        produtos = sd.listar_produtos(recarregar=True)
        sd.listar_modulos(recarregar=True)
    except sd.ErroSD as e:
        saida['erro'] = f'Não deu para ler o catálogo do Service Desk: {e}'
        return saida
    saida.update(no_sd=len(ativos), truncou=truncou, produtos=len(produtos))
    nomes, tags = _no_sd(ativos)
    por_nome = {sd._nome(p.get('name')): p for p in produtos}
    mapa = sd.mapa_tipos()
    estados = sd.mapa_estados()

    grupos = {}
    for it in Item.query.filter(Item.situacao != 'Baixada').order_by(Item.categoria, Item.modelo, Item.codigo):
        grupos.setdefault(it.categoria or '(sem categoria)', []).append(it)

    for cat, itens in grupos.items():
        tipo = mapa.get(cat)
        mod = sd.modulo_do_tipo(tipo) if tipo else None
        do_tipo = [p for p in produtos if tipo and _tipo_do_produto(p) == sd._nome(tipo)]
        motivo = ''
        if cat not in mapa:
            motivo = 'sem tipo de produto: acrescente em "Tipos de produto próprios"'
        elif not tipo and cat in sd.SO_NO_ZELO:
            motivo = ('fica só no Zelo: ninguém abre chamado por ele. Para mandar mesmo assim, mapeie em '
                      '"Tipos de produto próprios"')
        elif not tipo:
            motivo = 'criação desligada para esta categoria em "Tipos de produto próprios"'
        elif not mod:
            motivo = f'o tipo "{tipo}" não existe no seu Service Desk: crie lá ou mapeie para um que exista'
        elif not do_tipo:
            # Sem perguntar ao _metainfo: no laboratório (18/11) ele não marcou `product` como
            # obrigatório em Smart Phone, a tela disse "pronta", e todas as criações voltaram
            # "400 Value not provided". O produto é exigido nos dois builds que conhecemos.
            motivo = f'não há nenhum produto do tipo "{tipo}" no Service Desk: cadastre ao menos um'
        faltam = [it for it in itens if not _ja_esta(it, nomes, tags)]
        orfaos = [it for it in faltam if sem_dono(it, estados)]
        faltam = [it for it in faltam if not sem_dono(it, estados)]
        modelos = {}
        for it in faltam:
            chave = (it.modelo or '').strip()
            m = modelos.setdefault(chave, {'modelo': chave or '(sem modelo)', 'n': 0, 'produto': '', 'como': ''})
            m['n'] += 1
        for m in modelos.values():
            p = por_nome.get(sd._nome(m['modelo'])) if m['modelo'] != '(sem modelo)' else None
            if p:
                m['produto'], m['como'] = p.get('name'), 'proprio'
            elif do_tipo:
                m['produto'], m['como'] = do_tipo[0].get('name'), 'generico'
            else:
                m['como'] = 'nenhum'
        saida['categorias'].append({
            'categoria': cat, 'total': len(itens), 'ja_no_sd': len(itens) - len(faltam) - len(orfaos),
            'faltam': faltam, 'sem_dono': orfaos,
            'tipo': tipo or '', 'endereco': f"/api/v3/{mod['api_plural_name']}" if mod else '',
            'motivo': motivo, 'pronta': not motivo and bool(faltam),
            'so_zelo': not tipo and cat in sd.SO_NO_ZELO,
            'modelos': sorted(modelos.values(), key=lambda x: -x['n']),
        })
    # prontas primeiro, as que só ficam no Zelo por último: são decisão, não pendência
    saida['categorias'].sort(key=lambda c: (not c['pronta'], c['so_zelo'], -len(c['faltam'])))
    return saida


def enfileirar(categorias, limite=None):
    """Põe na fila a criação dos itens que faltam nas categorias pedidas. Devolve (ids, recado).

    Refaz a análise em vez de confiar na tela: entre abrir a página e clicar, alguém pode ter
    cadastrado coisa no SD ou mudado o mapa. `limite` existe para começar por um lote pequeno,
    conferir no SD como os ativos nasceram, e só então mandar o resto.
    """
    if not sd.criar_ativo_ligado():
        return [], ('Ligue "Atualizar o ativo no Service Desk" e "Cadastrar o ativo no Service Desk quando ele '
                    'não existir lá" antes: o cadastro em massa usa a mesma fila.')
    a = analisar()
    if a['erro']:
        return [], a['erro']
    pendentes = {e.alvo for e in EnvioSD.query.filter(EnvioSD.tipo == 'ativo', EnvioSD.status != 'Enviado')}
    from datetime import datetime
    agora = datetime.now().isoformat(timespec='seconds')
    novos, vistos, pulados = [], set(), 0
    for c in a['categorias']:
        if c['categoria'] not in categorias or not c['pronta']:
            continue
        for it in c['faltam']:
            nome = sd.nome_no_sd(it)
            # mesmo nome duas vezes no Zelo (tag repetida) ou já na fila: o SD recusaria o segundo
            if not nome or nome in pendentes or nome in vistos:
                pulados += 1
                continue
            vistos.add(nome)
            novos.append(EnvioSD(mov_id=None, tipo='ativo', alvo=nome, codigo=it.codigo, status='Pendente',
                                 criado=agora, tentativas=0))
            if limite and len(novos) >= limite:
                break
        if limite and len(novos) >= limite:
            break
    db.session.add_all(novos)
    db.session.commit()
    recado = f'{len(novos)} item(ns) na fila de cadastro.'
    if pulados:
        recado += f' {pulados} pulado(s): já na fila, ou com o mesmo nome de outro item do Zelo.'
    return [e.id for e in novos], recado
