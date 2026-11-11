"""Manutenção: abrir, atualizar e fechar ocorrências (igual à aba Lançar Manutenção da planilha).

- Atualizar/Fechar acham sozinhos a ocorrência aberta do item.
- Backup (máquina livre do pool) ao abrir — ou ao atualizar uma OS que ainda não tem — gera o Empréstimo
  para quem está com a máquina; ao fechar, "Backup volta? Sim" gera a Devolução do backup.
- Peça usada sai do estoque do EC.
"""
from datetime import date, datetime, timedelta

from app import db
from app.lancamento import saldo
from app.models import Consumivel, Item, Manutencao, MovConsumivel, Movimentacao, Pessoa, cfg
from app.regras import tocar

ACOES_MANUT = ['Abrir ocorrência', 'Atualizar ocorrência', 'Fechar ocorrência']


def aberta_do_item(codigo):
    for m in Manutencao.query.filter_by(item=codigo).order_by(Manutencao.id.desc()):
        if m.aberta:
            return m
    return None


def _anexa(antes, novo):
    return f'{antes}; {novo}' if antes else novo


def registrar(d, resp):
    """d: acao, item(Item), defeito, fornecedor, caso, status, visita, tecnico, chamado, backup, peca, qtd, feito,
    backup_volta, obs. Devolve (ok, mensagem)."""
    from app.routes.consulta import achar_item
    acao = d.get('acao')
    if acao not in ACOES_MANUT:
        return False, 'Escolha a Ação'
    it = achar_item(d.get('item'))
    if not it:
        return False, 'Item não encontrado (item novo: cadastre em Consumíveis → Cadastrar item)'
    if it.situacao == 'Baixada':
        return False, 'Item baixado'
    os_ = aberta_do_item(it.codigo)
    abrir, atual, fechar = acao == ACOES_MANUT[0], acao == ACOES_MANUT[1], acao == ACOES_MANUT[2]
    if abrir and os_:
        return False, f'Já tem ocorrência aberta (OS {os_.id}): use Atualizar ou Fechar'
    if not abrir and not os_:
        return False, 'Não há ocorrência aberta para esse item'
    if abrir and not d.get('defeito'):
        return False, 'Descreva o defeito'
    st = d.get('status') or ''
    if atual and st in ('Concluída', 'Sem conserto'):
        return False, 'Para encerrar, use Fechar ocorrência'
    if fechar and st and st not in ('Concluída', 'Sem conserto'):
        return False, 'Fechar: deixe Status vazio (= Concluída) ou escolha Sem conserto'
    if fechar and not d.get('feito'):
        return False, 'Fechar: descreva O que foi feito'
    campos = ('defeito', 'fornecedor', 'caso', 'status', 'visita', 'tecnico', 'chamado', 'backup', 'peca', 'feito', 'obs')
    if atual and not any(d.get(k) for k in campos):
        return False, 'Atualizar: preencha o que mudou'
    backup = d.get('backup') or ''
    emprest = bool(backup) and (abrir or (atual and not os_.substituto))
    if backup and not emprest:
        return False, 'Backup só ao abrir (ou ao atualizar uma ocorrência que ainda não tem backup)'
    b = None
    if emprest:
        b = achar_item(backup)
        if not b:
            return False, 'Backup não encontrado em Itens'
        if b.finalidade != 'Pool de empréstimo':
            return False, 'Backup precisa ser máquina do pool de empréstimo'
        if b.situacao != 'Em estoque':
            return False, f'Backup não está livre (está {b.situacao})'
        if not it.matricula:
            return False, 'A máquina não está com ninguém: backup não se aplica'
    volta = d.get('backup_volta') or ''
    sub = db.session.get(Item, os_.substituto) if (os_ and os_.substituto) else None
    if fechar and sub and sub.situacao == 'Emprestado' and not volta:
        return False, f'O backup {sub.codigo} está com {sub.com_quem}: diga se volta (Backup volta? Sim/Não)'
    devolve = fechar and sub is not None and volta == 'Sim'
    if devolve and sub.situacao != 'Emprestado':
        return False, f'O backup não está emprestado (está {sub.situacao})'
    if volta and not (fechar and sub):
        return False, 'Backup volta? só ao fechar ocorrência que tem backup'
    peca, qtd = d.get('peca') or '', 0
    if peca:
        if not Consumivel.query.filter_by(nome=peca).first():
            return False, 'Peça fora do catálogo (Consumíveis)'
        try:
            qtd = int(d.get('qtd') or 0)
        except ValueError:
            qtd = 0
        if qtd <= 0:
            return False, 'Informe a quantidade da peça'
        if qtd > saldo(peca):
            return False, f'Sem saldo da peça no EC (tem {saldo(peca)})'
    if d.get('visita'):
        try:
            datetime.fromisoformat(d['visita'])
        except ValueError:
            return False, 'Visita: data e hora'

    hoje = date.today().isoformat()
    agora = datetime.now().isoformat(timespec='seconds')
    if abrir:
        os_ = Manutencao(item=it.codigo, abertura=hoje, site=it.site, defeito=d['defeito'],
                         status=st or ('Visita agendada' if d.get('visita') else 'No lab aguardando'))
        db.session.add(os_)
    else:
        os_.status = ('Concluída' if not st else st) if fechar else (st or os_.status)
        if d.get('defeito'):
            os_.defeito = d['defeito']
    for k in ('fornecedor', 'caso', 'visita', 'tecnico', 'chamado'):
        if d.get(k):
            setattr(os_, k, d[k].replace('T', ' ') if k == 'visita' else d[k])
    if fechar:
        os_.retorno, os_.solucao = hoje, d['feito']
    if peca:
        os_.pecas = _anexa(os_.pecas, f'{qtd} × {peca}')
    if d.get('obs'):
        os_.obs = _anexa(os_.obs, d['obs'])
    if emprest:
        os_.substituto = b.codigo
    db.session.flush()
    msg = [f'{"abre" if abrir else ("fecha" if fechar else "atualiza")} a OS {os_.id} ({os_.status})']
    if emprest:
        p = db.session.get(Pessoa, it.matricula)
        dias = int(cfg('prazo_emprestimo') or 30)
        db.session.add(Movimentacao(
            data=hoje, tipo='Empréstimo', item=b.codigo, matricula=it.matricula, nome=it.com_quem, cc=p.cc if p else None,
            etapa='Entregue', termo='Pendente', chamado=d.get('chamado') or None, data_ent=hoje,
            prazo=(date.today() + timedelta(days=dias)).isoformat(),
            motivo=f'Máquina em manutenção: {it.codigo} (OS {os_.id})'[:60], resp=resp, tecnico=d.get('tecnico') or None,
            obs=f'Backup da OS {os_.id}', reg_em=agora))
        msg.append(f'empréstimo de {b.codigo} para {it.com_quem}')
    if devolve:
        db.session.add(Movimentacao(data=hoje, tipo='Devolução', item=sub.codigo, matricula=sub.matricula, nome=sub.com_quem,
                                    resp=resp, obs=f'Volta do backup: OS {os_.id} fechada', reg_em=agora))
        msg.append(f'{sub.codigo} volta ao estoque')
    if peca:
        db.session.add(MovConsumivel(data=hoje, consumivel=peca, site='EC', movimento='Saída', qtd=qtd, destino=it.codigo,
                                     chamado=d.get('chamado') or None, resp=resp, obs=f'Peça da OS {os_.id}'))
        msg.append(f'baixa {qtd} × {peca}')
    db.session.flush()
    tocar([it.codigo, b.codigo if b else None, sub.codigo if devolve else None])
    db.session.commit()
    return True, ' · '.join(msg)
