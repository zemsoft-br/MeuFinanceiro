# Movement canônico e ledger append-only

Status: **persistência base da Fase 1 / issue #141**.

Normativo: ADR-0019 e ADR-0020.

## Unidade do ledger

Um Movement é um efeito monetário efetivo em uma única conta financeira canônica.

```text
amount > 0 -> aumenta saldo
amount < 0 -> reduz saldo
amount = 0 -> inválido
```

Não existe campo redundante `credit/debit`.

O Movement não é projeção, recorrência futura, observação bancária, fatura, orçamento ou saldo.

## Resultado econômico

```text
INCOME
EXPENSE
NEUTRAL
```

Para eventos originais:

```text
INCOME  -> amount positivo
EXPENSE -> amount negativo
NEUTRAL -> positivo ou negativo, nunca zero
```

`NEUTRAL` permite representar futuramente efeitos patrimoniais sem tratá-los como receita/despesa.

## Datas

Todo evento possui:

```text
effective_date
competence_date
```

A primeira participa de caixa/saldo; a segunda de competência. Ambas são `date` e não possuem default implícito entre si.

## Persistência canônica

O ledger base é persistido em:

```text
finance.movements
```

Cada linha contém, entre outros campos:

```text
id UUID v4
installation_id
residence_id
account_id
currency
amount NUMERIC(24,8)
result_effect
role STANDARD | REVERSAL
effective_date
competence_date
created_by_operator_id
idempotency_key UUID v4
request_digest SHA-256
created_at
```

Movements são append-only. O runtime recebe somente `SELECT, INSERT` na tabela; não recebe `UPDATE` nem `DELETE`.

## Audiência

Movement herda integralmente a audiência da conta. Não possui owner, visibility scope ou grants independentes.

A política RLS de leitura exige membership ativa e consulta `finance.accounts` sob a RLS da própria conta. Com isso:

- `PERSONAL`: somente owner;
- `HOUSEHOLD`: membros ativos da residência;
- `SHARED`: owner e membros explicitamente granted.

Conhecer `movement_id` não concede acesso.

## Escrita

Nesta primeira persistence, criação e reversão são owner-only.

O operador precisa:

- estar em membership ativa;
- ser `owner_operator_id` da conta;
- operar na residence corrente;
- usar conta `ACTIVE`.

Audiência de leitura não implica capacidade de escrita.

## Idempotência

Toda criação/reversão exige `idempotency_key` UUID v4 operacional e independente do `movement_id`.

Escopo:

```text
(installation_id, idempotency_key)
```

Cada request persiste `request_digest` SHA-256 de material canônico versionado.

```text
mesma key + mesmo digest       -> replay do mesmo Movement
mesma key + digest diferente   -> conflito fail-closed
```

Criações concorrentes do mesmo request convergem para uma única linha persistida.

## Reversão

O comando de reversão recebe somente:

```text
movement_id
effective_date
competence_date
reason
```

Amount, conta, moeda e resultado são derivados do original.

A reversão integral possui:

- mesmo `account_id`;
- mesma moeda;
- mesmo `result_effect`;
- `amount = -original.amount`;
- `role = REVERSAL`;
- referência a um target `STANDARD`.

### Serialização sem abrir UPDATE no ledger

O original precisa de row lock `FOR UPDATE` antes da decisão de reversão concorrente. Como esse lock exige privilégio `UPDATE` no PostgreSQL, o runtime não executa o locking clause diretamente.

Ele chama:

```text
finance.lock_standard_movement_for_reversal(...)
```

A função é `SECURITY DEFINER`, possui `search_path` fechado, revalida contexto/membership/ownership e executa `FOR UPDATE OF m` somente para um `STANDARD` da conta `ACTIVE` pertencente ao operador corrente.

Como `finance.movements` usa `FORCE ROW LEVEL SECURITY`, existe também a policy `finance_movements_lock_update FOR UPDATE`. Ela deixa o definer atravessar o RLS somente para `STANDARD` da conta ativa pertencente ao operador e com membership ativa. Policy RLS não substitui `GRANT`: o role runtime continua sem privilégio `UPDATE` e uma tentativa direta de `SELECT ... FOR UPDATE` permanece negada.

`EXECUTE` é revogado de `PUBLIC` e concedido ao role runtime. A tabela `finance.movements` continua com apenas `SELECT, INSERT` para esse role.

Após o lock, o store reconsulta idempotência e reversão prévia. Isso faz retries concorrentes convergirem e garante que duas idempotency keys distintas não produzam duas reversões do mesmo original.

`reversal_of_id` é unique, portanto existe no máximo uma reversão integral por original.

Uma FK composta garante que a reversão aponta para o mesmo account/currency/result effect e para role `STANDARD`. Um trigger PostgreSQL valida novamente que o amount é exatamente o negativo do original.

Não é possível reverter uma reversão.

## Opening balance

Se a conta possui opening balance:

```text
movement.effective_date >= opening_balance.effective_date
```

O opening balance representa o saldo no início da sua `effective_date`; Movements na mesma data são válidos e ocorrem depois do anchor.

`competence_date` pode ser anterior ao opening date porque competência não altera caixa anterior ao anchor.

## Categoria

O contrato base não contém `category_id`. O vínculo classificatório permanece etapa posterior porque contas `SHARED` e categorias atualmente possuem modelos de audiência diferentes.

## Entrada manual de receita e despesa

A #167 define um caso de uso provider-neutral sobre o mesmo ledger. A intenção manual recebe uma **magnitude positiva** e um tipo explícito:

```text
INCOME  -> Movement STANDARD com amount positivo
EXPENSE -> Movement STANDARD com amount negativo
```

O chamador de alto nível não inverte sinal para despesa. A camada financeira converte a magnitude positiva para o `FinancialMovementDraft` assinado e delega a persistência exclusivamente a `create_movement(...)`.

Cada lançamento manual bem-sucedido produz exatamente um `Movement` `STANDARD`. O caso de uso não cria outra tabela, outra entidade persistida de receita/despesa, outra idempotency key ou um segundo ledger.

A fronteira de persistência é um `Protocol` mínimo. O módulo de entrada manual não importa SQLAlchemy nem `meufinanceiro_persistence`; por isso autorização, owner-only, conta `ACTIVE`, RLS, opening anchor, replay idempotente e concorrência continuam sendo aplicados pelo store canônico.

Correções continuam sendo novos eventos de reversão. Categoria permanece opcional e fora desse caso de uso.

## Transferência futura

Transferência será uma operação atômica externa ao Movement básico:

```text
origem  -> NEUTRAL negativo
destino -> NEUTRAL positivo
```

Os dois eventos serão ligados por um `transfer_id` distinto dos `movement_id` e das idempotency keys.

## Saldo

O saldo canônico permanece derivável por:

```text
opening balance opcional + soma dos Movement.amount efetivos
```

Não existe coluna de saldo em `finance.accounts` nem cache de saldo introduzido pela persistence de Movement.

## Fronteiras atuais

Store:

```text
create_movement
reverse_movement
get_movement
list_movements
```

Caso de uso manual:

```text
FinancialManualEntryDraft
FinancialManualEntryService.record
```

Sem:

```text
update_movement
delete_movement
upsert destrutivo
```

## Fora do escopo

- saldo materializado/query de saldo;
- category link;
- transferências;
- rateios;
- partial refund/correction;
- API/FastAPI;
- Flutter;
- Pluggy/importadores;
- cartões/faturas;
- empréstimos;
- deploy/HML/produção.
