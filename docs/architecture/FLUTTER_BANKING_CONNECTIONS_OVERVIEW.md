# Visão de conexões bancárias no Flutter Web/PWA

## Objetivo

O Flutter expõe uma visão provider-neutral das conexões bancárias que já
pertencem à residência principal da sessão autenticada.

Rota protegida:

```text
/app/integracoes
```

Ela pertence ao namespace `/app/*` e usa a mesma sessão bearer em memória e a
guarda descritas em `FLUTTER_OPERATOR_SESSION.md`.

A visão não consulta Pluggy nem outra instituição diretamente.

## Fonte de dados

O único request da visão é:

```text
GET /api/v1/banking/connections
```

O backend deriva instalação e residência do principal autenticado e devolve
somente metadados locais allowlisted.

A resposta pública contém:

```text
connectionId
provider
status
requiresUserAction
lastSuccessfulSyncAt
lastAttemptAt
nextRefreshAllowedAt
consentExpiresAt
disconnectedAt
updatedAt
reauthenticationAvailable
```

Não fazem parte do contrato Flutter:

- `external_connection_id` / Item ID Pluggy;
- `clientUserId`;
- reason code do provider;
- configuration/credential IDs;
- Connect Token ou API key;
- credenciais bancárias/MFA;
- payload bruto do provider.

## Parsing fail-closed

`BankingConnectionsApi` aceita somente o objeto raiz `connections` e exige o
shape completo de cada entrada.

A validação inclui:

- UUID local canônico;
- provider como slug bounded;
- status pertencente ao conjunto persistente conhecido;
- booleanos com tipo exato;
- timestamps ISO-8601 com timezone;
- rejeição de campos adicionais.

A lista também possui limite defensivo de tamanho. Resposta incompatível é
reduzida a erro local sanitizado e nunca é renderizada parcialmente.

## Estados locais

`BankingConnectionsController` é auto-dispose e single-flight.

O primeiro carregamento pode resultar em:

```text
loading
loaded
empty
authenticationRequired
forbidden
temporarilyUnavailable
invalidResponse
```

A atualização manual usa o estado `refreshing`.

Se já existe uma lista válida e uma atualização falha por transporte/5xx ou por
resposta incompatível, a versão já validada permanece visível com aviso local.
Uma falha de autenticação ou autorização não preserva a visão como se ainda
fosse autorizada.

Não existem timer, polling, background sync ou retry automático.

## Navegação

O shell passa a possuir o destino principal `Integrações`.

A seleção desse destino cobre o prefixo:

```text
/app/integracoes
```

Portanto também permanece selecionada nos fluxos existentes:

```text
/app/integracoes/pluggy/conectar
/app/integracoes/pluggy/conexoes/:connectionId/reautenticar
```

A visão usa somente o UUID local para ações:

```text
Conectar instituição
  -> /app/integracoes/pluggy/conectar

Reautenticar
  -> /app/integracoes/pluggy/conexoes/<connectionId-local>/reautenticar
```

O Item ID do provider nunca é necessário para navegação.

## Disponibilidade de reautenticação

A ação `Reautenticar` é exibida exclusivamente quando o backend retorna:

```text
reauthenticationAvailable=true
```

O Flutter não reconstrói essa decisão combinando provider ou status. A API
local conhece a composição do runtime e o estado da conexão; o cliente apenas
respeita o booleano recebido.

Conexões `DISCONNECTED` continuam listáveis como histórico local. O backend
devolve reautenticação indisponível para esse estado.

## Status

A UI conhece explicitamente os status locais:

```text
PENDING_USER_ACTION
SYNC_REQUESTED
SYNCING
AVAILABLE
PARTIAL
REAUTHENTICATION_REQUIRED
TEMPORARILY_UNAVAILABLE
RATE_LIMITED
DISCONNECTED
FAILED
```

Eles são traduzidos para rótulos neutros em português. A tela não interpreta
reason codes nem inventa instruções específicas da instituição.

## PWA e offline

O request permanece sob `/api/v1/`. O service worker ignora `/api` e `/api/`,
portanto a lista bancária não entra no cache do shell.

A feature não usa:

- localStorage/sessionStorage/IndexedDB;
- SQLite/SharedPreferences;
- cache PWA para dados bancários;
- fila offline.

Sem conectividade, a visão informa indisponibilidade temporária e aguarda ação
explícita do usuário para tentar novamente.

## Acessibilidade

A experiência preserva:

- heading semântico e foco inicial;
- ordem de foco natural;
- progresso e avisos via live region;
- status representado por texto e ícone, não apenas cor;
- ações com rótulos explícitos;
- layout em `Wrap`/`Column` para 320 px e texto ampliado.

## Segurança

A tela trabalha apenas com metadata local validada. O identificador local da
conexão é mantido no DTO para navegação, mas não precisa ser exibido ao usuário.

Nenhum material Pluggy é criado, carregado ou persistido pelo overview. O
script Pluggy continua pertencendo exclusivamente aos fluxos de Connect e só é
carregado depois da ação explícita nesses fluxos.

## Fora do escopo

- sincronização manual;
- contas/transações;
- saldo agregado;
- detalhes de contas;
- desconexão/consentimento;
- polling, worker ou webhook;
- provider I/O no overview;
- Android/iOS/macOS;
- alteração de flags;
- deploy, HML ou produção.
