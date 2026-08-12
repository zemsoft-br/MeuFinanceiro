# ADR-0020 — Persistência de Movement, idempotência e integridade de reversão

- Status: Accepted
- Data: 2026-08-11
- Decisores: mantenedores

## Contexto

O ADR-0019 definiu `Movement` como evento financeiro canônico append-only: um efeito `Money` assinado em exatamente uma conta, com resultado econômico `INCOME`, `EXPENSE` ou `NEUTRAL`, datas separadas de caixa e competência e correção por novo evento de reversão.

Persistir esse contrato exige resolver quatro problemas antes de qualquer API pública:

1. retries não podem duplicar efeitos financeiros;
2. reversões concorrentes não podem produzir dois cancelamentos integrais do mesmo original;
3. a audiência do ledger não pode divergir da audiência da conta;
4. o saldo de abertura imutável não pode coexistir com Movements efetivos anteriores ao seu anchor.

## Decisão

### Ledger append-only em PostgreSQL

A tabela canônica é:

```text
finance.movements
```

Cada linha possui UUID v4 local e opaco, `Money` persistido como `currency + numeric(24,8)`, `result_effect`, `role`, datas financeiras, auditoria de criação e material de idempotência.

O runtime recebe na tabela somente:

```text
SELECT
INSERT
```

Não recebe privilégio de `UPDATE` nem `DELETE`.

Nenhuma coluna de saldo atual, disponível ou cache equivalente é adicionada. O saldo continua derivável de opening balance + soma de Movements.

### Idempotency key separada do resource ID

Cada operação de criação ou reversão exige uma `idempotency_key` UUID v4 independente do `movement_id`.

A unicidade é:

```text
(installation_id, idempotency_key)
```

A linha persiste também `request_digest`, SHA-256 de material canônico versionado.

Semântica:

```text
mesma key + mesmo digest       -> replay do mesmo Movement
mesma key + digest diferente   -> conflito fail-closed
```

O digest usa namespace versionado e os campos normalizados que definem a operação. O operador faz parte do material para impedir que uma chave seja reutilizada silenciosamente por outro ator.

Na criação concorrente, `INSERT ... ON CONFLICT DO NOTHING` converge para a linha vencedora e o retry relê o evento persistido. Um novo UUID lógico pode ser gerado transitoriamente pelo processo perdedor, mas nunca se torna resource ID persistido.

### Reversão integral serializada

A reversão recebe somente:

```text
movement_id original
effective_date
competence_date
reason
```

O runtime primeiro lê o original `STANDARD` sob RLS e valida ownership de conta `ACTIVE`. Antes de verificar/criar a reversão, adquire um row lock real `FOR UPDATE` por meio da função PostgreSQL:

```text
finance.lock_standard_movement_for_reversal(...)
```

Essa função existe porque o PostgreSQL exige privilégio `UPDATE` para locking clauses como `SELECT ... FOR UPDATE`; conceder esse privilégio à tabela quebraria o contrato append-only do runtime.

A função é uma fronteira estreita de privilégio:

- `SECURITY DEFINER`;
- `search_path` fixado em `pg_catalog, pg_temp`;
- tabelas referenciadas com schema explícito;
- revalida `installation_id`, `residence_id` e `operator_id` contra o contexto da sessão;
- exige membership ativa;
- exige que o operador seja owner da conta `ACTIVE`;
- aceita apenas target `STANDARD` no mesmo escopo;
- retorna apenas booleano, nunca material financeiro;
- `EXECUTE` é revogado de `PUBLIC` e concedido somente ao role runtime configurado.

Como `finance.movements` usa `FORCE ROW LEVEL SECURITY`, o locking clause também precisa ser permitido por uma policy RLS de `UPDATE`. A migration cria `finance_movements_lock_update` com `USING` restrito a `STANDARD`, membership ativa e conta `ACTIVE` pertencente ao operador corrente. Essa policy **não concede privilégio SQL de `UPDATE`**: o role runtime continua sem `UPDATE` e não consegue executar `UPDATE` nem `SELECT ... FOR UPDATE` diretamente. Ela permite apenas que o definer autorizado atravesse o RLS para adquirir o row lock.

O lock permanece até o fim da transação e serializa tentativas concorrentes sobre o mesmo original sem conceder capacidade de `UPDATE` ao chamador.

Após adquirir o lock, o store reconsulta idempotência e existência de reversão. Assim um retry que aguardou outra transação converge para o mesmo evento, enquanto uma segunda reversão com chave diferente falha como já revertida.

A reversão persiste:

- mesma conta;
- mesma moeda;
- mesmo `result_effect`;
- `amount = -original.amount`;
- `role = REVERSAL`;
- referência ao original `STANDARD`.

Uma unique constraint em `reversal_of_id` permite no máximo uma reversão integral por original.

Uma FK composta fecha a referência pela mesma installation, residence, account, currency, result effect e target role `STANDARD`. Assim uma reversão não pode apontar para outra reversão nem mudar o efeito financeiro do target.

Além da derivação no store, um trigger `BEFORE INSERT` valida no PostgreSQL que o amount da reversão é exatamente o negativo do original. A integridade permanece protegida mesmo se uma inserção autorizada contornar o store.

### Audiência herdada da conta

`Movement` não possui owner, visibility scope ou grants independentes.

A política `SELECT` exige membership ativa na residence corrente e existência da conta sob a própria RLS de `finance.accounts`. Portanto:

- `PERSONAL` permanece visível apenas ao owner;
- `HOUSEHOLD` é visível aos membros ativos da residência;
- `SHARED` respeita os grants existentes da conta.

Conhecer `movement_id` não concede acesso.

### Escrita owner-only nesta fase

Nesta primeira persistence, somente o `owner_operator_id` de uma conta `ACTIVE` pode criar Movement ou reversão.

A política `INSERT` exige:

- residence corrente;
- `created_by_operator_id` igual ao operador corrente;
- membership ativa;
- conta pertencente ao operador corrente;
- conta `ACTIVE`.

Membros que conseguem ler uma conta `HOUSEHOLD` ou `SHARED` não recebem capacidade implícita de gravação. Uma futura matriz de capacidades por papel deverá ser decisão explícita.

### Relação com opening balance

Se a conta possui opening balance, todo novo Movement deve satisfazer:

```text
effective_date >= opening_balance.effective_date
```

A restrição existe no store e na política RLS de insert.

`competence_date` não recebe essa restrição. Competência pode anteceder o anchor porque não altera a posição de caixa anterior ao saldo de abertura.

### Erros e material sensível

Erros públicos da persistence são sanitizados. Amount, description, reason, IDs externos e digests não são interpolados em mensagens genéricas.

O record persistido é imutável e seu `repr` redige amount, descrição, reason, datas e identidades sensíveis.

## Alternativas consideradas

### Usar movement ID como idempotency key

Rejeitada. Misturaria identidade do recurso com identidade operacional de retry e contrariaria o ADR-0017.

### Upsert destrutivo por idempotency key

Rejeitada. Um retry nunca deve alterar retrospectivamente o conteúdo financeiro de um evento já persistido.

### Reversão por UPDATE do original

Rejeitada. Perderia auditabilidade e alteraria retrospectivamente saldos e relatórios.

### Conceder UPDATE ao runtime apenas para FOR UPDATE

Rejeitada. O row lock exige esse privilege, mas concedê-lo à tabela enfraqueceria o contrato explícito de runtime append-only. O lock privilegiado ficou encapsulado em função mínima com `EXECUTE` seletivo. A policy RLS `FOR UPDATE` existe apenas para o row-lock sob `FORCE RLS`; sem `GRANT UPDATE`, ela não cria capacidade de mutação para o runtime.

### Controlar reversão apenas no Python

Rejeitada. A derivação no store é necessária, mas a invariância crítica de amount também fica protegida no PostgreSQL.

### Copiar visibility scope/grants para Movement

Rejeitada. Duplicaria ACL e permitiria divergência entre conta e ledger.

### Permitir gravação a qualquer membro com leitura

Adiada. Leitura e capacidade de mutação financeira são permissões diferentes e exigem matriz explícita de papéis.

## Consequências positivas

- retries convergem sem duplicar efeitos financeiros;
- resource IDs permanecem separados de IDs operacionais;
- reversões são integrais, únicas e auditáveis;
- concorrência sobre reversão é serializada por row lock real;
- runtime continua sem `UPDATE/DELETE` na tabela de ledger;
- RLS do ledger acompanha automaticamente a audiência da conta;
- opening balance e novos Movements não se sobrepõem historicamente;
- integridade crítica de reversão existe também no banco.

## Consequências negativas e riscos

- o ledger persiste material de idempotência enquanto o evento existir;
- row lock serializa reversões do mesmo original e pode gerar espera curta sob contenção;
- a função `SECURITY DEFINER` passa a ser uma fronteira privilegiada e deve permanecer pequena, não-vazante e coberta por testes de privilégios;
- a policy `FOR UPDATE` precisa permanecer desacoplada de qualquer `GRANT UPDATE` ao runtime;
- membros com audiência de leitura ainda não possuem capacidade configurável de gravação;
- partial refund/correction continuam exigindo contrato futuro;
- transferência ainda precisa de operação atômica própria sobre dois Movements `NEUTRAL`.

## Validação

A implementação deve cobrir sinteticamente:

- sinais válidos de `STANDARD`;
- replay e conflito de idempotência;
- retry concorrente sem duplicação;
- reversão com amount exatamente oposto;
- no máximo uma reversão integral;
- reversão de reversão rejeitada;
- concorrência de reversão serializada;
- row lock executável pelo runtime sem `UPDATE` na tabela;
- `SECURITY DEFINER` com `search_path` fechado e `PUBLIC EXECUTE` revogado;
- policy `FOR UPDATE` restrita a `STANDARD` owner-only sob `FORCE RLS`;
- tentativa direta do runtime de `SELECT ... FOR UPDATE` rejeitada;
- membro visível sem capacidade de lock privilegiado e sem spoof de owner;
- `PERSONAL`, `HOUSEHOLD` e `SHARED` sob RLS;
- owner-only create/reverse;
- membership desabilitada;
- bloqueio antes do opening anchor;
- runtime sem `UPDATE/DELETE`;
- trigger de amount da reversão;
- downgrade/reupgrade simétrico da migration.

## Referências

- #124
- #141
- ADR-0015
- ADR-0016
- ADR-0017
- ADR-0018
- ADR-0019
- `docs/architecture/FINANCIAL_MOVEMENTS.md`
