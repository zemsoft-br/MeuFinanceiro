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

## Operações read-only

`PluggyReadOnlyExecutionService` oferece:

- estado da conexão;
- capacidades;
- contas;
- uma página de transações.

A API pública recebe somente installation ID, residence ID, connection ID interno e,
na leitura de transações, account ID externo após validação de pertencimento à conexão.
Item ID nunca é aceito como argumento público.

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

## Segurança

- conexão read-only resolvida pelo store sob RLS;
- provider diferente de `pluggy` é rejeitado nas operações contextualizadas;
- conexão desconectada é rejeitada antes da decriptação nas leituras;
- configuração deve estar `enabled` antes de qualquer I/O do provider;
- credenciais existem somente dentro do callback do store;
- factories e transportes são injetáveis nos testes;
- erros inesperados são convertidos em fronteiras sanitizadas;
- conta é validada contra as contas da conexão antes das transações;
- Connect Token e API key não são persistidos;
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
externas. O endpoint de Connect Token é a primeira fronteira HTTP capaz de iniciar I/O
do provider, e somente após autenticação, papel administrativo e residência primária.

Detalhes do endpoint e do payload server-side estão em
`docs/architecture/PLUGGY_CONNECT_TOKEN.md`.
