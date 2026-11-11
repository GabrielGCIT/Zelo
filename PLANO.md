# Zelo — plano de execução (acordado em 11/11/2026)

## Concluído
- Plano de 3 dias: base, importação (0 divergências), consultas, lançamentos com conferência, termo,
  Acompanhar, manutenção, consumíveis, conferência de linhas (Easy × Zelo × AirWatch), pacote Windows.
- Conferência em tempo real nos lançamentos (quem, o quê, o que conferir).
- Service Desk (provado no laboratório SDP 16): termo em PDF anexado + nota no chamado; solicitante na
  conferência; entrega/devolução atualizam usuário e estado do ativo (pelo hostname); fila com reenviar.
- Kit de mouse/teclado virou sugestão; devolução avulsa do kit na ficha da pessoa.
- Cadastro de ativo em Itens (não em Consumíveis). Pacote corrigido (greenlet, colorama). Versão 1.2.0.

## Descartado
- API do AirWatch (controle do time global): fica o upload do relatório.

## Etapa 1 — Lançamentos em cards + regras viram pendência (FEITA, v1.3.0)
- Tela inicial de lançamento com cards: Notebook e desktop · Celular e linha · Empréstimo do pool ·
  Acessório · Estoque e baixa. Cada card abre só os campos do caso, com a conferência em tempo real.
- Começar pelo item ou pela pessoa: digitar/bipar e ver só as ações possíveis para a situação.
- Botões de ação na ficha do item e da pessoa (Entregar, Devolver, Emprestar, Manutenção).
- Grade atual permanece como "Lançamento em lote" (rollout, inventário).
- Pendências: campo "incompleto" no lançamento + lista "Minhas pendências" (fila e painel). Deixam de
  bloquear: Recebido por, Nº do chamado para avançar etapa, 6 marcas da preparação, "o que foi feito" na
  manutenção. Continua bloqueando só integridade (item inexistente, com outra pessoa, saldo).
- Corrigir qualquer campo de qualquer lançamento na tela, com antes → depois na auditoria; desfazer o
  último lançamento de cada item.
- Rever com o Gabriel os outros pontos "ao pé da letra da planilha" que ele ainda vai trazer.

## Etapa 2 — Quadros de arrastar (FEITA, v1.4.0)
- Acompanhar: Reservado → Termo assinado → Chamado aberto → Entregue (arrastar o card avança a etapa).
- Preparação: Devolvido → Em preparação → Liberado, com as marcas salvando sozinhas.
- Manutenção: quadro por status da OS.

## Etapa 3 — Painel e fichas
- Pedido do Gabriel (11/11): o sistema tem de APONTAR o que está errado (cadastro, lançamento) e INDUZIR o
  fluxo certo; aparência conta; seguir o melhor padrão de mercado. Incluir "Qualidade do cadastro":
  pessoas duplicadas/sem CC/tipo "A confirmar", itens sem hostname/tag, em uso sem termo, desligado com item,
  linha em uso sem aparelho, lançamentos sem data — cada achado com o botão que resolve.
- Gráficos clicáveis: parque por situação e site, entregas/devoluções por semana, idade do parque,
  garantias vencendo, estoque EC × mínimo, tempo médio reserva → entrega.
- Ficha do item com linha do tempo (pessoas, manutenções); ficha da pessoa em cards.
- Visual: transições, respostas visuais, estados vazios, tema claro/escuro consistente.

## Etapa 4 — Agilidade
- Bipar código de barras/QR da plaqueta para entregar e devolver; etiqueta para imprimir.
- Lembretes automáticos: empréstimo vencendo, termo pendente, pendências antigas.
- Busca global com atalho (Ctrl+K) que também executa ações.
- Ações em lote na lista de itens (devolver vários, mudar site, separar para baixa).
- Fila única de devolução no desligamento.

## Etapa 5 — Aceite digital do termo (aprovado pelo Gabriel)
- Link de aceite para a pessoa, registro de quem/quando/IP, PDF assinado anexado ao chamado e ao
  lançamento; termo passa a Assinado sozinho. Definir com o Gabriel: aceite por link interno ou e-mail.

## Encaixes pendentes (sem etapa fixa)
- Gabriel terminar o teste de ponta a ponta no laboratório (entrega com chamado → anexo, nota, ativo).
- Service Desk: preencher a service tag quando vazia (testar o endereço do tipo Computador no laboratório).
- Publicar no GitHub: Gabriel cria GabrielGCIT/zelo; aí subir os commits.
- Login com a conta Microsoft. Admissões.
- JDE como fonte de colaboradores (CPF, nome, matrícula, código JDE) — depende de o Gabriel conseguir a API.
  Terceiros: cadastro próprio no Zelo (CPF, empresa, fim de contrato).
- Jira: compras e rollout obrigatórios lá (chave do card na compra) — quando houver uso do Jira.
- Linhas: base de centro de custo (Gabriel traz), validação da Easy nas contas Claro 196073995 e
  196074081, pedidos de bloqueio.
- Virada: importar a planilha mais recente no dia; 3106 lançamentos antigos sem data vêm assim da planilha.
