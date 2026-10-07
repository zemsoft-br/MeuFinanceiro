# ADR-0027 — Recorrências mensais manuais: regra é modelo, ocorrência é instância, Movement é o único fato

- Status: Accepted
- Data: 2026-10-06
- Decisores: mantenedores

## Contexto

A Fase 2 (#180) pede distinguir previsão de fato realizado. O ledger (`finance.movements`, ADR-0019/0020) é a única autoridade monetária e é append-only; o saldo é derivado (ADR-0021). Orçamentos (ADR-0026) já são planejamento persistido que nunca vira ledger. A #254 acrescenta **recorrências mensais manuais**: o usuário descreve uma receita ou despesa esperada, vê as ocorrências previstas e, **por ato explícito**, registra uma delas como fato.

A decisão precisa responder: onde mora o modelo e onde mora cada instância, como a geração evita duplicata sem processo de fundo, como uma edição trata o que já foi previsto, como uma ocorrência vira exatamente um Movement sem estado parcial, quem lê e quem escreve, e o que acontece quando o Movement é estornado.

## Decisão

### Três camadas, uma autoridade

| Camada | Tabela | Pode mudar saldo? |
|---|---|---|
| regra (modelo) | `finance.recurrences` | nunca |
| ocorrência (instância) | `finance.recurrence_occurrences` | nunca; `PENDING`, `SKIPPED` e `SUPERSEDED` não existem para o ledger |
| fato realizado | `finance.movements` (`STANDARD`) | só por **Registrar**, uma vez por ocorrência |

`finance.movements` **não ganha coluna nem ponteiro** de recorrência. O vínculo mora na ocorrência (`movement_id`, único) e é gravado uma vez, na transação que cria o Movement. Nenhum processo de fundo, agendador, worker ou leitura cria Movement, ocorrência ou saldo. Nenhuma coluna monetária guarda saldo ou realizado.

### Contrato v1

- somente `MONTHLY`; `result_effect` `INCOME` ou `EXPENSE`; `expected_amount > 0` em `NUMERIC(24,8)`; moeda igual à da conta (FK composta com a conta); descrição de 1 a 256 caracteres sem controle (é a descrição que o Movement herdará);
- `account_id` obrigatório, ativa e **do próprio operador** na criação; a audiência de leitura é a **da conta** (a política de linha consulta `finance.accounts` sob a RLS da conta), sem ACL paralela;
- `start_date` e `end_date` opcional (inclusivos, comparados com a data **agendada**); `day_of_month` 1..31;
- `status` `ACTIVE`/`PAUSED`; `version` com CAS; identidade (conta, efeito, moeda, `start_date`, dono) imutável;
- escrita e realização **somente do dono** (o dono da conta), alinhadas ao writer atual de Movement; ler nunca implica escrever (`canEdit` é decidido no servidor e no banco). Conhecer um UUID não concede nada: regra, ocorrência ou conta inexistente, invisível ou de outra residência são o mesmo erro sanitizado.

### Calendário mensal: só `date`, relógio injetado

A âncora é o dia do mês; se ele não existe no mês, usa-se o último dia (31 → 28/29 em fevereiro, 30 → 30 quando existir). O cálculo é função pura de `date` (`monthly_occurrence_date`), sem fuso e sem `now()` no domínio. O relógio (`date`) é injetado no serviço e usado em exatamente dois pontos: o **horizonte** da geração e o limite "futuro" da edição. O gatilho do banco recomputa a mesma data, de modo que nenhum cliente ou store fabrica uma data de ocorrência.

### Ocorrência: UUID v4 e snapshot da revisão

Cada ocorrência tem identidade UUID v4 e guarda o snapshot da revisão que a originou (`rule_version`, efeito, moeda, valor esperado, descrição, conta, dono) e o mês (`period_start`) mais a data agendada. Estados: `PENDING`, `REALIZED`, `SKIPPED`, `SUPERSEDED`. Só `PENDING` se move; os demais são terminais e **imutáveis no banco** (gatilho), inclusive para o runtime. Existe no máximo **uma ocorrência viva por regra e mês**: índice único parcial `(recurrence_id, period_start) WHERE status <> 'SUPERSEDED'`. Ocorrências `SUPERSEDED` são histórico e podem coexistir com a substituta do mesmo mês.

### Geração: explícita, limitada, replay-safe e concorrente

Gerar é um comando do usuário sobre **uma regra** e uma janela explícita `[fromPeriod, throughPeriod]`:

- no máximo **12 meses** por chamada e nunca além de **24 meses** depois do mês de `today` (relógio injetado); janela aberta não existe;
- só meses cuja data agendada cai entre `start_date` e `end_date` geram;
- regra `PAUSED` **não gera** (checado no serviço e **no gatilho de inserção**: nem SQL direto contorna);
- a regra é travada (`SELECT … FOR UPDATE`) durante a geração, serializando contra edição, pause e outra geração; a inserção usa `ON CONFLICT DO NOTHING` no índice único parcial. Repetir ou concorrer converge para o mesmo conjunto, sem duplicata e sem erro; a resposta informa quantas foram criadas e devolve as vivas da janela;
- nada gera sozinho: sem leitura que materialize, sem job.

### Edição, pause e histórico

- editar (`PUT`) exige `expectedVersion`; versão antiga é `409` e não grava. Editáveis: descrição, valor esperado, dia do mês, término. Edição que não muda nada não grava nem incrementa a versão (mas o CAS vale);
- **tratamento explícito das futuras `PENDING`:** na mesma transação, toda `PENDING` com data agendada `>=` hoje (relógio injetado) que a nova revisão **não descreve mais** (descrição, valor, data pelo novo dia, fim) vira `SUPERSEDED`; a resposta traz `supersededCount`. As compatíveis permanecem. `REALIZED`, `SKIPPED` e as `PENDING` vencidas (data anterior a hoje) **nunca** são tocadas nem reinterpretadas: o usuário ainda pode registrá-las ou pulá-las com o snapshot original. Uma nova geração cria a substituta na revisão corrente;
- `pause` e `resume` não têm CAS (são comandos de estado alvo e idempotentes): já estar no estado pedido devolve a regra sem nova versão; mudar incrementa a versão. Pausar **não apaga nem altera** ocorrências; retomar não gera nada por si;
- **não há `DELETE`** (nem grant): nada é destrutivo na v1.

### Skip

`PENDING → SKIPPED` é um comando explícito, idempotente (repetir devolve a ocorrência já pulada), e `REALIZED`, `SUPERSEDED` ou outra terminal falham fechado (`409`). Pular nunca cria Movement nem altera saldo.

### Realização: um Movement, um vínculo, uma transação

`POST /finance/recurrence-occurrences/{id}/realize` exige `idempotencyKey` UUID v4, `actualAmount > 0`, `effectiveDate` e `competenceDate`. O valor real pode diferir do esperado (a regra não muda).

**Atomicidade (decisão central).** O writer canônico de Movement (`FinancialMovementStore.create_movement`) abria sua própria transação, o que impediria atomicidade com o vínculo. Em vez de compensação frágil (criar o Movement e depois ligar, ou ligar e depois criar), o corpo do writer foi extraído, **sem mudança de comportamento**, para uma função que opera numa transação do chamador (`create_standard_movement_in_transaction`); `create_movement` passa a chamá-la. A recorrência a usa dentro da própria transação: mesmas validações do writer (membership, conta ativa do dono, moeda, âncora de saldo inicial), mesma RLS, mesmo audit `MOVEMENT_CREATED`, mesmo digest. Se qualquer passo falha, **nada** persiste: nem Movement nem vínculo. Não existe estado "Movement sem ocorrência" nem "ocorrência sem Movement".

Dentro da transação, em ordem: contexto e membership → trava da ocorrência (`FOR UPDATE`) → replay → revalidação (ocorrência `PENDING`; regra e conta ativa/dono/moeda; residência) → Movement canônico → atualização da ocorrência para `REALIZED` com `movement_id`. O gatilho do banco só aceita `REALIZED` se o Movement é `STANDARD`, da mesma conta, efeito e moeda, criado **nesta transação** pelo mesmo operador; `movement_id` é `UNIQUE`.

- **Retry idêntico converge:** a ocorrência guarda a chave de realização e o digest do pedido (valor, datas); a mesma chave com o mesmo material devolve o mesmo Movement (nada novo). Mesma chave com outro material, ou outra chave sobre ocorrência já realizada, falha fechado (`409`);
- **Concorrência:** a trava da ocorrência serializa; o perdedor relê `REALIZED` e converge (mesma chave) ou falha (chave diferente). Nunca dois Movements;
- a chave da realização não é a chave de idempotência do Movement: este usa uma chave própria gerada na transação, de modo que uma chave de realização nunca adota um Movement avulso preexistente;
- **sem classificação automática:** o Movement nasce sem alocação; categorização segue os fluxos #245/#247/#249.

### Estorno não reabre

Estornar o Movement vinculado (ADR-0020) é um evento do ledger. A ocorrência continua `REALIZED`; a leitura expõe `movementState` derivado (`ACTIVE` ou `REVERSED`) pela existência do estorno do Movement vinculado. Nenhum Movement novo é criado e nada volta a `PENDING`.

### Leitura

A ocorrência lista o esperado (snapshot) e, quando `REALIZED`, o realizado (`actualAmount`, `effectiveDate`, `competenceDate` lidos do Movement vinculado) e `movementState`. A leitura nunca escreve, nunca calcula saldo e é limitada (listas com teto, janelas de no máximo 12 meses).

### Fora do audit financeiro fechado

Como orçamentos e regras de categorização, o ciclo de vida de regra e ocorrência é planejamento e não amplia `finance.audit_events`. A criação do Movement continua auditada pelo writer canônico; a regra e a ocorrência carregam autoria e timestamps.

## Alternativas consideradas

- **Regras que geram Movements por agendador (ou ao ler):** cria fato sem ato do usuário. Rejeitada; viola a invariante central.
- **Ocorrência prevista como Movement `PENDING` no ledger:** segundo estado no ledger append-only e saldo contaminado. Rejeitada.
- **`recurrence_id` / `occurrence_id` em `finance.movements`:** viola ADR-0022 e o append-only. Rejeitada; o vínculo é da ocorrência.
- **Compensação (criar Movement e depois ligar, com reparo):** deixa janelas de estado parcial. Rejeitada; atomicidade real pela transação compartilhada.
- **Segunda função de escrita de Movement só para recorrências:** duplicaria validações do writer. Rejeitada; o writer canônico foi extraído e reutilizado.
- **Reinterpretar `PENDING` futuras no lugar de superseder:** mudaria silenciosamente o que o usuário viu. Rejeitada.
- **Reabrir a ocorrência no estorno:** geraria novo ciclo sem ato do usuário. Rejeitada.
- **`DELETE` de regra:** destrutivo; arquivamento/encerramento por `endDate` e pause cobrem a v1.
- **Frequências além de mensal, assinaturas assistidas, parciais, reajuste, alertas:** fora de escopo (#254).

## Consequências

- previsão e fato ficam em camadas distintas; saldo e extrato não mudam por regra, ocorrência `PENDING`, `SKIPPED` ou `SUPERSEDED`;
- uma regra editada deixa `SUPERSEDED` como histórico e exige nova geração; o usuário vê o que mudou (`supersededCount`);
- o writer de Movement ganhou um ponto de entrada transacional compartilhado; seu comportamento externo é idêntico (provado pelos testes existentes);
- uma edição simultânea perde para o CAS com `409`; pause/resume convergem por estado.

## Validação

Domínio (calendário 28–31, fevereiro, bissexto, início/fim), schema e migration simétrica, RLS (PERSONAL, HOUSEHOLD, SHARED, entre residências), CAS e concorrência, geração limitada, idempotente e concorrente, pause/resume, edição e `SUPERSEDED`, skip, realização (um Movement, replay, concorrência, falha intermediária sem estado parcial, conta inativa, esperado × real), estorno que não reabre, zero Movement antes de Registrar, zero saldo por `PENDING`/`SKIPPED`, API HTTP, contratos de qualidade, Flutter (sem retry automático nem sucesso otimista) e o smoke vertical da #254.

## Referências

- #180, #254
- ADR-0015, ADR-0019, ADR-0020, ADR-0021, ADR-0022, ADR-0024, ADR-0025, ADR-0026
- `docs/architecture/FINANCIAL_RECURRENCES.md`
