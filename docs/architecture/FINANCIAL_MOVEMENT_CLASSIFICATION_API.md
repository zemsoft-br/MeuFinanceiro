# Classificação e rateio manual de Movements — API e Flutter

Status: **implementação completa da issue #245** (4 batches). Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

Este documento descreve a capacidade vertical entregue sobre a persistência append-only da #170 (ADR-0022) e a auditoria da #171 (ADR-0023). Ele não altera nenhuma decisão: as regras financeiras continuam definidas no ADR-0022.

## Contrato HTTP

Todos os endpoints são residence-scoped e audience-aware, sob `/api/v1/finance`.

| Método | Caminho | Uso |
|---|---|---|
| `GET` | `/categories` | categorias visíveis ao operador (inclui `DISABLED`, para resolver histórico) |
| `POST` | `/categories` | cria categoria mínima (`PERSONAL` ou `HOUSEHOLD`, `parentId` opcional) |
| `GET` | `/movements/{movementId}/allocation` | classificação corrente (`allocation: null` quando não classificado) |
| `GET` | `/accounts/{accountId}/movement-allocations` | **leitura bulk** da classificação corrente de todos os Movements da conta, chaveada por `movementId` |
| `POST` | `/movements/{movementId}/allocation` | primeira classificação (1..50 shares) |
| `POST` | `/movements/{movementId}/allocation/revisions` | nova revisão append-only (`supersedesId` explícito) |

Não existe `PATCH`, `PUT` ou `DELETE` de classificação, nem `category_id` em `finance.movements`. Alterar uma classificação é sempre **anexar** uma revisão; a anterior permanece intacta.

Respostas de erro são sanitizadas: `404` (recurso/categoria inexistente ou invisível), `409` (estado canônico incompatível: predecessor stale, segunda classificação inicial, chave de idempotência reutilizada com outro material), `422` (formato, soma, sinal, moeda, duplicidade, alvo não classificável), `503` (indisponibilidade).

## Autoridade

O backend é a autoridade para soma exata, moeda, sinal, categoria `ACTIVE`, audiência, residência, ownership da conta, elegibilidade do Movement (`NEUTRAL` e `REVERSAL` não são classificáveis), predecessor corrente, concorrência, idempotência e RLS. O Flutter apenas evita oferecer opções obviamente inválidas.

Classificar, ratear ou revisar não cria evento econômico: valor, conta, moeda, direção, papel, datas e saldo do Movement não mudam.

## Cliente Flutter

- O extrato compõe `statement` + `categories` + **uma** leitura bulk, em memória, por `movementId`. O custo da tela não depende do número de Movements (nenhum `GET` individual de classificação por linha).
- Rótulos: `Sem categoria`, `Categoria pai > filha`, `N categorias`, `Não se aplica` (`NEUTRAL`/`REVERSAL`).
- Ações: `Classificar` (uma categoria ou `Ratear entre categorias`) e, para o owner de conta ativa, `Alterar classificação`. Não-owner, `NEUTRAL`, `REVERSAL` e conta arquivada ficam somente leitura.
- O editor de rateio mostra *Total do lançamento*, *Total rateado* e *Restante* e só habilita *Confirmar* quando a soma fecha exatamente. Bloqueia categoria duplicada, share zero, mais de 50 shares e categoria `DISABLED`/incompatível com a audiência. Categorias `DISABLED` de uma classificação histórica continuam visíveis, marcadas como indisponíveis, e precisam ser substituídas.
- A UI só muda depois de um `201` validado: não há sucesso otimista.

### Dinheiro

Valores são texto decimal; a aritmética de UX usa `BigInt` com escala de 8 casas (`financial_allocation_math.dart`). Não há `double`, percentual como autoridade, tolerância nem arredondamento. O sinal de cada share é o do Movement. O fechamento exigido é `SUM(shares) == movement.money`.

### Revisão, conflito e escrita ambígua

- O predecessor é sempre o `allocationSetId` com que o editor foi aberto; revisão contra um set histórico conhecido não é enviada.
- `409` (predecessor stale): **um** POST, zero retry, o predecessor não é trocado e a edição do usuário não é reaplicada sobre a nova revisão. O cliente relê categorias e classificações correntes, substitui o estado local e exige uma nova revisão manual.
- Timeout, falha de transporte, `5xx` ou `2xx` inválido: **uma** reconciliação, sem retry automático. Se o corrente mudou, ele é incorporado sem afirmar causalidade; se o predecessor ainda é o corrente, a chave de idempotência da tentativa é preservada para um retry explícito da *mesma* revisão; se a reconciliação falha, o estado fica não confiável e as mutações de classificação ficam bloqueadas até *Atualizar*.
- `404` reconcilia uma vez; `422` é rejeição sem retry.
- Idempotência: a tentativa lógica (Movement, predecessor e shares canônicas ordenadas por categoria) determina a chave. Reordenar linhas mantém a chave; qualquer mudança material gera outra. Chaves de primeira classificação e de revisão nunca se misturam.

## Fora do escopo desta entrega

Edição/movimentação/desativação de categorias, `SHARED` para categorias, regras automáticas (entregues depois pela #247; ver `FINANCIAL_CATEGORIZATION_RULES.md`), IA, tags, orçamento, recorrências, caixa de pendências, classificação de transferências `NEUTRAL`, classificação direta de `REVERSAL`, tela de histórico de revisões e qualquer integração Pluggy/Open Finance.

## Evidência de fechamento

| Batch | Commit | Escopo |
|---|---|---|
| 1 | `1815be26cb877db074ca211eaf30507a47549ed0` | boundaries, categorias, API de allocation, leitura bulk e revisão |
| 2 | `8c4caab5d341690280bab362da477b0781edda73` | Flutter: modelos/API/controller e classificação simples |
| 3 | `21d7eb42f819633d378ae55334115519bfd7026e` | Flutter: rateio, revisão append-only e reconciliação de stale/ambíguo |
| 4 | commit deste documento | fluxo vertical, gates finais e documentação |

Gates do Batch 4, executados localmente (sem GitHub Actions, HML ou PROD):

- fluxo vertical em PostgreSQL 16 real, com role de runtime não-superuser, sem `BYPASSRLS` e RLS forçada nas tabelas de ledger, categorias e classificação: categoria → despesa → sem categoria → classificação simples → revisão para rateio → conflito stale `409` → reconciliação → nova revisão explícita, com Movement, saldo e extrato idênticos em cada passo e a revisão anterior preservada linha a linha (nem `UPDATE` nem `DELETE`);
- leitura bulk com número de statements constante para 0, 1 e 25 Movements; no Flutter, 1 leitura bulk e 0 leituras individuais para 0, 1 e 25 Movements;
- fluxo vertical equivalente no controller Flutter, contando POSTs (um conflito nunca gera segundo POST);
- Flutter: `dart format`, `flutter analyze` e suíte completa sem avisos de hit-test.

A suíte Python completa tem **uma** falha, preexistente no `develop` e rastreada pela #240 (`tests/quality/test_safe_update_contract.py::test_update_contract_is_linked_and_ignored`), sem relação com esta issue.

## Pontos aceitos (P2), sem bloqueio

- Em uma classificação simples histórica cuja categoria continua `ACTIVE` mas saiu da audiência do operador, a nota do editor não acrescenta o sufixo "(indisponível)"; a escolha de outra categoria continua obrigatória.
- Uma revisão idêntica à corrente é recusada localmente (no botão e no controller) para não poluir o histórico append-only; isso é ergonomia do cliente, não regra do backend.
- Os testes de mutação do Flutter foram dirigidos e manuais; um mutante (troca do predecessor e reenvio automático após `409`) é detectado por não terminação do teste, não por asserção.
