# Orçamentos mensais por categoria — planejado × realizado

Status: **entregue** pela issue #252 (4 batches), integrada ao `develop` pela PR #253 (`bfcd228`).

Normativo: ADR-0026. Este documento descreve o contrato, a API, a agregação, o desempenho e o cliente Flutter. Nenhuma regra financeira anterior foi alterada.

## Definição

Um orçamento é **planejamento persistido**, separado do ledger. O realizado é sempre derivado de `finance.movements` + allocation set corrente + allocations correntes. Nunca existe Movement fictício, saldo planejado, `budget_id`/`category_id` em `finance.movements` ou cache monetário.

## Esquema

```text
finance.budgets
  id, installation_id, residence_id, owner_operator_id
  visibility_scope PERSONAL | HOUSEHOLD
  name, currency, period_kind MONTHLY, period_start (dia 1), date_basis CASH | COMPETENCE
  version (CAS), idempotency_key, request_digest, updated_by_operator_id, created_at, updated_at

finance.budget_lines     -- append-only por revisão
  budget_id, revision, category_id, result_effect INCOME | EXPENSE, planned_amount NUMERIC(24,8) > 0
  (a corrente é revision = budgets.version)
```

Migrations: `0023_monthly_budgets` (tabelas, RLS forçada, gatilhos, grants) e `0024_budget_realization_indexes` (só um índice de desempenho). Ambas simétricas por downgrade; head único.

- runtime: `SELECT, INSERT` nas duas tabelas e `UPDATE (name, version, updated_at, updated_by_operator_id)` em `budgets`; **sem `DELETE`**;
- RLS: PERSONAL só o dono; HOUSEHOLD leitura por membros ativos e escrita só do dono; linhas herdam a visibilidade do orçamento;
- gatilhos: versão inicial 1; update exige `version + 1` e identidade imutável; linhas só na revisão escrita na mesma transação, com categoria ativa e da mesma audiência; 1 a 100 linhas por revisão validadas no commit;
- índice único material: um plano por residência/audiência(/dono)/moeda/mês/base.

## Contrato HTTP

Residence-scoped sob `/api/v1/finance`. Erros sanitizados: `401`, `403` (acesso ou orçamento somente leitura), `404` (inexistente/invisível, categoria inexistente/incompatível), `409`, `422`, `503`.

| Método | Caminho | Uso |
|---|---|---|
| `GET` | `/budgets?period=YYYY-MM` | orçamentos visíveis do mês (único parâmetro aceito) |
| `POST` | `/budgets` | cria (`201`, replay-safe) |
| `GET` | `/budgets/{id}` | lê |
| `PUT` | `/budgets/{id}` | substitui nome e linhas sob `expectedVersion` |
| `GET` | `/budgets/{id}/summary` | planejado × realizado + cobertura |

Não existe `DELETE` nem `PATCH`.

Criação: `idempotencyKey` (UUID v4), `name`, `visibilityScope` (`PERSONAL`/`HOUSEHOLD`), `currency`, `period` (`YYYY-MM`), `dateBasis`, `lines[{categoryId, resultEffect, plannedAmount}]`. Edição: `expectedVersion` (inteiro ≥ 1), `name`, `currency`, `lines`. Dinheiro é sempre texto decimal (`^(0|[1-9][0-9]{0,15})(\.[0-9]{1,8})?$`, positivo); `float` é recusado. Corpo desconhecido, ausente ou fora do contrato é `422`.

`409` distingue pelo texto sanitizado: `financial budget version is stale` (CAS) e `financial budget conflicts with canonical state` (chave reutilizada com outro material, ou mês já planejado).

Todo orçamento (lista, leitura, criação, edição e o `budget` do resumo) traz o campo estável **`realizationAccountScope`**, decidido pelo servidor:

| Valor | Orçamento | Contas que alimentam realizado e cobertura |
|---|---|---|
| `HOUSEHOLD_ONLY` | `HOUSEHOLD` | somente contas `HOUSEHOLD` |
| `OWNER_PERSONAL_ONLY` | `PERSONAL` | somente contas `PERSONAL` do dono |

Contas pessoais e compartilhadas **não** entram no orçamento da casa, mesmo que seus lançamentos usem uma categoria da casa; o realizado pode, portanto, ser menor que o gasto total do período, e o contrato diz isso em vez de deixar o número parecer completo.

Resumo:

```text
budget { ..., realizationAccountScope, version, canEdit }
lines[] { categoryId, resultEffect, planned, realized, remaining = planned - realized,
          status UNDER | AT | OVER, progressPercent (Decimal, 2 casas, meio para cima) }
coverage { unclassifiedExpenseCount, unclassifiedExpenseAmount,
           unclassifiedIncomeCount, unclassifiedIncomeAmount }
```

`status` compara realizado e planejado: `INCOME` acima do previsto não é um problema. `planned` é sempre positivo, então não há divisão por zero. `realized` pode ser negativo (estorno posterior).

## Realizado

Por linha `(category, effect)`, no mês da base de data do orçamento (`CASH` → `effective_date`, `COMPETENCE` → `competence_date`), intervalo `[início, fim)`, na moeda do orçamento:

- `STANDARD` soma `+|parcela|` da allocation corrente da categoria; um rateio conta só a sua parcela;
- `REVERSAL` soma `-|parcela|` da allocation corrente do `STANDARD` que estorna, na **data do próprio estorno**; `REVERSAL` não é classificado;
- `NEUTRAL` e outras moedas nunca entram; categorias sem linha são ignoradas;
- contas somadas: as de `realizationAccountScope` (HOUSEHOLD → contas `HOUSEHOLD`; PERSONAL → contas `PERSONAL` do dono). Movements de contas `PERSONAL`/`SHARED` classificados em categoria da casa ficam fora do orçamento da casa — realizado **e** cobertura — por segurança (nenhum gasto pessoal em número compartilhado). `SHARED` não alimenta nenhum orçamento na v1.

Efeitos provados: reclassificação muda o resumo sem tocar o ledger; estorno integral no mesmo mês leva a linha a 0 exatamente uma vez; estorno posterior credita o mês do estorno; reclassificar o original move original e estorno juntos.

## Cobertura

Fora das linhas, por período/moeda/audiência: `STANDARD` sem allocation set soma `+|valor|` (e conta 1) se não foi estornado no mês; `REVERSAL` no mês de original sem classificação **fora** do mês soma `-|valor|` (e conta 1); um par original/estorno ambos no mês se cancela. Classificar o item (#245/#247) o remove na leitura seguinte. A tela oferece **Abrir Pendências** (#249).

## Desempenho

Uma leitura do resumo é uma transação `REPEATABLE READ` somente leitura com 6 statements fixos (contexto, membership, orçamento, linhas, realizado, cobertura), independente de Movements, categorias, linhas ou orçamentos do mês. Listar um mês custa 2 statements.

O realizado e a cobertura são SQL explícito com CTEs materializadas e leitura das parcelas dos Movements do mês por `movement_id = ANY(ARRAY(...))`. Motivo medido: sob RLS forçada, planos com loops aninhados reavaliam a cadeia de políticas das allocations a cada varredura. A primeira forma (join por `COALESCE(reversal_of_id, id)`) passou de 10 minutos em 60 mil Movements; com 2 branches por linha ainda custava ~1,3 s por mês; a forma final leva ~0,1 s.

| Medição (PG 18.4, não-superuser, RLS forçada, 60 mil Movements, ~1,9 mil no mês, 20 linhas) | Resultado |
|---|---|
| leitura completa do resumo | ~0,1 s |
| realizado (servidor, `EXPLAIN ANALYZE`) | ~24 ms, ~18 mil buffers |
| cobertura (servidor) | ~47 ms, ~11 mil buffers |
| mesmo statement sem RLS (superuser) | ~45 ms (referência) |

Testes automatizados exigem: nenhum `Seq Scan` em `movements`, `movement_allocations` e `movement_allocation_sets`; acesso ao mês por índice de data; buffers do mês quase estáveis ao triplicar o ledger fora do mês (crescimento < 60%, contra +200% se o custo fosse proporcional); leitura completa < 1,5 s; ≤ 8 statements.

## Escrita e concorrência

| Cenário | Resultado provado |
|---|---|
| criar duas vezes com a mesma chave e material | replay do mesmo orçamento |
| mesma chave com outro material/operador | `409`, nada gravado |
| 4 criações simultâneas idênticas | um orçamento |
| 5 edições simultâneas com a mesma versão | exatamente 1 vence, 4 `409` |
| edição com versão antiga ou futura | `409`, nada gravado |
| membro edita orçamento da casa | `403`, nada gravado |
| leitura durante reclassificações | sempre um estado consistente (snapshot) |

## Cliente Flutter

Tela **Orçamentos** (`/app/financas/orcamentos`, atalho na lista de contas):

- mês atual, navegação mensal, seletor quando há vários orçamentos no mês (escopo × base × moeda);
- criar/editar em diálogo: nome, escopo, moeda explícita, caixa/competência, linhas (tipo, categoria ativa compatível, valor planejado); categoria incompatível ou indisponível não é oferecida e bloqueia salvar; escopo, moeda, mês e base não mudam depois de criados;
- planejado, realizado e restante exatamente como o servidor devolveu, barra de progresso e `UNDER`/`AT`/`OVER` por texto (e ícone), nunca só por cor;
- alerta de cobertura com **Abrir Pendências**;
- aviso em texto, sempre visível (orçamento carregado e criar/editar), do escopo de realização recebido do servidor: pessoal considera só as contas pessoais do dono; da casa considera só as contas da casa, e contas pessoais e compartilhadas não entram no realizado nem na cobertura. O cliente rejeita como resposta inválida um escopo desconhecido ou incoerente com a audiência e não recalcula o realizado;
- estados: carregando, vazio do mês, erro com tentativa manual, resumo indisponível (plano mantido), lista possivelmente desatualizada, somente leitura e conflito.

### Sem sucesso otimista, sem retry automático

Toda resposta de escrita (sucesso, `409`, `403`, `404`, `422`, 5xx, transporte ou 2xx inválido) termina em **uma** releitura do mês que substitui o estado. `409` levanta o aviso de conflito e **não** refaz a edição sobre a versão nova. Uma criação de resultado desconhecido guarda a chave de idempotência apenas para um retry explícito e idêntico (o servidor devolve o replay). Se a releitura falha, o plano é marcado como possivelmente desatualizado e novas escritas ficam bloqueadas até *Atualizar*. O cliente não calcula realizado, restante, status nem percentual; só interpreta o texto de percentual para o tamanho da barra, com inteiros.

## Autoridade e invariantes

- `finance.movements` continua o único ledger; o orçamento não escreve nele, nem em allocations, nem em auditoria financeira;
- nenhuma coluna de realizado/saldo em banco (testado); sem `float`/`double`; sem semântica de provider;
- autorização, categoria, moeda, CAS e idempotência são do backend; o Flutter só evita opções obviamente inválidas.

## Pontos aceitos (P2), sem bloqueio

- o realizado e a cobertura podem ser negativos quando o estorno cai em outro mês que o original; a UI mostra o número do servidor;
- `STANDARD` estornado ainda não classificado continua na caixa de pendências (#249) mas não conta na cobertura do mês em que o par se cancela;
- orçamentos da casa só são editáveis pelo criador; edição colaborativa fica para decisão posterior;
- um orçamento acumula revisões de linhas (append-only); não há tela de histórico nem arquivamento;
- cada orçamento cobre um único par moeda × base; comparar caixa e competência exige dois orçamentos;
- o realizado de uma categoria com linha desativada continua contando; trocar a linha exige categoria ativa;
- a ordenação de categorias por caminho é a mesma já usada no cliente (comparação por unidades de código, acentos depois das letras ASCII).

## Fora do escopo desta entrega

Envelopes, rollover, base zero completa, períodos não mensais, subtree/rollup, tags, metas, recorrências (entregues depois pela #254; ver `FINANCIAL_RECURRENCES.md`), projeções, FX, alertas, IA, Pluggy/provider, arquivamento e `DELETE`, e HML/PROD/deploy.

## Evidência de fechamento

| Batch | Commit | Escopo |
|---|---|---|
| 1 | `c53dfa4` | domínio, schema, store, migration `0023`, RLS e CAS |
| 2 | `078cad6` | realizado, cobertura, estornos, serviço e API |
| 3 | `74403de` | Flutter: tela, controller, editor, API e `PUT` |
| 4 | commit deste documento | agregação otimizada (`0024`), concorrência, desempenho, documentação e gates |

Os resultados dos gates finais do Batch 4 constam do relatório de fechamento da issue.
