"""Modelo de dados do Zelo.

O desenho segue a planilha "Gestão de Ativos de TI", que é a especificação viva
do processo:

- o Histórico (Movimentacao) é a fonte da verdade: a situação de cada item e de
  cada linha é calculada a partir do último lançamento que a afeta;
- Item, Linha e Pessoa guardam cadastro; os campos "atuais" (situação, com quem,
  desde, prazo...) são um cache recalculado por `app.regras.recalcular_item` /
  `recalcular_linha` sempre que um lançamento toca o item ou a linha. O cache
  existe para as listas e o painel não recalcularem 5 mil movimentos a cada tela.
"""
from datetime import datetime

from app import db


# ---------------------------------------------------------------------------
# Listas de domínio (as mesmas da aba Config da planilha)
# ---------------------------------------------------------------------------
CATEGORIAS = ['Notebook', 'Desktop', 'Thin client', 'Monitor', 'Dock station', 'Celular', 'Tablet', 'Coletor',
              'Base de coletor', 'Telefone IP', 'Sala de reunião', 'Kiosk', 'Impressora', 'Outro']
FABRICANTES = ['Dell', 'Lenovo', 'Samsung', 'Motorola', 'Apple', 'Zebra', 'Logitech', 'Barco', 'Polycom',
               'Grandstream', 'Google', 'Kensington', 'Plantronics', 'Outro']
PROPRIEDADES = ['Próprio', 'Locado', 'Comodato', 'Terceiro']
FINALIDADES = ['Uso definitivo', 'Pool de empréstimo']
SITES = ['EC', 'GR', 'FT', 'JC', 'NE', 'PR', 'RJ', 'SC', 'DF', 'AM', 'Sala Bosch']
TIPOS_PESSOA = ['CLT', 'Terceiro', 'Posto', 'A confirmar']
TERMOS = ['Pendente', 'Assinado', 'Dispensado']
ETAPAS = ['Reservado', 'Termo assinado', 'Chamado aberto', 'Entregue', 'Cancelado']
MOTIVOS = ['Desligamento', 'Troca de máquina', 'Troca de aparelho', 'Fim do empréstimo', 'Roubo/furto', 'Perda',
           'Defeito sem conserto', 'Descarte', 'Doação', 'Venda', 'Devolvido à locadora', 'Outro']
STATUS_MANUT = ['No lab aguardando', 'Aguardando peça', 'Visita agendada', 'Enviado ao fornecedor', 'Em reparo',
                'Concluída', 'Sem conserto']
FORNEC_MANUT = ['Dell', 'Lenovo', 'BTB', 'Zebra', 'Reis Office', 'Interno', 'Outro']
OPERADORAS = ['Vivo', 'Claro', 'TIM', 'Outra']
TIPOS_CHIP = ['eSIM', 'Físico']
ESTADOS_DEV = ['Bom', 'Com avaria']
PRAZOS = [30, 60, 90]
STATUS_COMPRA = ['Em cotação', 'Aguardando aprovação', 'Pedido feito', 'Em trânsito', 'Recebido', 'Cancelado']

# Situações que um item pode ter (calculadas, nunca digitadas)
SITUACOES = ['Em estoque', 'Reservada', 'Em uso', 'Emprestado', 'Pendente devolução', 'Em trânsito para o EC',
             'Devolvido', 'Em preparação', 'Manutenção', 'Em transferência', 'A localizar', 'Aguardando baixa',
             'Baixada', 'Sem movimentação']
SITUACOES_LINHA = ['Livre', 'Em uso', 'Cancelada']
# Situações em que o item está com alguém
COM_PESSOA = ('Reservada', 'Em uso', 'Emprestado', 'Pendente devolução')


class Usuario(db.Model):
    """Quem entra no sistema (equipe de TI). Não confundir com Pessoa (quem recebe ativos)."""
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    senha_hash = db.Column(db.String(255), nullable=False)
    perfil = db.Column(db.String(20), nullable=False, default='Operador')   # PERFIS
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    senha_provisoria = db.Column(db.Boolean, nullable=False, default=False)
    tema = db.Column(db.String(10), nullable=True)
    login_tentativas = db.Column(db.Integer, nullable=False, default=0)
    login_bloqueado_ate = db.Column(db.DateTime, nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.now)


# Perfis e o que cada um faz. Lista fechada: o sistema não tem tela para criar perfis,
# o que mantém a regra explicável em uma frase.
PERFIS = {
    'Administrador': 'Tudo, inclusive usuários e configurações',
    'Operador': 'Consulta e lançamentos (entrega, devolução, estoque, manutenção, linhas)',
    'Consulta': 'Só consulta',
}


class LogAuditoria(db.Model):
    __tablename__ = 'logs_auditoria'
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, default=datetime.now, index=True)
    usuario = db.Column(db.String(100))
    acao = db.Column(db.String(60))
    detalhe = db.Column(db.Text)


class Pessoa(db.Model):
    """Quem recebe ativos: CLT (ID = matrícula), terceiro (T-xxxx) ou posto (P-xxxx)."""
    __tablename__ = 'pessoas'
    id = db.Column(db.String(30), primary_key=True)
    nome = db.Column(db.String(150), nullable=False, index=True)
    tipo = db.Column(db.String(20))
    empresa = db.Column(db.String(100))
    cpf = db.Column(db.String(14))
    jde = db.Column(db.String(30))
    cc = db.Column(db.String(60))
    cargo = db.Column(db.String(100))
    site = db.Column(db.String(30))
    user = db.Column(db.String(60))
    email = db.Column(db.String(120))
    situacao = db.Column(db.String(20), default='Ativo')
    obs = db.Column(db.Text)


class Item(db.Model):
    """Um equipamento. O código é a plaqueta; sem plaqueta, a service tag; celular, o IMEI 1."""
    __tablename__ = 'itens'
    codigo = db.Column(db.String(60), primary_key=True)
    categoria = db.Column(db.String(30), index=True)
    fabricante = db.Column(db.String(40))
    modelo = db.Column(db.String(100))
    plaqueta = db.Column(db.String(30))
    tag = db.Column(db.String(60), index=True)
    hostname = db.Column(db.String(60))
    imei1 = db.Column(db.String(20), index=True)
    imei2 = db.Column(db.String(20))
    eid = db.Column(db.String(60))
    propriedade = db.Column(db.String(20))
    fornecedor = db.Column(db.String(60))
    finalidade = db.Column(db.String(30))
    compativel = db.Column(db.String(30))
    area = db.Column(db.String(60))
    cc = db.Column(db.String(60))
    site = db.Column(db.String(30))
    ativo_jde = db.Column(db.String(30))
    nf = db.Column(db.String(40))
    data_nf = db.Column(db.String(10))
    valor = db.Column(db.Float)
    capex = db.Column(db.String(10))
    garantia = db.Column(db.String(10))
    pedido = db.Column(db.String(30))
    fonte = db.Column(db.String(60))
    teclado = db.Column(db.String(60))
    contrato = db.Column(db.String(40))
    origem = db.Column(db.String(80))
    obs = db.Column(db.Text)
    # cache calculado (app.regras.recalcular_item)
    situacao = db.Column(db.String(30), index=True, default='Sem movimentação')
    com_quem = db.Column(db.String(150))
    matricula = db.Column(db.String(30), index=True)
    linha_atual = db.Column(db.String(11))
    desde = db.Column(db.String(10))
    prazo = db.Column(db.String(10))
    termo = db.Column(db.String(20))
    etapa = db.Column(db.String(20))
    ultima_mov_id = db.Column(db.Integer)
    kit = db.Column(db.String(20))


class Linha(db.Model):
    __tablename__ = 'linhas'
    numero = db.Column(db.String(11), primary_key=True)
    operadora = db.Column(db.String(20))
    regional = db.Column(db.String(30))
    tipo_chip = db.Column(db.String(10))
    iccid = db.Column(db.String(30))
    cc = db.Column(db.String(60))
    plano = db.Column(db.String(60))
    obs = db.Column(db.Text)
    # cache calculado (app.regras.recalcular_linha)
    situacao = db.Column(db.String(20), index=True, default='Livre')
    com_quem = db.Column(db.String(150))
    matricula = db.Column(db.String(30))
    aparelho = db.Column(db.String(60))
    desde = db.Column(db.String(10))
    ultima_mov_id = db.Column(db.Integer)


class Movimentacao(db.Model):
    """Um lançamento do Histórico. Nunca é apagado por usuário comum: correções viram
    novos lançamentos, edição de campos de papelada (termo, chamado, datas) ou o
    Desfazer do último lote (que apaga o lote inteiro e fica na auditoria)."""
    __tablename__ = 'movimentacoes'
    id = db.Column(db.Integer, primary_key=True)          # = Nº da planilha
    data = db.Column(db.String(10), index=True)
    tipo = db.Column(db.String(30), index=True)
    item = db.Column(db.String(60), index=True)
    linha = db.Column(db.String(11), index=True)
    matricula = db.Column(db.String(30), index=True)
    nome = db.Column(db.String(150))
    cc = db.Column(db.String(60))
    local = db.Column(db.String(100))
    etapa = db.Column(db.String(20))
    termo = db.Column(db.String(20))
    data_ass = db.Column(db.String(10))
    chamado = db.Column(db.String(30))
    data_ent = db.Column(db.String(10))
    prazo = db.Column(db.String(10))
    motivo = db.Column(db.String(60))
    bo = db.Column(db.String(40))
    resp = db.Column(db.String(100))
    tecnico = db.Column(db.String(100))
    obs = db.Column(db.Text)
    acess = db.Column(db.String(60))
    fonte_dev = db.Column(db.String(5))
    mouse_dev = db.Column(db.String(5))
    teclado_dev = db.Column(db.String(5))
    estado = db.Column(db.String(20))
    receb_por = db.Column(db.String(100))
    link = db.Column(db.String(500))
    reg_em = db.Column(db.String(25))
    lote = db.Column(db.String(40), index=True)


class Manutencao(db.Model):
    __tablename__ = 'manutencoes'
    id = db.Column(db.Integer, primary_key=True)          # = OS
    item = db.Column(db.String(60), index=True)
    defeito = db.Column(db.String(200))
    abertura = db.Column(db.String(10))
    chamado = db.Column(db.String(30))
    fornecedor = db.Column(db.String(40))
    caso = db.Column(db.String(40))
    status = db.Column(db.String(30))
    visita = db.Column(db.String(25))
    site = db.Column(db.String(30))
    tecnico = db.Column(db.String(100))
    enviado = db.Column(db.String(10))
    retorno = db.Column(db.String(10))
    solucao = db.Column(db.Text)
    pecas = db.Column(db.String(200))
    custo = db.Column(db.Float)
    substituto = db.Column(db.String(60))
    obs = db.Column(db.Text)

    @property
    def aberta(self):
        return self.status not in ('Concluída', 'Sem conserto')


class Consumivel(db.Model):
    """Catálogo de consumíveis (fonte, mouse, teclado, headset...). Saldo é calculado dos movimentos."""
    __tablename__ = 'consumiveis'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)   # "Item – Marca"
    item = db.Column(db.String(80))
    marca = db.Column(db.String(60))
    compativel = db.Column(db.String(30))
    minimo = db.Column(db.Integer)


class MovConsumivel(db.Model):
    __tablename__ = 'mov_consumiveis'
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.String(10))
    consumivel = db.Column(db.String(120), index=True)
    site = db.Column(db.String(30))
    movimento = db.Column(db.String(20))      # Entrada | Saída | Ajuste
    qtd = db.Column(db.Integer)
    destino = db.Column(db.String(150))
    chamado = db.Column(db.String(30))
    compra = db.Column(db.String(30))
    resp = db.Column(db.String(100))
    obs = db.Column(db.Text)
    mov_id = db.Column(db.Integer, index=True)   # lançamento do Histórico que gerou (baixa do kit)
    lote = db.Column(db.String(40), index=True)


class EmprestimoAcessorio(db.Model):
    __tablename__ = 'emprestimos_acessorio'
    id = db.Column(db.Integer, primary_key=True)    # Nº EA-
    data = db.Column(db.String(10))
    consumivel = db.Column(db.String(120))
    qtd = db.Column(db.Integer)
    matricula = db.Column(db.String(30))
    nome = db.Column(db.String(150))
    cc = db.Column(db.String(60))
    prazo = db.Column(db.String(10))
    chamado = db.Column(db.String(30))
    resp = db.Column(db.String(100))
    obs = db.Column(db.Text)
    devolvido = db.Column(db.String(10))
    receb = db.Column(db.String(100))
    obs_dev = db.Column(db.Text)
    lote = db.Column(db.String(40))


class Compra(db.Model):
    __tablename__ = 'compras'
    id = db.Column(db.Integer, primary_key=True)
    compra = db.Column(db.String(30), unique=True)    # CP-0001
    data_pedido = db.Column(db.String(10))
    tarefa = db.Column(db.String(40))
    solicitante = db.Column(db.String(100))
    categoria = db.Column(db.String(40))
    descricao = db.Column(db.String(200))
    qtd = db.Column(db.Integer)
    status = db.Column(db.String(30))
    previsao = db.Column(db.String(10))
    pedido = db.Column(db.String(40))
    po = db.Column(db.String(40))
    cc = db.Column(db.String(60))
    conta = db.Column(db.String(40))
    aprovador = db.Column(db.String(100))
    capex = db.Column(db.String(10))
    valor_unit = db.Column(db.Float)
    nf = db.Column(db.String(40))
    data_nf = db.Column(db.String(10))
    recebido = db.Column(db.String(10))
    obs = db.Column(db.Text)


class Contrato(db.Model):
    __tablename__ = 'contratos'
    id = db.Column(db.Integer, primary_key=True)
    contrato = db.Column(db.String(40), unique=True)
    locadora = db.Column(db.String(60))
    descricao = db.Column(db.String(200))
    inicio = db.Column(db.String(10))
    fim = db.Column(db.String(10))
    padrao = db.Column(db.String(5))
    valor = db.Column(db.Float)
    obs = db.Column(db.Text)


class AnaliseLinha(db.Model):
    """Uma linha de uma rodada da conferência Easy × Zelo × AirWatch. 'quem_atendeu' e 'retorno' a equipe preenche."""
    __tablename__ = 'analise_linhas'
    id = db.Column(db.Integer, primary_key=True)
    rodada = db.Column(db.String(25), index=True)
    numero = db.Column(db.String(11), index=True)
    operadora = db.Column(db.String(20))
    conta = db.Column(db.String(30))
    usuario_easy = db.Column(db.String(150))
    cc_easy = db.Column(db.String(60))
    sem_consumo = db.Column(db.Boolean, default=False)
    sit_mb = db.Column(db.String(30))
    com_quem = db.Column(db.String(150))
    easy_x_mb = db.Column(db.String(60))
    aw_visto = db.Column(db.String(60))
    aw_aparelho = db.Column(db.String(120))
    aw_usuario = db.Column(db.String(150))
    aw_modelo = db.Column(db.String(80))
    decisao = db.Column(db.String(40), index=True)
    motivo = db.Column(db.String(300))
    acao = db.Column(db.String(300))
    quem_atendeu = db.Column(db.String(150))
    retorno = db.Column(db.String(300))


class Config(db.Model):
    """Parâmetros (chave/valor): prazo padrão de empréstimo, data do fluxo de preparação etc."""
    __tablename__ = 'config'
    chave = db.Column(db.String(40), primary_key=True)
    valor = db.Column(db.String(200))


CONFIG_PADRAO = {
    'empresa': 'Martin Brower Brasil',
    'prazo_emprestimo': '30',
    'fluxo_preparacao': '2026-11-05',     # notebook devolvido a partir daqui passa pela preparação
    'dias_fluxo_parado': '7',
    'aviso_contrato_dias': '90',
    'equipe': 'Gabriel;Giselly Oliveira;Adriano Santos;Daniely Reis',
    'tecnicos': 'Diogo Mariano;Adriano Santos;Emilly Cosmo;Edvaldo Filho;Thomaz Jardim;Lucas Rodrigues;Michel Santos;Lara Vitoriano',
    'recebido_por': 'Adriano Santos;Diogo Mariano',
}


def cfg(chave):
    c = db.session.get(Config, chave)
    return c.valor if c and c.valor is not None else CONFIG_PADRAO.get(chave)


def cfg_lista(chave):
    return [x.strip() for x in (cfg(chave) or '').split(';') if x.strip()]
