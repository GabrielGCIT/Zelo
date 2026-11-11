# Zelo

Controle de ativos de TI e linhas móveis da Martin Brower Brasil. Substitui a planilha
"Gestão de Ativos de TI - Centralizado.xlsx", com as mesmas regras, e roda num servidor interno
(mesma base do Lastro: Flask + SQLite + waitress, sem internet na máquina de destino).

## O que tem

| Tela | Para quê |
|---|---|
| Painel / Minha fila | números do parque e o que precisa de ação (reservas, devoluções, preparação, termos, empréstimos vencendo, desligados com item, contratos) |
| Lançamentos | grade igual à da planilha (Entrega, Empréstimo, Mobile, Estoque), com Conferência linha a linha antes de gravar e Desfazer último |
| Acompanhar | 1 · reserva → termo → chamado → entregue (ou cancelar, devolvendo o kit) · 2 · chegada e preparação do notebook devolvido (kit completado do EC na liberação) · 3 · termos sem link · 4 · corrigir um lançamento |
| Manutenção | abrir / atualizar / fechar OS; backup do pool gera o empréstimo; "Backup volta?" ao fechar; peça sai do EC |
| Consumíveis | saldo por site, entrada, saída, contagem de inventário (ajuste), catálogo, cadastro de item novo (IMEI com dígito verificador, plaqueta/tag duplicada, compra) |
| Linhas | cadastro, ficha e a Conferência Easy × Zelo × AirWatch (Bloquear / Validar com a Easy / OK – ajustar cadastro / OK), com retorno da ligação e exportação para Excel |
| Termo | termo pronto para imprimir a partir do Nº do lançamento (ou EA-xxxx para acessório) |
| Administração | usuários e perfis (Administrador, Operador, Consulta), configurações, auditoria |

O Histórico é a fonte da verdade: situação, com quem, desde, termo e kit de cada item/linha são
recalculados a partir dele (`app/regras.py`). Na importação da planilha de 09/11 a situação calculada
bateu com a da planilha em 100% dos itens e linhas.

## Desenvolvimento

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py importar "Gestão de Ativos de TI - Centralizado.xlsx"
.venv/bin/python run.py              # http://localhost:5001 — o link de primeiro acesso aparece no console
.venv/bin/python -m pytest -q        # usa a planilha real (ZELO_PLANILHA_TESTE) num banco temporário
```

## Entrega

`python scripts/empacotar.py` gera `dist/Zelo-<versão>.zip` com os componentes para Windows
(Python 3.10 a 3.14), `instalar.bat`, `iniciar.bat`, `instalar-servico.bat` (tarefa no boot +
firewall da porta 5001), `importar-planilha.bat` (arrastar a planilha) e `atualizar.bat`.
Instruções para quem instala: `LEIAME.txt` dentro do pacote.

## Próximos passos combinados

- Login com a conta Microsoft
- Leitura direta da API do AirWatch (hoje é o upload do relatório)
- Admissões
