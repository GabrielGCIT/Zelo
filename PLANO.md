# Zelo — plano de execução (acordado em 11/11/2026)

---

## ONDE PARAMOS — 18/11/2026, v1.31.0

Leia esta seção primeiro. O resto do arquivo é histórico e decisões; isto é o que está na mesa.

**Foco desde 18/11: desenvolver** (funcionalidade, integração com o SD, bugs). O servidor só entra
na pauta quando o Gabriel avisar. Fluxo: alteração e commit na máquina dele, `git pull` e teste
no servidor. A suíte roda local com `ZELO_PLANILHA_TESTE` apontando para a planilha atual.

### O nome que o agente dá à máquina tem domínio (18/11, v1.31.0)
O ativo que o agente criou na MB chama-se `lmbbfyp9nq3.reyesholdings.com`; nenhum dos 1051
hostnames do Zelo tem domínio. O Zelo procurava com `name is <hostname>`, então **toda máquina
com agente parecia inexistente**: a entrega e a devolução dariam "ativo não existe" na fila, e a
conferência só casava porque caía na service tag. Não houve estrago porque os interruptores de
escrita estão desligados no servidor.

- `achar_ativo` tenta o nome exato, depois `starts with` `<curto>.`, depois a service tag (no
  campo do apelido, `service_tag` na MB). Mais de um candidato é erro, não escolha.
- conferência e "Repetido no Service Desk" comparam pelo nome curto (`host_curto`); o hostname
  que vem do SD entra curto no Zelo.
- o ativo vai para dentro do chamado pelo **id**, não pelo nome.

**Provado no laboratório (18/11):** o build aceita `starts with` (`ZELO-TESTE-x.LAB.LOCAL` achado
por `ZELO-TESTE-x.`, e `achar_ativo` pelo nome curto); anexar ao chamado por `{'id': ...}` grava
e preserva o ativo que já estava lá.

### Cobertura do agente (18/11, v1.31.0)
Seção nova em Itens → Conferir com o Service Desk, para notebook, desktop e thin client em uso:
- **Entregue e sem agente** — não está no SD, ou só como cadastro manual nunca varrido, depois de
  `dias_sem_agente` (7) da entrega;
- **Agente parou de ver** — `last_scan_success_time` mais velho que `dias_agente_sumido` (30);
- **Quem usa difere** — `last_logged_user` sem domínio ≠ login (`Pessoa.user`) de quem o Zelo diz
  estar com a máquina, ou login recente numa máquina que o Zelo diz estar em estoque.

A listagem passou a pedir os dois campos do agente num degrau à parte: se o build recusar, cai
para os campos de sempre em vez de perder a service tag. Quando nenhum ativo trouxer os campos, a
tela diz isso em vez de mostrar grupo vazio.

**Achado no laboratório (18/11): `fields_required` aceita QUALQUER nome**, até um inventado, e a
resposta traz só os campos pedidos que têm valor. Duas consequências:
- "aceitou" não prova que `last_logged_user` e `last_scan_success_time` são os nomes certos — o
  laboratório não tem agente, então **só a MB prova**, pela primeira conferência depois que houver
  máquina com agente. Se a seção disser "não devolveu data de varredura" com agente instalado,
  os nomes estão errados: olhar a ficha pelo Inspecionar;
- a presença da chave é um sinal confiável de que o agente esteve no ativo, que é o que separa
  "cadastro manual nunca varrido" de "este build não entrega o campo".
O simulador passou a se comportar assim.

### Armadilha paga: MATCH exato não casa número com texto (18/11)
Ele lançou a devolução do notebook 7080 e a Categoria saiu "⚠ item não cadastrado". O Excel guardou
`7080` como número e `MATCH(7080, tItens[Código], 0)` não acha o código "7080", que é texto. A
situação até saía certa, porque a coluna Chave item já convertia com `&""` — a planilha dizia que o
item não existia e ao mesmo tempo mexia nele.

Convertidos 20510 MATCH da planilha para procurar texto (`valor&""`), em todas as colunas-chave
que alguém digita: código de item, matrícula, número de linha, plaqueta, service tag, hostname,
IMEI. Formatar a coluna como texto não resolveria: formato não impede o Excel de guardar número.

O Zelo nunca teve esse problema — `importar._valor` converte para string antes de comparar. Quem
mexer nas fórmulas da planilha tem de manter o `&""`.

### Item cadastrado sem lançamento agora é "Em estoque" (18/11)
Cadastrar uma máquina na planilha não a punha no Estoque: sem lançamento a situação era
"Sem movimentação". Máquina cadastrada está no armazém, então a situação passa a ser "Em estoque",
nos dois lados (`regras.py` e a coluna Situação da aba Itens). A situação
"Sem movimentação" saiu de `SITUACOES` e de `_POR_SITUACAO`.

O que ela sinalizava não foi perdido: `qualidade.itens_sem_movimentacao` agora procura item sem
nenhuma `Movimentacao` em vez de item com aquela situação, e diz o que importa — aparece como
"Em estoque" porque nada foi lançado, não porque alguém o viu lá.

### Nome e centro de custo vêm da matrícula (18/11)
A coluna Nome do Histórico era digitada: quem preenchia era o Office Script, que saiu com as abas
"Lançar". Virou fórmula em todas as linhas (as 3040 linhas com matrícula casam todas com o
cadastro, nenhuma ficou órfã); matrícula fora do cadastro mostra "⚠ pessoa não cadastrada".

Centro de custo recebeu a fórmula **só nas 3535 linhas que estavam vazias**: em 113 lançamentos o
CC digitado difere do CC atual da pessoa e está certo — é o CC de quando a movimentação aconteceu.
Sobrescrever seria reescrever o histórico.

Limpados também os 213 nomes marcados com "EX"/"- EX" no cadastro (sobra da planilha antiga), que
agora ficam como Desligado. Sem isso a fórmula do Nome passaria a mostrar "JOÃO - EX" no histórico
inteiro dessas pessoas.

### Devolução volta direto para o estoque (18/11) — simplificação pedida pelo Gabriel
O fluxo obrigatório de preparação saiu de cena: notebook devolvido ia para "Devolvido" e só voltava
ao estoque depois de lançar **Preparação** e **Liberação** — três lançamentos para registrar uma
máquina que voltou, e a Daniely não achava a máquina no Estoque depois de devolver.

- `fluxo_preparacao` agora vem **vazio** (= desligado) em `CONFIG_PADRAO`. Com uma data, o
  comportamento antigo volta inteiro: a tela Acompanhar, os lembretes e o quadro continuam no
  código, só não têm quem os alimente.
- o corte "quando o controle novo começou" (pendência de termo, acompanhamento) virou a constante
  `INICIO_FLUXO = '2026-11-05'` em `models.py`. Antes as duas coisas dividiam a mesma chave de
  configuração, e desligar uma mexia na outra.
- na planilha, a coluna *Situação do item* do Histórico perdeu o desvio do notebook e a linha
  "Fluxo de preparação vale a partir de" saiu do Config.
- `tests/conftest.py` ganhou a fixture `fluxo_preparacao`, que liga o fluxo nos testes que
  precisam dele. **A planilha e o Zelo seguem batendo: 0 itens e 0 linhas com situação diferente.**

### Cadastro do JDE importado (18/11)
Extração `Cadastro de usuários` (aba LISTAG, três linhas por cadastro: nome, departamento, R.G.).
3336 matrículas: 1145 já estavam na planilha e **2191 foram cadastradas**. Pessoas foi de 1798 para
3989. Terceiro não entra no JDE (não tem matrícula), então ausência no JDE nunca marca desligado.

- 40 nomes corrigidos pelo JDE, 201 "Cadastro JDE" preenchidos, 582 Sites preenchidos.
- 13 pessoas que a planilha tinha como ativas estão desligadas no JDE → marcadas Desligado.
  **9 delas têm equipamento no nome** (coluna Alerta), e isso agora é um cartão no Início.
- 20 divergem ao contrário (planilha diz desligado, JDE diz ativo): ninguém foi "ressuscitado",
  os casos estão no relatório para ele decidir.
- o cartão "pessoas sem e-mail" virou **"com ativo e sem e-mail"** (1386): com o quadro inteiro da
  empresa na base, o número cru não dizia nada — quase nenhum funcionário de CD tem e-mail.

### Estado
221 testes verdes. Tudo commitado e empurrado para `github.com/GabrielGCIT/Zelo` (privado).
A integração com o Service Desk lê chamado, anexa termo, grava nota, atualiza usuário e estado do
ativo, e **cria ativo** no SDP com hostname, service tag, plaqueta e estado — tudo provado gravando
no laboratório pelo botão de diagnóstico.

### O Zelo está instalado no servidor da MB (17–18/11)
Clonado do GitHub num servidor interno (`brdapp01`), apontando para o **SDP de produção**
(`https://servicedesk.martinbrower.com.br`) — a MB não tem SDP de teste. Integração ligada;
**todos os interruptores de escrita de ativo em Não**. Provado lá: conexão, listagem dos 27 tipos
de produto, e o **Inspecionar** lendo a ficha completa de um ativo.

Falta no servidor, por ordem:
1. `serial_number=service_tag` em "Nomes de campo próprios", e rodar o **Diagnóstico: criar ativo**
   para confirmar a criação (1 minuto; cria e apaga um `ZELO-TESTE-…` de verdade).
2. **Subir como serviço no boot.** Desde a v1.28.0 o repositório traz `instalar-servico.bat` e
   `servico-run.bat` na raiz. Falta rodar no servidor (como administrador) e **reiniciar** para
   provar o boot. Até lá o Zelo morre quando a janela fecha.
3. **Testar a restauração do backup.** O backup diário existe; restaurar nunca foi testado, e
   backup não testado não é backup.
4. **Ligar "anexar o equipamento ao chamado"** — com a base de ativos zerada, o histórico por ativo
   começa agora, e cada mês desligado é um mês perdido para sempre.

Pendências menores do servidor: `url_base` com o endereço real (senão o link de assinatura quebra),
SSL em **Verificar** (estava em Ignorar) e porta 5001 liberada no firewall.

### A criação de ativo está fechada (13/11, v1.23.0)
O que o Zelo descobriu sozinho sobre o build da MB, e que agora está gravado na configuração:

| O quê | Valor neste build |
|---|---|
| endereço de criação de Notebook | `/api/v3/asset_laptops` (não `asset_computers`) |
| produto | obrigatório e tem que já existir; o Zelo usa o do modelo, ou um do mesmo tipo |
| `product_type` | **recusado** — e com razão: o endereço e o produto já dizem o tipo. Ele serve só para escolher o endereço, e não vai no corpo |
| service tag | **`org_serial_number`** (`serial_number` é recusado) |

O apelido da service tag não foi escolhido por semelhança de nome: `cpu_serial_number` também era
candidato, e só `org_serial_number` devolveu o valor gravado na leitura de volta. Se os dois
tivessem gravado, o diagnóstico teria parado e perguntado.

Provado no laboratório: `asset_tag`, `name`, `org_serial_number` e `state` gravam e voltam.

**Garantia (18/11, v1.27.0):** o SDP guarda data como **epoch em milissegundos**; o Zelo mandava
`AAAA-MM-DD`, então a garantia era recusada ou gravava lixo em silêncio. Agora converte, usando
**meio-dia UTC** — meia-noite muda de dia conforme o fuso de quem lê, e meio-dia UTC aguenta de
-11:59 a +11:59 sem precisar de banco de fusos (que o Python no Windows não traz). Data ilegível
(a planilha tem "Vencida" escrito nesse campo) fica **fora** do corpo em vez de virar nulo.

### A pergunta da duplicação — RESPONDIDA (13/11, no SDP de produção da MB)
O agente do SDP grava a service tag no campo **`service_tag`**. Visto num ativo real escaneado
(`lmbbfyp9nq3.reyesholdings.com`, agente 11.2.2338.1.W): `service_tag: FYP9NQ3`, com `serial_number`
e `org_serial_number` ausentes.

Isso **não** teria sido descoberto pela sondagem automática: ela procura nomes que contenham a raiz
do campo (`serial`), e `service_tag` não contém. No laboratório, onde não há agente, ela tinha
concluído `org_serial_number` — e o Zelo estaria escrevendo a tag num campo que o agente não lê,
criando um ativo duplicado por máquina em todo o parque.

Daí duas mudanças (v1.26.0): `service_tag` entrou na lista de campos pedidos na listagem, e passou
a existir uma tabela de **sinônimos conhecidos** (`serial_number` → `service_tag`,
`org_serial_number`, `serial_no`) com ordem de preferência vinda do que o agente de verdade
preenche. Quando vários campos guardam o valor e um deles é o do agente, agora há razão para
preferir, e ele prefere; sem razão, continua perguntando.

**Na MB, portanto: `serial_number=service_tag` em "Nomes de campo próprios".**
No laboratório, onde o build recusa `service_tag`, vale `org_serial_number`.

Falta confirmar na prática que o agente funde em vez de duplicar — mas a condição necessária
(escrever no campo que ele lê) está resolvida.

### A base de ativos do SD foi zerada (17/11/2026)
O Gabriel limpou o módulo de ativos do SDP da MB: hoje não há nenhum ativo lá, e dali em diante só
entra pelo agente. Isso resolve a divisão de trabalho da criação, que estava em aberto:

- **Notebook, desktop, thin client** → o agente cria; o Zelo não encosta na criação, só enriquece.
- **Monitor, celular, dock, coletor, tablet** (~2295 itens) → nunca terão agente. Ou o Zelo cria,
  ou nunca existem no SD.

Configurável sem código: em **Tipos de produto próprios**, `Notebook=` com o lado direito vazio
desliga a criação daquela categoria.

O preço: o agente **não** vem na imagem do Windows e é instalado à mão pelo Suporte. Máquina
formatada ou nova sem agente é invisível para o SD. Mas o Zelo sabe o que entregou — hostname
entregue que não aparece no SD em N dias só pode ser agente não instalado, e isso vira pendência
(e, quando a oportunidade G existir, chamado automático). É o monitoramento de cobertura do agente,
e sai quase de graça porque o Zelo tem os dois lados.

Consequência para "o ativo conta a própria história": esse histórico **começa agora**, e só se
constrói se o ativo estiver anexado aos chamados. O interruptor "anexar o equipamento ao chamado"
deixa de ser enfeite e vira matéria-prima — cada mês desligado é um mês de histórico perdido
para sempre.

### Outros achados do mesmo ativo, para usar depois
- **Datas vêm em epoch de milissegundos** (`warranty_expiry: 1813046399000`, `acquisition_date`).
  O Zelo manda garantia como `{'value': 'AAAA-MM-DD'}` — **provavelmente não grava**; conferir antes
  de ligar "Corrigir os campos que são do Zelo".
- Campos que o SD já tem e o Zelo poderia aproveitar: `department`, `site`, `region`,
  `last_logged_user`, `mac_addresses`, `os_name`, `manufacturer`, `chassis_type`,
  `agent_version`, `last_scan_success_time` (dá para saber quais máquinas o agente parou de ver).
- `product_id` é o product id do **Windows**, não o id do produto do SDP. Confirma que o apelido
  `product_type=product_id`, que a v1.20.0 rejeitou por falta de prova de ida e volta, teria
  gravado lixo em cima da licença.
- O ativo tem `linked_entity: cmdb_windowsworkstation` — existe um CI espelho no CMDB.

### Detector de duplicados — FEITO (v1.22.0)
Seção **Repetido no Service Desk** no topo de Itens → Conferir com o Service Desk. Agrupa por
service tag e por hostname (plaqueta não: etiqueta reaproveitada é legítima e viraria ruído). É por
ela que se lê o resultado do teste do agente, sem caçar na mão no SDP.

Junto saiu um reparo que o achado da service tag obrigava: `do_sd` lia a tag só de `serial_number`,
que neste build está vazio — a tela de conferência achava que o Service Desk não tem tag nenhuma, e
estava casando só por hostname e plaqueta.

### Depois disso, na ordem conversada
1. **Cadastro em massa** — empurrar os itens do Zelo para o SD pela fila. Só faz sentido depois do
   teste do agente; antes disso é construir sobre premissa não provada.
2. **G — abrir chamado pelo Zelo** (`POST /api/v3/requests`). Independe do agente. Precisa combinar
   template, categoria e grupo antes.
3. **H — preencher service tag vazia no SD.**
4. **I — ler garantia e contrato do SD** para alimentar os lembretes que o Painel já mostra.

### Decisão que vai aparecer no cadastro em massa
No SDP **todo ativo pertence a um produto** (o modelo), e produto é cadastro manual. Para os 3203
itens, ou existe um produto por modelo, ou todos caem no primeiro produto do tipo e o campo Modelo
no SD fica errado — nas ~2295 máquinas sem agente, errado para sempre. Três caminhos:
1. extrair os modelos distintos da planilha unificada e cadastrar os produtos antes (mais trabalho
   agora, cadastro certo depois);
2. um produto genérico por tipo ("Notebook MB"), com o modelo real existindo só no Zelo;
3. o Zelo criar o produto quando faltar — **descartado**: sistema criando catálogo no SDP sem
   revisão humana é como a base fica bagunçada de novo.
Decidir quando o diagnóstico rodar na MB e mostrar que produtos já existem lá.

### Nota de ambiente
Esta parte do trabalho foi feita por um assistente em nuvem, que gravava os arquivos no
`Desktop\Zelo` por uma ponte com o desktop. A ponte caiu em 13/11 e o Gabriel passou a trabalhar
pelo Claude Code, na própria máquina. Daí este `CLAUDE.md` e esta seção.

---

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
- ~~Publicar no GitHub~~ — feito em 13/11: `github.com/GabrielGCIT/Zelo`, privado, sem o banco.
- Tipo de produto `TESTE-ZELO-01` sobrou de um teste no SDP do laboratório; apagar antes que a base
  vire produção — tipo órfão é começo de bagunça nova.
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

## Princípio: o Zelo é autossuficiente; o Service Desk é adaptador (17/11/2026)
Decisão do Gabriel: o Zelo tem de rodar sozinho amanhã se preciso, e rodar **com excelência** quando
integrado. Consequências práticas, que é fácil furar sem perceber:

- **A espinha do processo mora no Zelo.** Quando o Zelo passar a abrir e fechar chamados, a
  *solicitação* (pedido de preparação, pedido de devolução) é entidade **do Zelo**, com status e
  prazo próprios; o chamado no SD é o espelho dela. Apontar só para o Nº do chamado mudaria o
  processo de casa sem ninguém decidir isso.
- **O SD é registro oficial de chamado e fonte do que o agente descobre da máquina.** Não é o banco
  de dados do Zelo: pessoas, itens e histórico de responsabilidade vivem aqui.
- **Teste para toda decisão nova:** *se a integração for desligada agora, isso continua
  funcionando?* Se não, está no lugar errado.

## Identificação de pessoa: matrícula é a chave, CPF é atributo (17/11/2026)
Terceiro não tem matrícula, então o CPF é necessário — mas o que importa é **onde ele mora**. No
Zelo ele fica com três ou quatro usuários de governança; no SD ficaria com dezenas de técnicos e
como campo de busca. Mesmo dado, riscos muito diferentes.

- matrícula segue sendo a chave (terceiro recebe matrícula interna; o Zelo já gera `SD-NOME`);
- CPF entra como atributo da pessoa, para busca e para identificar quem assina o termo — uso
  legítimo num termo de responsabilidade;
- fica no Zelo, **não** no Service Desk; restrito por perfil e mascarado nas telas de consulta.

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
decide a chave do corpo (`asset_computers` → `{'asset_computer': {...}}`). A listagem é **paginada**
e sem `row_count` só devolvem os 10 primeiros tipos. No SDP da MB, por exemplo, o endereço de
Notebook é `asset_laptops`, não `asset_computers` — motivo suficiente para nunca fixar a lista.

**O SDP exige um produto** e recusa com `HTTP 400 Value not provided`, sem dizer qual campo falta.
Quem responde isso é `GET /api/v3/<modulo>/_metainfo`, e o diagnóstico lê de lá. O produto tem que
**já existir** no SDP: o Zelo procura pelo modelo do item e, na falta, usa qualquer produto daquele
tipo — o agente corrige o modelo quando chegar. O Zelo **não cria produto**: inventar cadastro no
SDP é a sujeira que esta integração existe para evitar.

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
