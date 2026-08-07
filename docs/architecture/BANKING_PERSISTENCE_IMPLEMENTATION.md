# Implementação da persistência bancária mínima

Status: **implementação inicial da issue #68, reforçada pela issue #90**.

Este documento descreve o primeiro subconjunto executável do contrato definido no
ADR-0012 e em `BANKING_INTEGRATION_PERSISTENCE_MODEL.md`. O recorte cria somente a
configuração administrativa, as conexões externas e as capacidades observadas.

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

O downgrade integral remove os objetos na ordem inversa, revoga os grants do runtime
e remove o schema `integrations`.

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
com RLS. `register_connection` não cria nem corrige uma residência: o PostgreSQL exige
que o contexto informado já corresponda a uma linha canônica de household.

Erros públicos são estáveis e não incluem:

- plaintext;
- envelope;
- external connection ID;
- residence ID inválido;
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

- round-trip da migration e preservação de dados no downgrade da `0006`;
- falha fechada do upgrade quando existe referência de residência órfã;
- FK canônica com `ON DELETE RESTRICT`;
- envelope válido e AAD contextual;
- ausência dos envelopes nos records públicos;
- compare-and-swap e substituição de credenciais;
- reutilização idempotente de conexão;
- snapshot idempotente de capacidades;
- invisibilidade total sem contexto;
- isolamento de configuração por instalação;
- isolamento de conexões e capacidades entre residências da instalação;
- bloqueio de update, delete e insert cruzados;
- rejeição de associações cross-installation e cross-residence;
- ausência de privilégios administrativos na role de runtime.

As fixtures de conexão criam instalação, operador e residência household legítimos antes
de inserir dados bancários. UUIDs sintéticos sem linha canônica não são mais aceitos.

## Fora do escopo

Continuam fora deste recorte:

- Connect Token e Connect Widget;
- criação de Item real;
- endpoint HTTP de conexão bancária;
- leitura real de contas e dados financeiros;
- sincronização manual ou worker;
- múltiplas residências selecionáveis pela UI;
- chamada real à Pluggy;
- alteração de flags;
- bootstrap real;
- deploy, HML e produção.
