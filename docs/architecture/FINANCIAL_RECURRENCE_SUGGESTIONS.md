# Sugestões assistidas de recorrência — padrão detectado, confirmação explícita

Status: **em implementação (#256)** na branch `feat/finance-assisted-subscriptions-256`; batch 1 (domínio, detector puro, fingerprint e ADR) concluído. Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

Normativo: ADR-0028 (e ADR-0027 para a recorrência criada). Este documento descreve o contrato do detector, do fingerprint e das decisões. Nenhuma regra financeira anterior foi alterada.

## Definição

Uma **sugestão** é um padrão mensal provável, **derivado na leitura** de Movements `STANDARD` `EXPENSE` já realizados e visíveis ao operador. Ela **não é** Movement, ocorrência nem recorrência; não altera saldo, extrato, classificação nem orçamento; nunca é aceita sozinha; `GET` nunca escreve; não há job nem processo de fundo. O único efeito possível é o usuário **confirmar** a criação de uma recorrência canônica da #254 (ou **dispensar** a sugestão). Detecção é provider-neutral: sem Pluggy, merchant, fuzzy, ML, LLM ou pontuação opaca.

## Detector v1

Implementado como função pura (`detect_recurrence_suggestions`, em `meufinanceiro_finance.recurrence_suggestions`): dado o mesmo conjunto de observações e a mesma data injetada, devolve o mesmo resultado, independentemente da ordem. Não lê relógio nem fuso.

**Entrada elegível** (filtrada por quem chama, sob a RLS do operador): `STANDARD` `EXPENSE` de conta `ACTIVE`, com data efetiva entre o primeiro dia do mês de `hoje − 11 meses` e `hoje` (12 meses civis; nada no futuro). Excluídos: `REVERSAL`, `INCOME`/`NEUTRAL`, `STANDARD` já revertido, Movement ligado a `finance.recurrence_occurrences` e descrição ausente, vazia ou só espaços após normalizar.

**Agrupamento** (nunca entre contas): `(conta, EXPENSE, moeda, descrição normalizada)`. Normalização reutilizada de `normalize_categorization_text`: trim externo → NFC → `casefold` → NFC (acentos, pontuação e espaços internos preservados). `Streaming`, `  STREAMING` e `streaming ` são o mesmo grupo; `Streaming+` e `Streamingg` não são.

**Critério** (todos obrigatórios):

| Regra | Efeito se falhar |
|---|---|
| a *corrida* final de meses civis consecutivos (até a última observação) tem ≥ 3 meses e **exatamente uma** observação por mês | sem sugestão |
| a corrida termina no mês atual ou no anterior | sem sugestão (padrão que parou) |
| o último mês tem uma única observação | sem sugestão (ambíguo) |
| as datas cabem numa janela de cobrança de ±3 dias em torno de um dia âncora | sem sugestão |
| nenhuma recorrência da conta cobre o mesmo grupo (conta, `EXPENSE`, moeda, descrição normalizada; qualquer status) | sem sugestão |

Uma lacuna, ou um mês com duas cobranças, **antes** da corrida só encerra a corrida: valem os meses depois dela.

**Dia âncora.** Um dia `D` (1..31) explica uma observação no mês `M` e dia `d` com desvio `|min(D, último_dia(M)) − d|`, então uma cobrança no dia 31 que cai em 28/29/30 em meses curtos tem desvio zero. `D` é aceito se o maior desvio for ≤ 3. Entre os aceitos vence o de menor maior desvio, depois menor desvio total, depois menor dia: escolha total, independente da ordem. Exemplos: `10, 11, 12` → 11; `31/07, 31/08, 30/09` → 31; `31/12, 31/01, 28/02` → 31; `30/01, 28/02, 30/03` → 30; um espalhamento de sete dias não tem âncora e não gera sugestão.

**Valor.** Pode variar e é evidência: expõe-se cada valor e data observados (na ordem), mínimo, máximo, último valor, `suggestedExpectedAmount` (= último valor observado) e `amountBehavior` (`FIXED` se todos iguais, senão `VARIABLE`). Tudo `Decimal`, nunca `float`.

**Motivos** (`reasonCodes`, enumerados; sem confiança numérica): `EXACT_DESCRIPTION`, `CONSECUTIVE_MONTHS`, `ONE_PER_MONTH`, `DAY_WINDOW` e `AMOUNT_FIXED` ou `AMOUNT_VARIABLE`.

**Saída:** `fingerprint`, conta, dono da conta, descrição exibida (a da última observação), descrição normalizada, moeda, evidências (`movementId`, data, valor), `suggestedDayOfMonth`, `suggestedExpectedAmount`, `amountBehavior`, mínimo, máximo, último, `reasonCodes`, `canAccept` (somente o dono da conta) e o `evidenceDigest` do que foi mostrado. Ordem: observação mais recente primeiro, depois fingerprint.

## Fingerprint

`SHA-256` (hex minúsculo de 64 caracteres) com prefixo de tamanho sobre `meufinanceiro:recurrence-suggestion:v1`, instalação, residência, conta, `EXPENSE`, moeda e descrição normalizada. **Não inclui** IDs de Movement nem datas: o feedback sobre a mesma assinatura sobrevive a novas observações. **Não é resource ID e não prova acesso**; o servidor sempre reexecuta o detector para o operador e só age sobre um fingerprint que ele produz agora. Uma forma inválida é `422`; um fingerprint que o operador não produz (inexistente, forjado, de outra conta/residência ou de conta invisível) é o mesmo `404`.

## Limites

Janela fixa de 12 meses; a varredura lê no máximo `SUGGESTION_SCAN_MAX` = 20 000 Movements e a resposta traz no máximo `SUGGESTION_LIST_MAX` = 100 sugestões; ultrapassar qualquer um é erro explícito (nunca truncamento silencioso). Custo constante em statements.

## Pontos aceitos (P2), sem bloqueio

- a janela de dia fixa em ±3 dias é uma política conservadora e documentada, não uma estimativa de calendário bancário;
- o valor sugerido é o último observado, não uma mediana: é explicável e o usuário o revisa antes de confirmar;
- uma dispensa não expira quando surgem novas evidências;
- só despesas, só mensal, só contas ativas;
- uma recorrência equivalente criada manualmente ao mesmo tempo que um aceite pode coexistir com ele (equivalência é semântica de sugestão, não invariante do banco).

## Fora do escopo

Criação automática, detecção em segundo plano, ML/LLM/fuzzy, enriquecimento de merchant, metadados de provedor, receitas recorrentes assistidas, frequências semanal/anual/personalizada, cancelamento automático, alertas, comparação de preços, cobrança contestada, cartões e faturas, importação e conciliação, HML/PROD/deploy e GitHub Actions como gate.

## Estado do trabalho

| Batch | Escopo | Estado |
|---|---|---|
| 1 | domínio, detector puro, fingerprint, normalização e ADR-0028 | concluído |
| 2 | persistência de decisões, RLS e store do detector | pendente |
| 3 | API accept/dismiss, writer transacional da recorrência e concorrência | pendente |
| 4 | Flutter, desempenho, smoke, docs e gates | pendente |
