# Executor Pluggy read-only contextual por residência

Status: **implementação inicial da issue #80**.

## Objetivo

Executar uma operação Pluggy read-only a partir de uma conexão interna autorizada por
instalação e residência, sem aceitar Item ID como entrada pública e sem registrar o
provider no runtime da API.

```text
installation_id + residence_id + connection_id
    -> BankingIntegrationStore.get_connection (RLS)
    -> BankingIntegrationStore.use_enabled_credentials
    -> PluggyGatewayHttpTransport efêmero
    -> PluggyHttpReadOnlyGateway
    -> PluggyBankingProvider
    -> DTO neutro
```

## Pacote separado

A composição vive em `meufinanceiro-banking-pluggy-execution` para preservar:

- `meufinanceiro-banking` sem Pluggy, HTTP ou persistência;
- `meufinanceiro-persistence` sem dependência de provider;
- `meufinanceiro-banking-pluggy` sem acesso ao banco;
- API e Worker sem instalação ou registro da integração.

## Resolução da conexão

O serviço recebe somente IDs internos de contexto:

```text
installation_id
residence_id
connection_id
```

O store aplica `SET LOCAL` e RLS. Conexão ausente ou pertencente a outra residência é
indistinguível e resulta em `ConnectionNotFoundError` sanitizado.

O campo `external_connection_id`, que representa o Item do provider, é lido somente do
record persistido e permanece dentro da composição.

## Bloqueios anteriores às credenciais

Antes de chamar `use_enabled_credentials`, o executor rejeita:

- provider diferente de `pluggy`;
- conexão em estado `DISCONNECTED`.

Assim, esses casos não decriptam Client ID ou Client Secret e não criam transporte.

## Sessão efêmera

Cada operação chama `use_enabled_credentials`. Dentro do callback:

1. confirma que o provider das credenciais corresponde ao da conexão;
2. cria `PluggyApplicationCredentials`;
3. cria o transporte por factory injetável;
4. compõe gateway e adapter;
5. executa uma única leitura;
6. fecha o transporte no `finally`.

Falha de factory ou composição é convertida para `BankingProviderError(INTERNAL)` sem
cadeia causal. Falha de fechamento após uma operação bem-sucedida também falha fechado.
Uma falha de fechamento não substitui um erro já produzido pela operação.

## Operações permitidas

- `get_connection_state`;
- `get_capabilities`;
- `list_accounts`;
- `list_transactions`.

Não existe método genérico para executar callback arbitrário sobre o provider.

## Validação de conta

A leitura de transações recebe um Account ID externo porque contas ainda não possuem
persistência local neste estágio. Para impedir uso cross-connection, o executor:

1. lista as contas da conexão na mesma sessão;
2. compara Account ID e Item ID retornados pelo adapter;
3. somente então consulta transações;
4. retorna `NOT_FOUND` sanitizado quando a conta não pertence à conexão.

Esse pacote é interno e não deve ser exposto diretamente por endpoint HTTP. Uma futura
persistência de contas deverá introduzir IDs locais antes da exposição ao cliente.

## Resultados

Somente DTOs do pacote `meufinanceiro-banking` atravessam a fronteira:

- `ConnectionState`;
- `ConnectionCapability`;
- `ExternalAccount`;
- `ExternalPage[ExternalTransaction]`.

Tipos HTTP, payloads Pluggy, envelopes e credenciais não são retornados.

## Erros

Podem propagar, pois já são sanitizados:

- `BankingPersistenceError` e subclasses;
- `BankingProviderError`.

Códigos adicionais do executor:

```text
PROVIDER_NOT_SUPPORTED
CONNECTION_DISCONNECTED
CREDENTIAL_PROVIDER_MISMATCH
ACCOUNT_NOT_IN_CONNECTION
PROVIDER_EXECUTION_FAILED
TRANSPORT_CLOSE_FAILED
```

Nenhum deles inclui Item ID, Account ID, credencial, URL, header ou payload.

## Runtime preservado

O recorte não:

- instala o pacote na API ou Worker;
- registra provider no `BankingProviderRegistry`;
- altera `APP_BANKING_ENABLED=false`;
- cria endpoint;
- executa chamada real nos testes;
- persiste contas ou transações;
- cria migration;
- executa deploy, HML ou produção.
