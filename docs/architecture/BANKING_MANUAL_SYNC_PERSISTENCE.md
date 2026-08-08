# Persistência da sincronização bancária manual

Status: **implementação da fundação local da Epic #63 / issue #109**.

## Objetivo

Este recorte materializa a infraestrutura PostgreSQL necessária para uma futura
sincronização manual de contas e transações sem executar qualquer chamada ao
provider.

A fronteira adicionada persiste somente:

- a execução lógica/idempotente da sincronização;
- o catálogo minimizado de contas externas observadas;
- o cursor opaco confirmado por conta e recurso.

Transações/observações financeiras ainda não são persistidas neste estágio.

## Schema

A migration `0007_banking_manual_sync_persistence` adiciona ao schema
`integrations`:

```text
sync_runs
external_accounts
sync_cursors
```

Ela é linear sobre:

```text
0006_banking_residence_fk
```

Nenhuma tabela de domínio financeiro é alterada.

## `sync_runs`

`sync_runs` representa uma operação lógica de sincronização de uma conexão.

O trigger disponível neste estágio é somente:

```text
manual
```

Estados:

```text
requested
running
partial
succeeded
failed
cancelled
```

Invariantes principais:

- `(connection_id, idempotency_key)` é único;
- existe no máximo um run `requested` ou `running` por conexão;
- a unicidade de run ativo é garantida por índice parcial PostgreSQL, e não
  somente pelo processo Python;
- `running` exige `started_at`;
- estados terminais exigem `finished_at`;
- contadores são não negativos e `records_applied <= records_seen`;
- diagnósticos são categorias/códigos allowlisted e limitados;
- não existe coluna para mensagem livre, URL, header ou payload HTTP.

O método `begin_manual_sync` bloqueia a linha da conexão durante a decisão de
idempotência/single-flight. A mesma chave devolve o run já existente. Outra
chave enquanto há run ativo falha por conflito sanitizado.

Conexão `DISCONNECTED` não inicia novo run.

## `external_accounts`

A tabela mantém somente metadados minimizados necessários para relacionar o
provider à futura importação local:

```text
external_account_id   # interno/sensível, nunca resposta pública
connection_id
residence_id
type
subtype
currency
name                  # opcional/minimizado
number_mask           # opcional, nunca número completo
status
first_seen_at
last_seen_at
updated_at
```

Tipos locais:

```text
BANK
CREDIT
INVESTMENT
LOAN
OTHER
```

Estados locais:

```text
active
unavailable
disconnected
```

A chave `(connection_id, external_account_id)` é única. Um snapshot repetido
atualiza a mesma conta; um snapshot mais antigo não substitui metadados mais
recentes. Contas ausentes de um snapshot posterior não são apagadas
silenciosamente.

`ExternalAccountSnapshot` rejeita IDs vazios/fora do limite, timestamps sem
fuso, moeda incompatível e máscara numérica que se pareça com um número de
conta completo.

## `sync_cursors`

O cursor inicial é específico de:

```text
connection + external_account + transactions
```

Invariantes:

- o cursor é tratado como texto opaco e bounded;
- o valor não é normalizado ou interpretado;
- a conta precisa existir na mesma conexão e residência;
- `(connection_id, external_account_id, resource)` é único;
- o FK composto impede reutilização cross-connection/cross-residence;
- commit com timestamp anterior ao cursor confirmado falha fechado;
- repetição do mesmo cursor no mesmo instante é idempotente;
- mesmo instante com material divergente é conflito;
- cursor e `source_window` não aparecem em `repr`, log ou API neste recorte.

O recurso permitido inicialmente é somente:

```text
transactions
```

A futura persistência de uma página de transações deverá atualizar observações
e cursor dentro da mesma transação. Esta issue ainda não implementa essa
operação, portanto não existe caminho que avance cursor após uma importação
parcial.

## RLS

As três tabelas usam:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
```

A política compara a coluna direta `residence_id` com:

```text
app.current_residence_id
```

O store também define `app.current_installation_id` e resolve a conexão pelo
triplo confiável:

```text
installation_id
residence_id
connection_id local
```

Isso mantém RLS como fronteira obrigatória e o filtro explícito como defesa
adicional.

A role de runtime continua sem `BYPASSRLS`, `SUPERUSER`, `CREATEDB` ou
`CREATEROLE`.

## Fronteira do store

O `BankingIntegrationStore` público compõe
`BankingManualSyncStoreMixin` e fornece:

```text
begin_manual_sync
mark_sync_running
finish_sync
replace_external_accounts
get_sync_cursor
commit_sync_cursor
```

Essas operações:

- não usam `BankingProvider`;
- não importam Pluggy;
- não decriptam credenciais;
- não criam transporte HTTP;
- não aceitam Item ID do cliente HTTP;
- não criam endpoint FastAPI;
- não executam fila, polling ou background worker.

## Dados sensíveis

Valores necessários operacionalmente, mas proibidos em representação pública:

```text
external_account_id
idempotency_key
cursor
source_window
```

Os DTOs de persistência possuem `repr` explícito que os omite.

Também continuam proibidos neste schema:

- API key;
- Connect Token;
- Client Secret plaintext;
- senha/MFA;
- número completo de conta;
- headers de autenticação;
- request/response HTTP bruto.

## Relação com a próxima etapa

A fundação desta issue não é ainda uma sincronização funcional.

A evolução segura é:

```text
#109 persistência operacional local
  -> orquestrador manual provider-neutral
  -> persistência transacional de external_observations
  -> reconciliação PENDING / CONFIRMED / DELETED
  -> endpoint/UX de solicitação manual
```

O orquestrador futuro deverá usar o executor read-only contextual já existente,
persistir uma página integralmente e somente então confirmar o cursor
correspondente.

## Fora do escopo

- chamadas Pluggy reais ou fake de rede no runtime;
- listagem provider durante uma sync;
- persistência de transações;
- reconciliação;
- `PATCH /items` / manual refresh do provider;
- worker, fila ou polling;
- endpoint HTTP de sync;
- UI Flutter de sync;
- faturas/cartões;
- desconexão/consentimento;
- webhooks;
- alteração de flags;
- deploy, HML ou produção.
