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

## Feito em 11/11 (v1.5.0), a pedido do Gabriel
- Quadro das entregas com 2 colunas (Reservado → Entregue); termo e chamado são marcas no cartão.
- Termo assinado guardado no próprio Zelo (instance/termos, vai no backup); a ideia de "link" foi abandonada.
- Termo assinado vai ao chamado pela fila do Service Desk (reenviável); informar o chamado depois leva o termo junto.
- "Ajustar cadastro" (v1.7.0): corrige quem está com o item / situação / linha no aparelho; entra no Histórico
  como tipo "Ajuste" com motivo e autor, sem inventar movimentação. Botão na ficha do item e da linha.

## Etapa 5 — Assinatura digital do termo (FEITA, v1.9.0)
Decidido com o Gabriel: a pessoa abre o Zelo e assina na tela — caneta ou dedo no tablet, mouse no
notebook. São DUAS vias: a de quem recebe e a de quem responde pela empresa (Giselly ou Sato), que é a
que libera o ativo. Quem não está presencial recebe um link e assina de onde estiver.

- **Quadro de assinatura** com Pointer Events (caneta, dedo e mouse pelo mesmo caminho), desenhado na
  resolução real da tela e com traço suavizado; desfazer traço e limpar; o PNG vai recortado no desenho.
- **Link por via**: token de 32 bytes, para um único termo e uma única via, com validade em dias
  (`dias_link_assinatura`). A página não exige login e mostra só aquele termo. Serve para os dois casos:
  abrir no tablet do balcão ou mandar para quem está fora.
- **Registro**: nome confirmado, data, hora, IP, navegador e o **hash do texto do termo**. Se o lançamento
  for corrigido depois, o hash deixa de bater e o Zelo avisa que o papel assinado não é mais o mesmo.
- **Com as duas vias**, o Zelo monta o PDF com os dois desenhos e o bloco de conferência (quem, quando, IP,
  código da via), guarda no mesmo lugar do termo digitalizado, marca o termo como Assinado e manda ao
  chamado do Service Desk.
- **Assinar no papel continua valendo**: anexar o termo digitalizado encerra os pedidos em aberto. As duas
  formas convivem na mesma tela.
- **Cobrança**: via pedida e não assinada vira lembrete no Painel e seção em Minha fila.
- `url_base` em Configurações: sem ele, o link copiado sai com o endereço do navegador e só funciona na
  máquina de quem copiou. O painel avisa quando isso acontece.
- Decidido: o Zelo não dispara e-mail. O link é copiado ou compartilhado pelo botão Enviar, e quem precisar
  mandar por e-mail manda na mão.

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

---

# Levantamento: onde a API do Service Desk pode render mais (nov/2026)

Pedido do Gabriel: entender como aproveitar a integração ao máximo. Abaixo, o que já funciona, o
que dá para fazer, e a decisão que precisa vir antes de tudo.

## O que já está ligado hoje
| O quê | Quando acontece | Precisa de |
|---|---|---|
| Lê o chamado na conferência em tempo real (solicitante, assunto, status) | ao digitar o Nº no lançamento | `sd_ativo=Sim` |
| Anexa o PDF do termo ao chamado + grava nota | lançamento com Nº de chamado | idem |
| Anexa o termo **assinado** e nota | quando as duas vias assinam, ou ao anexar o digitalizado | idem |
| Põe o ativo **In Use** com o usuário | Entrega/Empréstimo marcados como Entregue | `sd_ativos=Sim` + item com **hostname** |
| Põe o ativo **In Store** e tira o usuário | Devolução (inclusive pela fila do desligamento) | idem |

Limites conhecidos, provados no laboratório (SDP 16 on-premises):
- o ativo é achado pelo **hostname** (`name`), então item sem hostname no Zelo não sincroniza;
- o usuário é achado por **e-mail**; sem e-mail, pelo nome exato, e só se for único. É a causa nº 1
  de erro na fila — ver oportunidade **B**;
- `PUT /api/v3/asset_assets/{id}` funciona; o formato em lote (`?ids=`) devolve "Internal Error".
  Toda escrita é um ativo por chamada, logo tudo que for em massa tem que ser fila, não botão síncrono;
- a documentação pública fala em `/api/v3/assets`; o que responde nesse build é `/api/v3/asset_assets`.
  Qualquer endpoint novo daqui precisa de um teste no laboratório antes de virar promessa.

## A decisão que vem antes de tudo: quem é dono de qual campo
A base do SD vem do agente e do AD. A do Zelo vem da planilha. Elas vão discordar muito no primeiro
encontro, e sem regra de dono a sincronização fica trocando os dados de um lado para o outro.
Proposta:

| Campo | Dono | Por quê |
|---|---|---|
| hostname, service tag, serial, modelo, SO, memória, disco | **Service Desk** (agente) | a máquina se descreve sozinha, melhor que digitação |
| com quem está, estado (In Use/In Store), plaqueta, CC, site, finalidade, contrato, garantia, propriedade | **Zelo** | é o que o processo de entrega controla, e o que a planilha sempre controlou |
| nome e e-mail da pessoa | **Service Desk/AD** só para achar o usuário | cargo, CC e matrícula do AD não são confiáveis (decisão do Gabriel) |

Com isso: importar do SD preenche só o que está **vazio** no Zelo e nunca sobrescreve o que foi
completado à mão; e o Zelo escreve no SD só os campos de que é dono.

## Oportunidades, da que mais rende para a que menos
**A + D. Ativos × Service Desk** — FEITAS (v1.11.0), em Itens → Conferir com o Service Desk
Uma busca responde as duas perguntas, então moram na mesma tela. Casa por hostname, depois service
tag, depois plaqueta. Grupos: falta no Zelo (cadastrar, opt-in), completa o cadastro (só campo vazio),
**quem está com ele difere**, **situação difere**, dado diferente, cadastro repetido no Zelo, e só no
Zelo (apenas máquina com hostname — monitor e celular nunca estiveram no SD).
Nada é corrigido sozinho: divergência de pessoa ou situação leva ao Ajustar cadastro, e quem decide é
você. Chave que aponta para dois itens do Zelo não vira palpite: vira o grupo "cadastro repetido".

**B. Importar pessoas do SD** — FEITA (v1.10.0), em Pessoas → Importar do Service Desk
Decisão do Gabriel: as pessoas vêm do Service Desk, não do AD direto — é a mesma base e o SD já tem
API. Traz nome, e-mail e login, nada mais. Casa por e-mail e, na falta dele, por nome exato e único;
nome repetido vira escolha na tela, nunca palpite. O e-mail só entra onde está vazio (divergência
fica num grupo à parte que você marca de propósito) e o login só onde o Zelo não tem nenhum.
Cadastrar quem não está no Zelo é opt-in linha a linha, com matrícula provisória SD-NOME.

**C. O Zelo escrever no SD o que ele sabe melhor** — FEITA (v1.13.0)
Dois interruptores separados em Administração → Service Desk, os dois desligados de fábrica:
- **Cadastrar o ativo quando ele não existir lá** (v1.14.0 depois do teste no laboratório): em vez de a fila dar erro "ativo não existe", o
  Zelo cria com hostname, service tag, plaqueta, site, fornecedor, garantia e tipo de produto.
  Mandar hostname e service tag é o que faz o agente, quando for instalado, casar com este registro
  em vez de duplicar (a service tag é o primeiro critério de casamento do SDP). Não manda `product`:
  o modelo teria que existir como produto cadastrado no SDP, e inventar um derruba a chamada inteira.
- **Corrigir os campos que são do Zelo**: em ativo que já existe, escreve `asset_tag`, `site`,
  `vendor` e `warranty_expiry` a cada sincronização. Hostname, service tag e modelo nunca — é a
  regra de dono da tabela acima. Ligar isto é passar a sobrescrever o que alguém pôs à mão no SD,
  então só depois de a tela Conferir mostrar que o Zelo está confiável nesses campos.

Campo vazio no Zelo fica **fora** do corpo da chamada: no SDP mandar nulo apaga o que está lá,
não mandar o campo deixa como está.

**`asset_assets` NÃO cria ativo** (provado no laboratório, 13/nov): o POST devolve
`HTTP 404 Cannot add asset under Asset product type`. A ManageEngine separou **um endereço por tipo
de produto** — `asset_computers` (ex-workstations), `asset_monitors`, `asset_printers`,
`asset_access_points`… — e o nome de cada um sai de `GET /api/v3/requests/assets/module`, no campo
`api_plural_name`. O Zelo **pergunta** em vez de carregar lista fixa: os tipos variam entre build e
entre instalação, e lista fixa é justamente o que produz aquele 404. O tipo de produto também
decide a chave do corpo (`asset_computers` → `{'asset_computer': {...}}`).

**Diagnóstico antes da promessa.** A documentação pública e este build não batem, então a criação
não entrou por fé: o botão **Diagnóstico: criar ativo** cria um `ZELO-TESTE-…` no Service Desk de
verdade, mostra campo por campo o que o build guardou, e apaga. Se a recusa citar um campo, o
relatório diz qual — e antes disso ele lista **os tipos de produto do seu Service Desk com o
endereço de cada um**, que é o que faltava para a criação funcionar. É o que separa "a API suporta"
de "o nosso SDP aceita"; foi esse botão que achou o 404 acima em um minuto.

**E + F. Ciclo completo do ativo** — FEITAS (v1.12.0)
O estado no SD passou a sair da **situação atual do item**, não do tipo de lançamento: Em uso,
Emprestado, Pendente devolução e Reservada → `In Use`; Em estoque, Devolvido, Em preparação →
`In Store`; Manutenção → `In Repair`; Baixada → `Expired`. Situação sem equivalente (Em trânsito,
Em transferência, A localizar, Aguardando baixa) **não mexe no estado** — melhor um estado velho que
um estado mentiroso. O mapa é editável em Administração → Service Desk (`Situação = Estado`, um por
`;`; valor vazio = não mexer), para o caso de os estados de lá terem outro nome.
Manutenção e Ajustar cadastro mudam a situação sem gerar movimentação, então entram na fila por
`enfileirar_item`, que não duplica pendência do mesmo hostname.
Anexar o ativo **dentro do chamado** (não só na nota) é um liga-desliga na mesma tela: lê os ativos
que já estão no chamado e acrescenta, porque o PUT substitui a lista inteira. Se falhar, a nota e o
termo valem do mesmo jeito.

**G. Abrir chamado a partir do Zelo** (`POST /api/v3/requests`)
Casos que valem: recolhimento no desligamento (um chamado com a lista do que a pessoa tem), abertura
de manutenção com o ativo anexado, e devolução pendente que ninguém atende. Precisa combinar
template, categoria e grupo antes.

**H. Service tag quando vem vazia no SD**
Já estava na lista: o Zelo preenche o que a planilha tem. Depende de testar o endereço do tipo
Computador no laboratório.

**I. Garantia e contrato vindos do SD**
`warranty_expiry`, `vendor`, `acquisition_date`, `purchase_cost` alimentam os lembretes de garantia
vencendo que o Painel já mostra.

**J. Ordens de compra** (`/api/v3/purchase_orders`)
Leitura do que está comprado e ainda não chegou, para dar entrada no estoque. Prioridade baixa: a
decisão do Gabriel é que compra e rollout vão para o Jira.

## Ordem sugerida
1. **B** (pessoas/e-mail) — destrava o que já existe e quebra hoje.
2. **A** (importar ativos) — o pedido, e base para o resto.
3. **D** (reconciliação) — mostra o tamanho real do problema antes de automatizar correção.
4. ~~**E** + **F**~~ — feitas.
5. ~~**C**~~ — feita, mas os dois interruptores nascem desligados: ligar depende da reconciliação
   mostrar que o Zelo é confiável naqueles campos.
6. **G**, **H**, **I** — conforme a necessidade aparecer.
