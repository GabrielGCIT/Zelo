# Como trabalhar neste repositório

Zelo — controle de ativos de TI e linhas móveis da Martin Brower Brasil. Flask + SQLite + waitress,
roda num servidor Windows interno **sem internet**. Substitui a planilha
"Gestão de Ativos de TI - Centralizado.xlsx".

Leia o `README.md` para o mapa das telas e o `PLANO.md` para as decisões, o histórico das etapas e o
que está em aberto. **O `PLANO.md` é o contexto de verdade do projeto** — antes de propor qualquer
coisa sobre Service Desk, leia a seção do levantamento até o fim: várias ideias óbvias já foram
testadas e recusadas pelo build real.

## Quem é o Gabriel, e como ele quer as coisas

Analista de governança de TI na Martin Brower; administra o ServiceDesk Plus da empresa e escreveu
este sistema sozinho. Fala português. Prefere resposta curta e direta, sem rodeio e sem elogio.
Quer discordância quando houver motivo — concordar por educação não ajuda.

Ele vai ler o código depois. Comentário explica **por que**, não o que a linha faz; e vale mais o
comentário que registra uma decisão ou uma armadilha já paga do que o que descreve o óbvio.
Nomes de função, variável e rota em português, como o resto do código.

## Comandos

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # a suíte inteira; tem que ficar verde antes de commitar
.venv/bin/python run.py                # http://localhost:5001
python scripts/empacotar.py            # dist/Zelo-<versão>.zip para Windows
```

Os testes usam a planilha real (`ZELO_PLANILHA_TESTE`) num banco temporário. **Nenhum teste toca um
Service Desk de verdade**: `tests/test_servicedesk.py` tem um `SimuladorSD` que imita o build da MB,
inclusive os erros dele (`asset_assets` recusando POST, campos que o SDP aceita e ignora, listagens
paginadas em 10). Toda descoberta nova sobre o SDP vira comportamento no simulador **e** teste.

## Regras do código que não são óbvias

**O Histórico é a fonte da verdade.** `Item.situacao`, `com_quem`, `desde` e companhia são *cache*
recalculado por `app/regras.py` (`recalcular_item`, `tocar`) a partir das movimentações. Nunca
escreva nesses campos direto: grave o histórico e recalcule. Exceção única: **Manutenção** tem tabela
própria e a situação `'Manutenção'` é sobreposta, sem gerar movimentação.

**Ajustar cadastro e Manutenção mudam a situação sem movimentação.** Por isso existe
`servicedesk.enfileirar_item`: o Service Desk precisa acompanhar essas duas mesmo sem lançamento.

**A máquina de destino não tem internet.** Bootstrap, FontAwesome e Chart.js estão vendorizados em
`static/`. **Não acrescente dependência nova sem necessidade real** — o pacote offline do Windows é
montado com `pip download` e já está fechado. Foi por isso que o Code 128 das etiquetas
(`app/etiqueta.py`) foi escrito à mão em vez de usar `python-barcode`.

**Não mexa em `instance/`, `backups/` nem `logs/`.** São dados do servidor dele.

## Service Desk — o que já custou caro descobrir

O build é **ManageEngine ServiceDesk Plus on-premises, v3 da API**. A documentação pública e este
build divergem em pontos importantes, e cada divergência abaixo foi encontrada com o botão
**Administração → Service Desk → Diagnóstico: criar ativo** (`servicedesk.diagnostico_criacao`).

- `/api/v3/assets` não existe aqui; o que responde é `/api/v3/asset_assets`.
- **`asset_assets` não CRIA ativo** — devolve `404 Cannot add asset under Asset product type`.
  Cada tipo de produto tem o seu endereço (`asset_laptops`, `asset_monitors`, …), e a lista sai de
  `GET /api/v3/requests/assets/module` (campo `api_plural_name`). Essa listagem é **paginada**: sem
  `row_count` vêm só 10. O tipo também decide a chave do corpo (`asset_laptops` →
  `{'asset_laptop': {...}}`).
- Escrita é sempre **um ativo por chamada**: o lote (`?ids=`) devolve "Internal Error". Logo, tudo
  que for em massa é **fila** (`EnvioSD`), nunca botão síncrono.
- **Campo vazio fica fora do corpo.** No SDP mandar nulo apaga o que está lá; não mandar deixa como
  está.
- O SDP exige um **produto** que já exista lá, e recusa com `400 Value not provided` sem dizer qual
  campo falta. O Zelo nunca cria produto — inventar cadastro no SDP é a bagunça que a integração
  existe para evitar.
- **Sucesso na chamada não é valor gravado.** Há campo que o SDP aceita e ignora em silêncio. Toda
  sondagem de campo cria, **lê de volta pelo endereço do módulo** e confere se o valor voltou. A
  listagem geral (`asset_assets`) devolve menos campos que a ficha do módulo — ler por ela faz campo
  gravado parecer campo perdido.
- **Nome parecido não é o mesmo campo.** `cpu_serial_number` e `org_serial_number` guardam os dois;
  só um é a service tag da máquina. Quando mais de um candidato grava, o Zelo **não escolhe**: lista
  as opções e deixa a decisão em "Nomes de campo próprios".

O princípio atrás de tudo isso: **perguntar ao build em vez de confiar na documentação**, e **exigir
prova de ida e volta** antes de dar um campo por bom. Lista fixa tirada da documentação foi
exatamente o que produziu o primeiro 404.

### Chaves de configuração do Service Desk
`sd_url`, `sd_chave`, `sd_ssl`, `sd_ativo` (integração ligada), `sd_ativos` (sincronizar ativo),
`sd_estados` (mapa situação=estado), `sd_anexar_ativo`, `sd_criar_ativo`, `sd_campos_zelo`,
`sd_tipos` (categoria=tipo de produto), `sd_criar_fora` (campos que este build recusa),
`sd_apelidos` (campo=nome real neste build). As três últimas o diagnóstico preenche sozinho.

## Segurança e limites combinados

- **A chave de API de produção da MB nunca passa por um assistente.** Ela é colada direto na tela de
  Administração do servidor deles, e a tela nunca a mostra de volta. A chave do laboratório doméstico
  do Gabriel é a única que pode aparecer numa conversa.
- **Sem dados de produção da MB no laboratório.**
- Não digite senha por ele — nem a de proteção da planilha.
- Script que apaga coisa no SDP: lê a chave de arquivo local ou variável de ambiente (nunca embutida),
  faz *dry-run* primeiro, e é testado no laboratório antes da produção.
- Apagar um ativo no SDP pode **desinstalar o agente** da máquina ou pôr o host na lista de exclusão —
  ele não volta sozinho na varredura. `servicedesk.apagar_ativo` existe só para o ativo de teste do
  diagnóstico.

## Commits e versão

Uma linha em `VERSAO` (ex.: `1.21.0`), subida a cada entrega. Mensagem de commit em português,
assunto curto no imperativo, corpo explicando **o motivo** e o que foi descartado — o histórico deste
repositório é usado como memória do projeto, então vale escrever para quem vier depois.
Repositório: `github.com/GabrielGCIT/Zelo` (privado). O banco nunca sobe.
