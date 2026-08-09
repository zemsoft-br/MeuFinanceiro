# Continuidade justa da sincronização bancária entre contas

Status: **implementação da Epic #63 / issue #117**.

## Problema

A primeira orquestração manual (#115) usa limites globais por run e recovery cursor por conta. O cursor representa exclusivamente uma paginação interrompida e é removido na página terminal.

Sem estado adicional, uma nova operação não distingue uma conta que já concluiu o full-scan de outra que ainda não foi percorrida no ciclo multi-conta. Em cardinalidades acima dos limites, contas anteriores poderiam ser lidas repetidamente antes de contas posteriores.

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
completed_at
```

O identificador externo do provider não é duplicado nessa tabela. O store resolve o UUID local a partir do snapshot já persistido e só projeta o `external_account_id` transitoriamente no DTO interno usado pelo orquestrador. Esse valor permanece redigido de `repr` e nunca vira resultado público.

A migration adiciona uma candidate key explícita `(id, connection_id, residence_id)` em `external_accounts`, permitindo que a FK de membership feche o escopo da conta local no próprio PostgreSQL.

O estado não depende da ordem retornada pelo provider nem usa o identificador externo como marcador de progresso.

Uma conta é concluída somente quando sua página terminal foi confirmada. Página não terminal nunca grava `completed_at`.

## Reconciliação do snapshot

Depois de `replace_external_accounts`, `prepare_sync_cycle` recebe somente as contas `BANK` e `CREDIT` do snapshot atual.

Na mesma transação local:

1. bloqueia a conexão;
2. obtém ou cria o ciclo aberto;
3. marca memberships antigos como fora do snapshot atual;
4. resolve e valida os UUIDs locais das contas na mesma residência/conexão;
5. rejeita qualquer conta persistida com tipo não transacional;
6. cria/reativa memberships do snapshot corrente;
7. preserva `completed_at` de contas já concluídas;
8. se nenhuma conta ativa estiver pendente, conclui o ciclo.

Uma conta que desaparece do snapshot não é apagada, desconectada nem inferida como removida. Ela apenas deixa de bloquear o ciclo corrente. Se reaparecer em um ciclo futuro, volta a participar normalmente.

## Fairness entre runs

O orquestrador consulta o plano persistente e processa apenas contas ativas ainda pendentes.

Dentro desse conjunto, contas com recovery cursor continuam prioritárias. Assim:

```text
run 1 -> conta A conclui -> limite atingido
run 2 -> A é ignorada; conta B recebe orçamento
run 3 -> B é ignorada; conta C recebe orçamento
```

Quando a última conta ativa conclui, o ciclo muda para `completed`. O próximo run inicia um novo full-scan completo.

## Atomicidade da página terminal

No caminho cycle-aware, `apply_transaction_page` executa uma única transação PostgreSQL:

```text
set residence context
  -> lock external account
  -> lock/validate cycle + local membership
  -> apply normalized observations
  -> confirm/remove recovery cursor
  -> terminal? mark cycle account completed
  -> last active pending account? mark cycle completed
  -> COMMIT
```

Qualquer falha reverte observações, cursor e progresso de fairness juntos.

Um replay terminal de uma conta já concluída é tolerado de forma idempotente; uma página não terminal após conclusão falha fechado.

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

O resultado público de sincronização permanece inalterado.

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

Os testes adicionados cobrem migration, persistência do ciclo, terminal atômico, mudança de membership, isolamento de escopo, RLS, redaction e progressão entre múltiplos runs limitados.

GitHub Actions não é gate operacional deste projeto. Validações não executadas nesta sessão permanecem declaradas como não executadas.