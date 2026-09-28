# Token Pluggy de reautenticação/update

## Objetivo

A reautenticação de uma conexão Pluggy existente parte somente do UUID local da
conexão. O navegador nunca escolhe nem fornece o Item ID usado como autoridade.

Endpoint:

```text
POST /api/v1/banking/pluggy/connections/{connection_id}/reauthentication-token
```

O request não possui body nem query parameters.

## Fluxo de confiança

```text
sessão installation_admin + residência principal
        |
        v
connection_id local
        |
        v
BankingIntegrationStore.get_connection
(RLS instalação + residência)
        |
        +--> provider != pluggy / DISCONNECTED -> fail closed
        |
        v
credenciais Pluggy habilitadas, efêmeras
        |
        v
GET /items/{external_connection_id persistido}
        |
        v
validar id exato + clientUserId exato
residence:<primary_residence_id>
        |
        v
POST /connect_token
{"itemId":"<Item verificado>"}
        |
        v
accessToken + itemId efêmeros para o widget update mode
```

A prova de ownership acontece antes da emissão do token. O Item persistido é
somente um ponteiro para a consulta server-side; a resposta da Pluggy precisa
reconfirmar o mesmo `id` e o marcador canônico da residência.

## Contrato Pluggy usado

A documentação oficial da Pluggy para atualização de Item recomenda abrir o
Pluggy Connect em update mode. O Connect Token é criado para o Item existente e
o widget recebe o mesmo Item em `updateItem`.

Neste recorte o transporte envia somente:

```json
{
  "itemId": "<verified-provider-item-id>"
}
```

Não são enviados:

- `clientUserId`;
- `avoidDuplicates`;
- connector ou product IDs;
- `webhookUrl`;
- `oauthRedirectUri`;
- `forceAskForCredentials`.

Também não existe `PATCH /items/{id}` neste recorte. MFA, credencial inválida e
outras interações de reautenticação permanecem dentro do Pluggy Connect.

Referências oficiais verificadas durante a implementação:

- Pluggy — Updating an Item;
- Pluggy — Create a Connect Token;
- Pluggy — Authentication / Connect Token lifecycle.

## Resposta efêmera

Resposta pública:

```json
{
  "accessToken": "<ephemeral-connect-token>",
  "itemId": "<ephemeral-provider-item-id>"
}
```

Os dois valores são necessários apenas para inicializar o widget de atualização.
A resposta recebe `Cache-Control: no-store` e `Pragma: no-cache` pelo middleware
de APIs bancárias autenticadas.

`IssuedPluggyReauthenticationToken` usa representação redigida. O serviço não
persiste o Connect Token e não adiciona nova persistência para o Item ID; o Item
já existe server-side como `external_connection_id` da conexão local.

O cliente Flutter futuro deve manter ambos apenas em memória, não colocá-los em
Riverpod persistente, storage, cache, URL, logs ou mensagens visuais, e
descartá-los após abrir/concluir o widget.

## Concorrência e retries

A emissão do Connect Token é uma operação explícita do usuário.

- o POST `/connect_token` não recebe retry automático após falha ambígua de
  rede/5xx;
- a renovação única da API key após 401/403 permanece permitida, pois o primeiro
  request foi rejeitado como não autorizado;
- um novo retry funcional exige nova ação do cliente e um novo ciclo completo de
  resolução e prova de ownership.

## Pós-widget

Após o Pluggy Connect concluir ou devolver um Item utilizável, o cliente deve
reutilizar o endpoint existente:

```text
POST /api/v1/banking/pluggy/connections
```

Esse endpoint recompõe a prova server-side de ownership e atualiza/reutiliza a
conexão local e suas capacidades de forma idempotente. O callback do widget não
vira fronteira de autorização.

## Flags e startup

O serviço de reautenticação somente é composto quando:

```text
APP_BANKING_ENABLED=true
APP_BANKING_PLUGGY_ENABLED=true
```

Ambas continuam `false` por padrão. A composição não lê credenciais, não cria
transporte e não executa rede no startup.

## Fora do escopo

- UI Flutter de reautenticação;
- visão/lista de conexões;
- `forceAskForCredentials`;
- refresh manual com PATCH de Item;
- sincronização de contas ou transações;
- polling, worker ou webhook;
- desconexão;
- migration/schema;
- chamadas reais à Pluggy;
- alteração de flags reais;
- deploy, HML ou produção.
