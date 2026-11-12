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

## Etapa 3 — Painel e fichas (FEITA, v1.6.0)
- Pedido do Gabriel (11/11): o sistema tem de APONTAR o que está errado (cadastro, lançamento) e INDUZIR o
  fluxo certo; aparência conta; seguir o melhor padrão de mercado. Incluir "Qualidade do cadastro":
  pessoas duplicadas/sem CC/tipo "A confirmar", itens sem hostname/tag, em uso sem termo, desligado com item,
  linha em uso sem aparelho, lançamentos sem data — cada achado com o botão que resolve.
- Gráficos clicáveis: parque por situação e site, entregas/devoluções por semana, idade do parque,
  garantias vencendo, estoque EC × mínimo, tempo médio reserva → entrega.
- Ficha do item com linha do tempo (pessoas, manutenções); ficha da pessoa em cards.
- Visual: transições, respostas visuais, estados vazios, tema claro/escuro consistente.

## Etapa 4 — Agilidade (FEITA, v1.8.0)
- **Bipar**: tela com fila. Escolhe a ação uma vez (devolver, entregar, reservar, enviado ao EC, pedir
  devolução, entrada no estoque, outro site, separar para baixa) e bipa tudo; cada leitura confere na hora
  pelo mesmo motor dos lançamentos e grava num lote só. Campo comum vai só onde cabe, então notebook e
  celular entram na mesma devolução. Modo "Conferir prateleira" não grava: compara o bipado com o que o
  Zelo diz que está no site e lista o que não foi bipado.
- **Etiqueta** com código de barras (Code 128 da plaqueta), 3 por linha em A4, com nº de vias. O código
  foi conferido módulo a módulo contra a tabela padrão, para o leitor bipar de primeira.
- **Busca rápida (Ctrl+K)** em qualquer tela: item, pessoa, linha, Nº do lançamento e nome de tela.
  Tab abre as ações que cabem na situação daquele item — bipar a plaqueta e devolver sem abrir ficha.
- **Lembretes** no alto do Painel e número ao lado de Minha fila: só o que passou do prazo (empréstimo
  vencido, devolução cobrada, reserva e preparação paradas, termo não assinado, lançamento incompleto,
  desligado com equipamento, OS parada, erro no envio ao Service Desk, estoque mínimo, garantia e
  contrato vencendo). Cada prazo é ajustável em Configurações (`lembrete_*`).
- **Ações em lote** na lista de Itens: marca vários (Shift marca o intervalo) e manda para a fila de
  bipagem, ou imprime as etiquetas dos marcados.
- **Desligamentos**: lista de quem saiu e ainda consta com alguma coisa, e uma fila por pessoa que
  devolve equipamento, linha, kit do EC e acessório emprestado de uma vez, com motivo Desligamento.
- Falta combinar: lembrete por e-mail precisa de um relay SMTP interno — hoje o Zelo cobra na tela.

## Feito em 11/11 (v1.5.0), a pedido do Gabriel
- Quadro das entregas com 2 colunas (Reservado → Entregue); termo e chamado são marcas no cartão.
- Termo assinado guardado no próprio Zelo (instance/termos, vai no backup); a ideia de "link" foi abandonada.
- Termo assinado vai ao chamado pela fila do Service Desk (reenviável); informar o chamado depois leva o termo junto.
- "Ajustar cadastro" (v1.7.0): corrige quem está com o item / situação / linha no aparelho; entra no Histórico
  como tipo "Ajuste" com motivo e autor, sem inventar movimentação. Botão na ficha do item e da linha.

## Etapa 5 — Aceite digital do termo (aprovado pelo Gabriel)
- O PDF aceito deve ser gravado no mesmo lugar do termo assinado (termo_arquivo).
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
