# Desconexão bancária explícita e preservação do histórico

## Objetivo

A desconexão remove o vínculo operacional com o provider sem apagar o histórico bancário já materializado localmente.

O PostgreSQL local continua sendo a fonte de verdade para o estado conhecido da conexão e para toda evidência já persistida. A chamada externa de desconexão não transforma provider IDs em autoridade pública: o cliente continua operando exclusivamente por `connection_id` UUID local.

## Sequência canônica

```text
connection_id local
→ membership ativa + RLS/residence scope
→ SELECT connection FOR UPDATE
→ rejeitar sync REQUESTED/RUNNING
→ observar estado remoto
→ se remoto já DISCONNECTED: recovery local
→ senão: provider.disconnect(...)
→ external_accounts.status = disconnected
→ connections.status = DISCONNECTED
→ COMMIT
```

Se a conexão já estiver `DISCONNECTED` localmente, a operação é replay e não realiza I/O externo.

## Por que o row lock atravessa o I/O externo

`begin_manual_sync()` já bloqueia a mesma row de `integrations.connections` com `FOR UPDATE` antes de criar um `sync_run`.

A desconexão reutiliza essa fronteira de concorrência e mantém o row lock enquanto observa/muta o provider. Isso é deliberado para este comando raro e destrutivo:

- duas desconexões concorrentes são serializadas;
- uma nova sync não pode nascer entre a observação remota e o commit de `DISCONNECTED`;
- não é necessário criar tabela/status transitório apenas para reservation;
- não é necessário consumir uma segunda conexão do pool para advisory lock;
- nenhuma migration concorrente é criada enquanto a cadeia financeira #170/#171 está pendente.

O custo é manter uma transação PostgreSQL aberta durante uma operação de rede. Portanto uma implementação produtiva de `disconnect` em qualquer provider **deve possuir timeout de transporte estritamente limitado** e nunca pode aguardar indefinidamente.

Neste recorte, o adapter Pluggy continua `UNSUPPORTED`; os testes externos usam somente provider fake e nenhuma chamada Pluggy real é autorizada.

## Falha distribuída e recuperação

PostgreSQL e provider não formam uma transação distribuída.

Se o provider falhar antes de confirmar a desconexão:

```text
provider error
→ exception
→ rollback PostgreSQL
→ conexão local permanece inalterada
```

Se o provider concluir a desconexão, mas a finalização/commit PostgreSQL falhar:

```text
provider = DISCONNECTED
local = estado anterior
→ erro LOCAL_FINALIZATION_PENDING
```

A tentativa explícita seguinte **não repete a mutação externa cegamente**. Ela primeiro chama `get_connection()`:

```text
remote.status == DISCONNECTED
→ não chamar disconnect novamente
→ finalizar apenas o estado local
```

Isso também cobre queda do processo depois da mutação externa e antes do commit, desde que o provider consiga expor o estado desconectado na observação seguinte.

## Estado local após sucesso

A finalização local é atômica:

```text
integrations.connections
  status = DISCONNECTED
  requires_user_action = false
  next_refresh_allowed_at = null
  provider_reason_code = null
  disconnected_at = transaction_timestamp()

integrations.external_accounts
  status = disconnected
```

`disconnected_at` não é reescrito em replay local.

## Retenção

A desconexão **não apaga**:

- connection capabilities;
- sync runs e cursores históricos;
- external observations;
- reconciled transactions;
- decisões banking → ledger;
- Movements financeiros;
- qualquer outro histórico que possua política de retenção própria.

Nenhuma operação `DELETE` faz parte do runtime de desconexão.

## Autorização

Antes de qualquer I/O externo:

- installation e residence precisam corresponder à conexão local;
- o operador precisa possuir membership ativa nessa residence;
- a conexão precisa ser visível sob o contexto corrente;
- não pode existir sync `REQUESTED` ou `RUNNING` para a conexão.

Falha de membership/cross-residence é tratada como recurso não encontrado, sem revelar a existência da conexão.

## Estado posterior

Após `DISCONNECTED`:

- `begin_manual_sync()` continua rejeitando a conexão pelo contrato existente;
- reautenticação continua rejeitando `DISCONNECTED` pelo contrato existente;
- reconectar futuramente requer fluxo explícito novo; não é inferido por refresh/sync.

## Segurança e observabilidade

Erros/resultados públicos não incluem:

- external connection ID;
- Item ID/clientUserId;
- provider reason code;
- credenciais;
- token;
- payload HTTP;
- URL externa.

Falhas inesperadas do adapter são convertidas em erro sanitizado apenas na fronteira da chamada ao provider. Erros de programação internos não devem ser silenciosamente mascarados pelo orchestration.

## Fora deste recorte

- endpoint FastAPI;
- Flutter/UX de confirmação;
- implementação real do delete/revoke Pluggy;
- consent renewal;
- retenção/expurgo físico;
- cartões/faturas;
- webhooks;
- deploy, HML ou produção.
