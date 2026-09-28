# Lifecycle local de consentimento bancário

Status: contrato provider-neutral da issue #184 sobre o develop após #182 e #183.

## Fronteira

O classificador em `meufinanceiro-banking-sync` recebe somente
`StoredConnectionStatus`, `consent_expires_at`, `ConsentLifecyclePolicy` e um
`ConsentClock` injetado. Ele deriva um `ConsentLifecycleResult` sem leitura ou
escrita de dados, serviço de aplicação, chamada de provider ou I/O externo.

O lookup de conexão por UUID, autorização de residência, RLS/store e exposição
por API pertencem à #186. A capability `CONSENT_RENEWAL` representa capacidade
operacional observada; ela não prova a validade temporal do consentimento e não
é requisito para esta classificação.

## Estado operacional e tempo

O estado operacional da conexão e o lifecycle temporal do consentimento são
eixos independentes. Os únicos estados temporais são `UNKNOWN`, `NON_EXPIRING`,
`VALID`, `EXPIRING` e `EXPIRED`. Não há estado `REVOKED`: timestamp, status ou erro
do provider não demonstram revogação. Ela exigiria evidência explícita futura.

`consent_expires_at=None` não significa automaticamente `NON_EXPIRING`.
Os seguintes status locais indicam um estágio estabelecido e, sem timestamp,
produzem `NON_EXPIRING`:

```text
SYNC_REQUESTED
SYNCING
AVAILABLE
PARTIAL
TEMPORARILY_UNAVAILABLE
RATE_LIMITED
```

`SYNC_REQUESTED` segue `AVAILABLE`; os status de sincronização e degradação
representam uma conexão em operação. `PENDING_USER_ACTION`,
`REAUTHENTICATION_REQUIRED` e `FAILED` não fornecem essa evidência e produzem
`UNKNOWN` quando o timestamp está ausente. Reautenticação pode decorrer de
credenciais ou de outra ação do usuário e não equivale a renovação de
consentimento: `REAUTHENTICATION_REQUIRED != CONSENT_RENEWAL`.

O conjunto histórico incluía `DISCONNECTED` entre os casos `NON_EXPIRING`.
Após #182/#183 ele é um estado operacional terminal que pode resultar de uma
desconexão explícita antes de o consentimento ser estabelecido. Por isso,
`DISCONNECTED + None` produz `UNKNOWN`. Se houver timestamp, sua classificação
temporal é preservada; em todos os casos `connection_terminal=true` e
`renewal_required=false`. `DISCONNECTED` não significa `EXPIRED`.

## Policy temporal

`ConsentLifecyclePolicy.warning_window` é um `timedelta` obrigatório e não
negativo. Não existe número de dias global ou migration para configurá-lo.

```text
expires_at > now + warning_window          -> VALID
now < expires_at <= now + warning_window   -> EXPIRING
expires_at <= now                           -> EXPIRED
```

O boundary em `now + warning_window` é `EXPIRING`; em `now` é `EXPIRED`.
Com `warning_window=0`, qualquer expiração futura é `VALID` e não existe
intervalo positivo `EXPIRING`. Janela negativa é rejeitada.

O clock é lido uma vez por classificação. Ele e `consent_expires_at`, quando
presente, devem ser `datetime` timezone-aware. Offsets são normalizados em UTC
antes da comparação; datetimes naive são rejeitados, inclusive em conexão
desconectada ou sem timestamp.

Para conexão não terminal, `renewal_required=true` somente em `EXPIRING` ou
`EXPIRED`. Esse sinal não ordena uma ação, não afirma suporte do provider e não
cria fluxo de reautenticação ou renovação.

## Privacidade e persistência

O resultado contém apenas `state`, `renewal_required` e `connection_terminal`.
Seu `repr` contém os mesmos sinais, sem UUID, Item ID, provider, código de
motivo, URL, payload ou credencial.

`StoredConnectionStatus`, `consent_expires_at` e `CONSENT_RENEWAL` já existem no
modelo atual: `MIGRATION=NO`. O classificador não persiste seu resultado.

## Fora do escopo

- #186, lookup local, facade de persistência, API e Flutter;
- Pluggy real, Connect, PATCH de Item e mutação de provider;
- sync automática, cartões, faturas, webhooks e deploy;
- alterações no disconnect, advisory locking ou writers da #182/#183.
