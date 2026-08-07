# Pluggy Connect Token autenticado por residência

Status: implementação da issue #93.

## Objetivo

O MeuFinanceiro emite Connect Token somente no backend, para uma residência canônica
derivada da sessão autenticada. O cliente nunca recebe `CLIENT_ID`, `CLIENT_SECRET` ou
API key e não controla o escopo usado para emitir o token.

Este recorte prepara exclusivamente o bootstrap do futuro Connect Widget. Ele não cria
Item, não registra conexão e não inicia sincronização.

## Endpoint

```text
POST /api/v1/banking/pluggy/connect-token
```

O endpoint não possui body nem query parameters.

Autorização atual:

```text
Bearer session
  -> installation_admin
  -> primary_residence_id obrigatório
```

`installation_id` e `residence_id` são obtidos do `OperatorSessionPrincipal`. Qualquer
body, inclusive `{}`, e qualquer query parameter são rejeitados para evitar que opções
ou identificadores do provider apareçam acidentalmente como entrada controlada pelo
cliente.

A resposta contém somente:

```json
{
  "accessToken": "<token efêmero>"
}
```

Todas as respostas sob `/api/v1/banking/` recebem:

```text
Cache-Control: no-store
Pragma: no-cache
```

## Payload enviado à Pluggy

O backend gera internamente:

```json
{
  "options": {
    "clientUserId": "residence:<primary_residence_id>",
    "avoidDuplicates": true
  }
}
```

Não são aceitos neste recorte:

- `itemId`;
- `webhookUrl`;
- `oauthRedirectUri`;
- connector ID;
- seleção de produtos;
- credenciais bancárias;
- MFA;
- `clientUserId` vindo do cliente.

## Transporte

`PluggyConnectTokenHttpTransport` reutiliza a autenticação efêmera, limites de resposta,
timeouts, retry bounded, política de redirects e sanitização do transporte Pluggy já
existente.

A única ampliação de escrita permitida é:

```text
POST /connect_token
```

`POST /items` continua bloqueado. A API key pode ser renovada uma única vez após
`401/403`, exatamente como nas leituras autenticadas.

O `accessToken` retornado é validado como string não vazia e limitada. Ele é devolvido
à camada superior e não é salvo no objeto de transporte.

## Serviço de execução

`PluggyConnectTokenService` recebe somente:

- `installation_id` confiável;
- `residence_id` confiável.

O serviço deriva `clientUserId`, usa
`BankingIntegrationStore.use_enabled_credentials(provider="pluggy")`, constrói um
transporte por chamada e o fecha em sucesso ou falha.

`IssuedPluggyConnectToken` possui `repr` redigido. Erros de persistência, configuração
e transporte são convertidos para categorias estáveis sem payload, URL, credencial,
API key, token ou cadeia causal externa.

## Runtime e flags

O serviço somente é composto quando as duas flags são verdadeiras:

```text
APP_BANKING_ENABLED=true
APP_BANKING_PLUGGY_ENABLED=true
```

Ambas continuam `false` por padrão.

Construir o serviço não lê/decripta credenciais e não cria transporte. Portanto, o
startup permanece sem I/O do provider. A primeira possibilidade de rede ocorre somente
quando um operador autenticado invoca explicitamente o endpoint e a configuração
Pluggy está habilitada.

## Persistência

Não existe coluna, migration ou store para:

- Connect Token;
- `accessToken` do Connect Widget;
- API key Pluggy.

O token é uma credencial transitória de apresentação ao widget e não faz parte do
modelo persistente.

## Fora do escopo

Continuam fora desta issue:

- Flutter e Connect Widget;
- callback de sucesso do Widget;
- criação ou recuperação de Item;
- persistência de `external_connection_id` a partir do Widget;
- reautenticação/update de Item;
- OAuth redirect;
- webhooks;
- sincronização e worker;
- leitura nova de contas/transações;
- chamada real à Pluggy nos testes;
- credenciais reais;
- mudança das flags padrão;
- bootstrap real;
- deploy, HML ou produção.

O próximo recorte deve tratar a conclusão do Connect Widget e o registro server-side do
Item retornado, vinculando-o à residência autenticada sem aceitar `residence_id`
arbitrário.
