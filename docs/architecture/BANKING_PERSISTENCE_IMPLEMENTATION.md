# Implementação da persistência bancária mínima

Status: **implementação iniciada pela issue #68, reforçada pelas issues #90 e #109**.

Este documento descreve o subconjunto executável do contrato definido no ADR-0012 e
em `BANKING_INTEGRATION_PERSISTENCE_MODEL.md`. A fundação atual cobre configuração,
conexões, capacidades e a persistência operacional necessária para futura
sincronização manual. A especificação detalhada do último recorte está em
`BANKING_MANUAL_SYNC_PERSISTENCE.md`.

## Migrations

A revisão Alembic `0003_banking_persistence` cria o schema PostgreSQL
`integrations` com:

```text
provider_configurations
connections
connection_capabilities
```

A revisão `0006_banking_residence_fk`, posterior à criação do schema `household`,
fecha a integridade referencial entre a conexão bancária e a residência canônica. O
upgrade recusa qualquer conexão existente cujo par `(residence_id, installation_id)`
não corresponda a `household.residences(id, installation_id)`.

O gate de upgrade não cria residência, não remapeia conexão para a residência primária
e não registra identificadores externos na mensagem de falha. A FK usa
`ON DELETE RESTRICT`. O downgrade da `0006` remove somente essa constraint e preserva
as linhas de integração e household.

A revisão `0007_banking_manual_sync_persistence` adiciona:

```text
sync_runs
external_accounts
sync_cursors
```

Essas tabelas implementam somente a fundação local de execução idempotente, contas
externas minimizadas e cursor opaco confirmado. Elas não persistem ainda observações
ou transações financeiras e não executam provider I/O.

O downgrade integral remove os objetos na ordem inversa, revoga os grants do runtime
e remove o schema `integrations`.

Continuam não criadas tabelas de observações/transações, faturas, investimentos,
empréstimos ou auditoria bancária.

## Configuração por instalação

`integrations.provider_configurations` mantém uma configuração por
`(installation_id, provider)`.

As credenciais persistíveis são exclusivamente:

```text
client_id_envelope
client_secret_envelope
```

Os dois campos armazenam envelopes AES-256-GCM produzidos por `SecretCipher`. A
configuração recebe seu UUID antes da cifragem, permitindo o AAD canônico:

```text
meufinanceiro:v1:installation:{installation_id}:provider:{provider}:
configuration:{configuration_id}:field:{field_name}
```

A API pública do store não devolve os envelopes. API key, Connect Token, senha
bancária e MFA não possuem campos no schema.

Estados aceitos:

```text
disabled
configured
enabled
```

Regras:

- `configured` e `enabled` exigem os dois envelopes;
- `disabled` pode preservar os envelopes para uma pausa reversível;
- ativação é explícita;
- atualização usa `configuration_revision` como compare-and-swap;
- substituição de credenciais cifra os novos valores antes da transação final;
- revisão obsoleta é rejeitada sem retornar ciphertext ou plaintext.

## Conexões por residência

`integrations.connections` mantém:

- UUID interno;
- instalação e residência diretas;
- provider e configuração da mesma instalação;
- identificador operacional externo;
- estado neutro do `BankingProvider`;
- ação do usuário, sincronização, refresh, consentimento e desconexão;
- código limitado do provider, sem mensagem livre.

Existem duas FKs compostas relevantes:

```text
(provider_configuration_id, installation_id, provider)
  -> integrations.provider_configurations(id, installation_id, provider)

(residence_id, installation_id)
  -> household.residences(id, installation_id)
```

A primeira impede associar uma conexão à configuração de outra instalação ou de outro
provider. A segunda impede UUID de residência órfão e impede reutilizar uma residência
canônica de outra instalação. Nenhuma delas usa cascade destrutivo.

A unicidade por `(installation_id, provider, external_connection_id)` permite
reutilizar uma conexão já conhecida sem criar duplicidade. A atualização só ocorre
quando a linha pertence à residência visível; uma colisão com outra residência gera
erro sanitizado.

## Capacidades por conexão

`integrations.connection_capabilities` mantém um snapshot idempotente por
`(connection_id, capability)`.

A FK composta usa `(connection_id, residence_id)`, impedindo que uma capacidade seja
associada a uma conexão de outra residência.

As allowlists de capacidade, estado e fonte correspondem ao pacote neutro
`meufinanceiro-banking`, mas o pacote de persistência não importa o provider nem um
SDK externo.

Ausência de linha não significa `NOT_AVAILABLE`. O snapshot pode remover capacidades
não mais observadas e atualizar estados para `UNKNOWN` ou
`REQUIRES_USER_ACTION`.

## Fundação da sincronização manual

A `0007` introduz três objetos residence-scoped.

### `sync_runs`

- chave idempotente por conexão;
- trigger inicial somente `manual`;
- estados `requested`, `running`, `partial`, `succeeded`, `failed` e `cancelled`;
- índice parcial PostgreSQL garante somente um run ativo por conexão;
- estados terminais exigem `finished_at`;
- diagnósticos são allowlisted e bounded, nunca mensagem/payload livre.

### `external_accounts`

- FK composta para conexão da mesma residência;
- unicidade por `(connection_id, external_account_id)`;
- tipo/status/moeda neutros e validados;
- nome é opcional e minimizado;
- somente `number_mask` pode ser armazenado, nunca número completo;
- snapshot repetido atualiza sem duplicar e snapshot antigo não regride a observação.

### `sync_cursors`

- recurso inicial somente `transactions`;
- cursor opaco e bounded;
- FK composta para uma conta da mesma conexão/residência;
- um cursor por `(connection_id, external_account_id, resource)`;
- commit não pode retroceder `committed_at`;
- cursor e source window são omitidos de representações públicas.

Nenhum desses objetos cria provider transport, decripta credenciais ou chama Pluggy.

## Row-Level Security

Todas as políticas usam contexto transacional definido por `set_config(..., true)`.
O valor existe somente durante a transação atual.

### Configuração

```text
app.current_installation_id
```

A política de `provider_configurations` exige que o `installation_id` da linha seja
o mesmo do contexto.

### Conexões

```text
app.current_installation_id
app.current_residence_id
```

A política de `connections` exige simultaneamente a instalação e a residência da
linha. A FK canônica é uma defesa adicional de integridade; ela não substitui RLS nem
a derivação do contexto a partir do operador autenticado.

### Capacidades

```text
app.current_residence_id
```

A política de `connection_capabilities` usa a residência direta da linha. A FK
composta confirma que a conexão pertence à mesma residência.

### Sync runs, contas externas e cursores

```text
app.current_residence_id
```

Cada uma das tabelas novas possui `residence_id` direto, `ENABLE ROW LEVEL SECURITY`
e `FORCE ROW LEVEL SECURITY`. FKs compostas vinculam os registros à conexão/conta da
mesma residência.

A role de runtime permanece sem `BYPASSRLS`, `SUPERUSER`, `CREATEDB`, `CREATEROLE` ou
`REPLICATION`.

Quando o contexto está ausente, `current_setting(..., true)` produz valor nulo e a
política não permite leitura ou mutação. O comportamento é fail-closed.

## Store transacional

`BankingIntegrationStore` fornece:

```text
create_configuration
get_configuration
set_configuration_state
replace_credentials
register_connection
get_connection
replace_capabilities
begin_manual_sync
mark_sync_running
finish_sync
replace_external_accounts
get_sync_cursor
commit_sync_cursor
```

Cada operação abre uma transação curta e define o contexto antes de acessar tabelas
com RLS. `register_connection` não cria nem corrige uma residência: o PostgreSQL exige
que o contexto informado já corresponda a uma linha canônica de household.

As operações de sync resolvem a conexão usando simultaneamente installation,
residence e `connection_id` local antes das mutações. Elas não acessam credenciais nem
provider.

Erros públicos são estáveis e não incluem:

- plaintext;
- envelope;
- external connection ID;
- external account ID;
- cursor ou idempotency key;
- residence ID inválido;
- payload;
- token;
- resposta HTTP bruta;
- mensagem livre do provider.

## Testes PostgreSQL

A suíte cria uma role descartável real com:

```text
NOSUPERUSER
NOCREATEDB
NOCREATEROLE
NOREPLICATION
NOBYPASSRLS
```

Os testes existentes e adicionados cobrem:

- round-trip das migrations, incluindo downgrade/reupgrade da `0007`;
- falha fechada do upgrade `0006` quando existe referência de residência órfã;
- FKs canônicas com `ON DELETE RESTRICT` onde histórico operacional exige retenção;
- envelope válido e AAD contextual;
- ausência dos envelopes nos records públicos;
- compare-and-swap e substituição de credenciais;
- reutilização idempotente de conexão;
- snapshot idempotente de capacidades;
- idempotência e single-flight de `sync_runs`;
- bloqueio de sync para conexão desconectada;
- snapshot minimizado/idempotente de contas externas;
- cursor vinculado à conta, idempotente e monotônico;
- invisibilidade das tabelas novas sem contexto ou com outra residência;
- isolamento de configuração por instalação;
- isolamento de conexões e capacidades entre residências da instalação;
- bloqueio de update, delete e insert cruzados;
- rejeição de associações cross-installation e cross-residence;
- ausência de privilégios administrativos na role de runtime.

As fixtures de conexão criam instalação, operador e residência household legítimos antes
de inserir dados bancários. UUIDs sintéticos sem linha canônica não são mais aceitos.

## Fora do escopo

Continuam fora deste recorte:

- persistência de observações/transações financeiras;
- reconciliação `PENDING` / `CONFIRMED` / `DELETED`;
- execução provider-neutral da sincronização;
- `request_refresh` / PATCH de Item no fluxo de sync;
- endpoint HTTP e UI Flutter de sincronização;
- worker, fila ou polling de sincronização;
- faturas/cartões;
- chamada real à Pluggy;
- alteração de flags;
- bootstrap real;
- deploy, HML e produção.
