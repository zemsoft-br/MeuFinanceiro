# API local de conexões bancárias

## Objetivo

A API expõe uma visão estritamente local das conexões bancárias pertencentes à
residência principal da sessão autenticada.

```text
GET /api/v1/banking/connections
```

A listagem não consulta provider externo, não decripta credenciais e permanece
disponível mesmo quando as integrações bancárias estão desabilitadas.

## Fronteira de dados

A persistência usa `BankingConnectionQueryStore`, separado do store mutável e da
criptografia. A consulta seleciona explicitamente somente:

- UUID local da conexão;
- provider local;
- estado neutro;
- `requires_user_action`;
- timestamps operacionais locais;
- timestamps de consentimento/desconexão;
- criação/atualização local.

Não são selecionados pelo query record:

- `external_connection_id` / Item ID;
- `provider_reason_code`;
- `provider_configuration_id`;
- envelopes ou credenciais.

A consulta define `app.current_installation_id` e `app.current_residence_id` com
`SET LOCAL`, depende da RLS fail-closed e também aplica filtros explícitos de
instalação/residência.

## Contrato HTTP

O endpoint exige a sessão local `installation_admin` e residência principal. O
cliente não fornece instalação, residência ou provider como filtro.

O request não possui body nem query parameters.

Resposta:

```json
{
  "connections": [
    {
      "connectionId": "<uuid-local>",
      "provider": "pluggy",
      "status": "REAUTHENTICATION_REQUIRED",
      "requiresUserAction": true,
      "lastSuccessfulSyncAt": null,
      "lastAttemptAt": "2026-08-08T00:00:00Z",
      "nextRefreshAllowedAt": null,
      "consentExpiresAt": null,
      "disconnectedAt": null,
      "updatedAt": "2026-08-08T00:00:00Z",
      "reauthenticationAvailable": true
    }
  ]
}
```

A resposta vazia é sempre:

```json
{"connections": []}
```

O middleware autenticado aplica `Cache-Control: no-store` e `Pragma: no-cache`.

## Disponibilidade de reautenticação

`reauthenticationAvailable` é derivado somente de estado local do runtime:

- o serviço Pluggy de reautenticação precisa estar composto atrás das duas
  feature flags;
- a conexão precisa ser do provider `pluggy`;
- a conexão não pode estar `DISCONNECTED`.

Esse cálculo não cria transporte, não lê credenciais e não consulta a Pluggy.
Quando as flags externas são desligadas, o histórico local continua listável,
mas a ação externa aparece indisponível.

## Por que não há paginação neste recorte

A entidade listada é conexão bancária, não conta nem transação. O volume esperado
por residência é pequeno e limitado por ações explícitas de conexão. O endpoint
não deve ser reutilizado como mecanismo de leitura de dados financeiros.

Caso o produto passe a permitir um volume de conexões que torne esse pressuposto
inválido, paginação bounded será introduzida antes de ampliar o contrato.

## Segurança e privacidade

A API nunca retorna:

- Item ID ou outro identificador externo da conexão;
- `clientUserId`;
- reason code do provider;
- configuração ou credential ID;
- API key ou Connect Token;
- credenciais bancárias/MFA;
- payload bruto do provider.

Conexões `DISCONNECTED` continuam listáveis para preservar histórico local. A
leitura também funciona se a configuração do provider for desabilitada depois
da conexão.

## Próxima evolução

A visão Flutter de integrações deverá consumir somente este endpoint para
descobrir `connectionId` locais e oferecer ações como reautenticação.

A sincronização manual de contas/transações será um recorte separado, com
persistência, idempotência e reconciliação próprias. Esta listagem não inicia
sync nem provider I/O.

## Fora do escopo

- Flutter/visão geral;
- contas/transações;
- sincronização manual;
- PATCH/refresh de Item;
- worker, polling ou webhook;
- desconexão;
- migration/schema;
- chamadas reais à Pluggy;
- alteração de flags;
- deploy, HML ou produção.
