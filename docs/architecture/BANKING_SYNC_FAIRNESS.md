# Continuidade justa da sincronização bancária entre contas

Status: **implementação da Epic #63 / issue #117**.

## Problema

A primeira orquestração manual (#115) usa limites globais por run e recovery cursor por conta. O cursor representa exclusivamente uma paginação interrompida e é removido na página terminal.

Sem estado adicional, uma nova operação não distingue uma conta que já concluiu o full-scan de outra que ainda não foi percorrida no ciclo multi-conta. Além disso, uma única conta com paginação longa poderia consumir repetidamente todo o orçamento de páginas antes das demais.

## Decisão

A #117 mantém o cursor totalmente opaco e adiciona estado local explícito:

```text
integrations.sync_cycles
integrations.sync_cycle_accounts
```

Nenhum cursor sentinela, prefixo local ou valor reservado é introduzido.

## Ciclo

`sync_cycles` representa uma passagem lógica por todas as contas transacionais presentes no snapshot da conexão.

Estados:

```text
open
completed
```

Existe no máximo um ciclo `open` por conexão, garantido por índice parcial único no PostgreSQL.

Um novo ciclo nasce somente quando não existe ciclo aberto. Depois que um ciclo é concluído, a próxima sincronização manual cria outro ciclo e todas as contas elegíveis atuais voltam a ficar pendentes.

## Progresso por conta

`sync_cycle_accounts` registra a participação de uma conta **local** no ciclo corrente:

```text
cycle_id
residence_id
connection_id
external_account_record_id  # UUID local de integrations.external_accounts
active_in_latest_snapshot
pages_committed              # scheduler metadata local
completed_at
```

O identificador externo do provider não é duplicado nessa tabela. O store resolve o UUID local a partir do snapshot já persistido e só projeta o `external_account_id` transitoriamente no DTO interno usado pelo orquestrador. Esse valor permanece redigido de `repr` e nunca vira resultado público.

A migration adiciona uma candidate key explícita `(id, connection_id, residence_id)` em `external_accounts`, permitindo que a FK de membership feche o escopo da conta local no próprio PostgreSQL.

`pages_committed` começa em zero e é incrementado somente depois que uma nova página é confirmada. Ele não contém cursor, quantidade de transações nem valor financeiro; existe exclusivamente para ordenar o orçamento entre contas.

O estado não depende da ordem retornada pelo provider nem usa o identificador externo como marcador de progresso.

Uma conta é concluída somente quando sua página terminal foi confirmada. Página não terminal incrementa `pages_committed`, mas nunca grava `completed_at`.

## Reconciliação do snapshot

Depois de `replace_external_accounts`, `prepare_sync_cycle` recebe somente as contas `BANK` e `CREDIT` do snapshot atual.

Na mesma transação local:

1. bloqueia a conexão;
2. valida as contas elegíveis dentro da mesma residência/conexão;
3. obtém ou cria o ciclo aberto;
4. marca memberships antigos como fora do snapshot atual;
5. resolve os UUIDs locais das contas;
6. rejeita qualquer conta persistida com tipo não transacional;
7. cria/reativa memberships do snapshot corrente;
8. preserva `pages_committed` e `completed_at` de memberships já existentes;
9. se nenhuma conta ativa estiver pendente, conclui o ciclo.

Uma conta que desaparece do snapshot não é apagada, desconectada nem inferida como removida. Ela apenas deixa de bloquear o ciclo corrente. Se reaparecer no mesmo ciclo, seu progresso anterior é preservado; se reaparecer em ciclo futuro, participa do novo full-scan normalmente.

### Recuperação na fronteira entre ciclos

Um recovery cursor pertence ao full-scan que o produziu. Portanto ele não pode atravessar silenciosamente um ciclo já concluído.

Há duas regras distintas:

- no **primeiro ciclo persistente da #117**, cursores que já existiam da implementação #115 são preservados, permitindo retomar uma sincronização interrompida durante a transição de versão;
- quando já existe um ciclo persistente `completed` e um novo ciclo é criado, qualquer recovery cursor de `transactions` das contas elegíveis atuais é removido antes da nova membership. O novo ciclo começa full-scan limpo.

Isso resolve o caso de uma conta que tinha paginação incompleta, desapareceu do snapshot, deixou de bloquear o ciclo antigo e reapareceu depois. O cursor abandonado do ciclo antigo não é reutilizado no ciclo novo.

A limpeza é residence/connection-scoped, limitada às contas elegíveis já validadas e executada dentro da mesma transação que cria o ciclo.

## Fairness entre runs

O plano persistente ordena as contas ativas por:

```text
1. menor pages_committed
2. recovery cursor primeiro, em caso de empate
3. ordem local estável de membership
```

O orquestrador preserva essa ordem e só então aplica os limites do run.

Essa regra resolve dois casos:

```text
run 1 -> conta A conclui -> limite de contas
run 2 -> A é ignorada; conta B recebe orçamento
```

E também paginação longa:

```text
run 1 -> A confirma página 1 e atinge limite de páginas
run 2 -> B/C (0 páginas) vêm antes de A (1 página)
run posterior -> A retoma pelo cursor persistido
```

Assim o recovery cursor continua prioritário entre contas igualmente atendidas, mas não pode monopolizar indefinidamente as contas com menos serviço confirmado.

Quando a última conta ativa conclui, o ciclo muda para `completed`. O próximo run inicia um novo full-scan completo.

## Atomicidade da página

No caminho cycle-aware, `apply_transaction_page` executa uma única transação PostgreSQL:

```text
set residence context
  -> lock external account
  -> lock/validate cycle + local membership
  -> apply normalized observations
  -> confirm/remove recovery cursor
  -> increment pages_committed
  -> terminal? mark cycle account completed
  -> last active pending account? mark cycle completed
  -> COMMIT
```

Qualquer falha reverte observações, cursor, contador de serviço e progresso de conclusão juntos.

Replay exato de uma página **não terminal** já confirmada retorna antes de incrementar novamente `pages_committed`, preservando a idempotência do cursor. Depois que uma membership foi concluída, qualquer nova página usando aquele `sync_cycle_id` falha fechado. O orquestrador não tenta essa operação porque contas concluídas já foram retiradas do plano pendente antes de qualquer I/O do provider.

## RLS e integridade

As duas tabelas usam:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
```

A política usa diretamente `app.current_residence_id`.

FKs compostas garantem:

- ciclo e membership na mesma residência/conexão;
- UUID local da conta, membership e ciclo na mesma residência/conexão.

A remoção física de conexão/conta pode limpar apenas esse estado de scheduler por cascade. Isso não altera o histórico financeiro normalizado nem os `sync_runs` existentes.

## Compatibilidade do pacote provider-neutral

`ManualBankingSyncService` continua aceitando o contrato histórico `ManualSyncStore`. A extensão `SyncFairnessStore` é detectada estruturalmente para preservar testes/fakes e consumidores neutros existentes.

A composição canônica `BankingIntegrationStore` implementa `SyncFairnessStore`; portanto o runtime oficial usa o planejamento persistente da #117. O caminho legado permanece somente como compatibilidade estrutural e não cria estado de fairness.

## Redaction

Os DTOs de ciclo não exibem:

- external account ID;
- UUID local da conta;
- cursor;
- fingerprint;
- amount;
- descrição;
- UUID de ciclo/conexão/residência.

`pages_committed` pode aparecer em diagnóstico local redigido porque é apenas um contador operacional do scheduler. O resultado público de sincronização permanece inalterado.

## Fora do escopo

- `changed_since` incremental;
- sincronização automática/background;
- endpoint HTTP e Flutter;
- reconciliação com lançamentos financeiros;
- inferência de deleção por ausência;
- cartões/faturas/parcelas;
- investimentos/empréstimos;
- chamada Pluggy real;
- flags, deploy, HML ou produção.

## Validação

Os testes adicionados cobrem migration, persistência do ciclo, terminal atômico, mudança de membership, isolamento de escopo, RLS, redaction, limite de contas, rotação por limite de páginas e reset seguro de recovery cursors entre ciclos.

GitHub Actions não é gate operacional deste projeto. Validações não executadas nesta sessão permanecem declaradas como não executadas.