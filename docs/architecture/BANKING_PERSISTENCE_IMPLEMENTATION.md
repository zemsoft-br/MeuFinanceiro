# Implementação da persistência bancária mínima

Status: **implementação inicial da issue #68**.

Este documento descreve o primeiro subconjunto executável do contrato definido no
ADR-0012 e em `BANKING_INTEGRATION_PERSISTENCE_MODEL.md`. O recorte cria somente a
configuração administrativa, as conexões externas e as capacidades observadas.

## Migration

A revisão Alembic `0003_banking_persistence` cria o schema PostgreSQL
`integrations` com:

```text
provider_configurations
connections
connection_capabilities
```

O downgrade remove os objetos na ordem inversa, revoga os grants do runtime e remove
o schema `integrations`.

Não são criadas neste recorte tabelas de contas externas, transações, faturas,
investimentos, empréstimos, sync runs, cursores, observações ou auditoria.

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

A FK composta inclui:

```text
provider_configuration_id
installation_id
provider
```

Isso impede associar uma conexão à configuração de outra instalação ou de outro
provider.

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
linha.

### Capacidades

```text
app.current_residence_id
```

A política de `connection_capabilities` usa a residência direta da linha. A FK
composta confirma que a conexão pertence à mesma residência.

As três tabelas usam `ENABLE ROW LEVEL SECURITY` e `FORCE ROW LEVEL SECURITY`. A role
de runtime permanece sem `BYPASSRLS`, `SUPERUSER`, `CREATEDB`, `CREATEROLE` ou
`REPLICATION`.

Quando o contexto está ausente, `current_setting(..., true)` produz valor nulo e a
política não permite leitura ou mutação. O comportamento é fail-closed.

## Store transacional

`BankingIntegrationStore` fornece somente:

```text
create_configuration
get_configuration
set_configuration_state
replace_credentials
register_connection
get_connection
replace_capabilities
```

Cada operação abre uma transação curta e define o contexto antes de acessar tabelas
com RLS.

Erros públicos são estáveis e não incluem:

- plaintext;
- envelope;
- external connection ID;
- payload;
- token;
- resposta HTTP;
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

Os testes comprovam:

- round-trip da migration pelo gate existente;
- envelope válido e AAD contextual;
- ausência dos envelopes nos records públicos;
- compare-and-swap e substituição de credenciais;
- reutilização idempotente de conexão;
- snapshot idempotente de capacidades;
- invisibilidade total sem contexto;
- isolamento entre duas instalações e duas residências;
- bloqueio de update, delete e insert cruzados;
- rejeição de FKs compostas fora do escopo;
- ausência de privilégios administrativos na role de runtime.

## Fora do escopo

Continuam pendentes:

- configuração por endpoint administrativo;
- registry fail-closed de providers;
- adaptador Pluggy;
- autenticação externa e API key efêmera;
- Connect Token e Connect Widget;
- contas e dados financeiros externos;
- sync runs, cursores e reconciliação;
- auditoria persistente e rewrap em lote;
- API, Worker e Flutter;
- deploy, HML e produção.
