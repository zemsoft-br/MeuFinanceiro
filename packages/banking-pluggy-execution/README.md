# Banking Pluggy Execution

Pacote de orquestração contextual da integração Pluggy.

## Fronteiras

O pacote compõe o caminho read-only:

```text
BankingIntegrationStore
    -> conexão interna com RLS por residência
    -> credenciais efêmeras habilitadas
PluggyGatewayHttpTransport
    -> PluggyHttpReadOnlyGateway
    -> PluggyBankingProvider
    -> DTOs neutros
```

E o bootstrap de conexão:

```text
sessão autenticada
    -> installation_id + primary_residence_id
BankingIntegrationStore.use_enabled_credentials
    -> PluggyConnectTokenHttpTransport
    -> Connect Token efêmero
```

Após o sucesso do Connect Widget, o registro local segue outra fronteira explícita:

```text
itemId não confiável
    -> GET /items/{itemId}
    -> prova de clientUserId da residência autenticada
    -> register_connection
    -> replace_capabilities
```

A reautenticação de uma conexão existente inverte a entrada: o cliente fornece somente
o UUID local e o Item é resolvido server-side:

```text
connection_id local
    -> get_connection sob RLS
    -> GET /items/{external_connection_id persistido}
    -> prova de id + clientUserId
    -> POST /connect_token {itemId: Item verificado}
    -> accessToken + itemId efêmeros para update mode
```

## Operações read-only

`PluggyReadOnlyExecutionService` oferece:

- estado da conexão;
- capacidades;
- contas;
- uma página de transações.

A API pública recebe somente installation ID, residence ID, connection ID interno e,
na leitura de transações, account ID externo após validação de pertencimento à conexão.
Item ID nunca é aceito como argumento público nessas operações de leitura.

## Emissão de Connect Token

`PluggyConnectTokenService` recebe somente `installation_id` e `residence_id`
confiáveis. O serviço:

- valida os UUIDs;
- deriva `clientUserId` como `residence:<residence_id>`;
- exige configuração `pluggy` habilitada;
- decripta credenciais somente dentro do callback efêmero do store;
- cria um transporte por emissão;
- fecha o transporte em sucesso e falha;
- devolve `IssuedPluggyConnectToken` com `repr` redigido;
- converte erros do provider e persistência em códigos estáveis e sanitizados.

O serviço não recebe `itemId`, webhook, OAuth redirect, connector ID, seleção de
produtos ou dados bancários.

## Registro de Item concluído

`PluggyConnectionRegistrationService` recebe `itemId` somente como ponteiro para
verificação. `installation_id` e `residence_id` continuam vindo de uma fronteira
confiável.

Antes de persistir, o serviço:

- lê o Item diretamente do provider com credenciais efêmeras;
- exige que o ID retornado corresponda ao solicitado;
- exige `clientUserId=residence:<residence_id>`;
- fecha o transporte;
- somente depois registra/reutiliza a conexão sob RLS e FK canônica;
- substitui o snapshot de capacidades observadas.

Mismatch de ownership, Item inválido, erro de transporte e conflito cross-residence são
convertidos para erros estáveis sem Item ID, clientUserId, payload bruto ou credenciais.
A resposta pública usa apenas o UUID local da conexão e estado neutro.

## Reautenticação/update

`PluggyReauthenticationTokenService` recebe somente `installation_id`, `residence_id`
e `connection_id` confiáveis. O serviço resolve a conexão local antes de acessar
credenciais e rejeita provider incompatível ou conexão desconectada.

Com credenciais efêmeras, ele lê o Item persistido diretamente na Pluggy, exige o ID
exato e `clientUserId=residence:<residence_id>` e só então cria um Connect Token
vinculado ao Item. O DTO `IssuedPluggyReauthenticationToken` contém `access_token` e
`item_id` apenas para inicialização do Pluggy Connect update mode e possui `repr`
redigido.

O POST de Connect Token não é repetido automaticamente após falha ambígua de rede/5xx.
Não há `PATCH /items`, persistência adicional ou atualização de estado local nessa
fronteira; após o widget, o registro existente recompõe a prova de ownership e atualiza
a conexão de forma idempotente.

## Segurança

- conexão read-only resolvida pelo store sob RLS;
- provider diferente de `pluggy` é rejeitado nas operações contextualizadas;
- conexão desconectada é rejeitada antes da decriptação nas leituras e reautenticação;
- configuração deve estar `enabled` antes de qualquer I/O do provider;
- credenciais existem somente dentro do callback do store;
- factories e transportes são injetáveis nos testes;
- erros inesperados são convertidos em fronteiras sanitizadas;
- conta é validada contra as contas da conexão antes das transações;
- Connect Token e API key não são persistidos;
- `clientUserId` é usado somente como prova transitória de ownership;
- nenhum log ou payload bruto é produzido pelo pacote.

Os DTOs read-only ainda contêm identificadores externos operacionais. Essa fronteira é
interna e não deve ser exposta diretamente por endpoint HTTP. A futura persistência de
contas e transações deverá mapear esses identificadores para IDs locais antes da
exposição ao cliente.

## Runtime

O pacote é instalado na imagem da API. Os serviços Pluggy somente são construídos
quando `APP_BANKING_ENABLED` e `APP_BANKING_PLUGGY_ENABLED` são verdadeiros. As flags
são falsas por padrão.

Construir os serviços não lê credenciais, não cria transporte e não executa chamadas
externas. I/O do provider ocorre somente após uma operação autenticada explícita.

Detalhes das fronteiras estão em:

- `docs/architecture/PLUGGY_CONNECT_TOKEN.md`;
- `docs/architecture/PLUGGY_CONNECTED_ITEM_REGISTRATION.md`;
- `docs/architecture/PLUGGY_REAUTHENTICATION_TOKEN.md`.
