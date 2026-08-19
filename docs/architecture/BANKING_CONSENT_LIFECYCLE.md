# Lifecycle local de consentimento bancário

Status: **contrato provider-neutral da issue #184**.

## Objetivo

O MeuFinanceiro precisa distinguir a validade temporal do consentimento da saúde da
conexão e da operação concreta usada pelo provider para renová-lo.

Este recorte deriva somente de fatos locais já persistidos:

```text
StoredConnectionStatus
consent_expires_at
warning_window
clock injetado
```

Nenhuma chamada ao `BankingProvider`, Pluggy, Connect, transporte HTTP ou mutação
externa participa da classificação.

## Camada escolhida

A classificação pertence a `meufinanceiro-banking-sync`.

Responsabilidades permanecem separadas:

```text
banking
  -> contrato e DTOs provider-neutral

persistence
  -> fatos locais persistidos

banking-sync
  -> projeções e orquestração local sobre fatos neutros

banking-pluggy / banking-pluggy-execution
  -> tradução e operações específicas da Pluggy
```

`REAUTHENTICATION` e `CONSENT_RENEWAL` continuam conceitos distintos. A emissão de
Connect Token em update mode não é chamada por este módulo e não é reinterpretada
como uma mutação genérica de consentimento.

## Estados temporais

A projeção possui somente:

```text
UNKNOWN
NON_EXPIRING
VALID
EXPIRING
EXPIRED
```

`REVOKED` não existe neste classificador. Expiração por tempo não prova revogação.
Uma futura representação de revogação exigirá evidência explícita e contrato
provider-derived próprio.

## Evidência para `NON_EXPIRING`

`consent_expires_at = null` não significa automaticamente consentimento permanente.

Sem timestamp de expiração, `NON_EXPIRING` exige uma conexão local cujo estado já
demonstre que a conexão chegou a um estágio operacional estabelecido:

```text
SYNC_REQUESTED
SYNCING
AVAILABLE
PARTIAL
REAUTHENTICATION_REQUIRED
TEMPORARILY_UNAVAILABLE
RATE_LIMITED
DISCONNECTED
```

Estados ambíguos, como `PENDING_USER_ACTION` e `FAILED`, produzem `UNKNOWN` quando
não existe `consent_expires_at`.

Se existe `consent_expires_at`, o próprio timestamp é evidência suficiente para a
classificação temporal, independentemente do estado operacional atual.

## Warning window

A janela de aviso é um objeto de policy explícito:

```text
ConsentLifecyclePolicy.warning_window
```

Não há número de dias default no domínio.

Semântica:

```text
expires_at <= now
  -> EXPIRED

now < expires_at <= now + warning_window
  -> EXPIRING

expires_at > now + warning_window
  -> VALID
```

A implementação calcula a diferença temporal em UTC, evitando overflow por soma de
datas extremas.

Uma janela igual a zero é válida e desabilita, na prática, o período antecipado de
`EXPIRING`. Janela negativa é inválida.

## UTC e relógio determinístico

O relógio é injetado como `ConsentClock`.

Tanto o resultado do relógio quanto `consent_expires_at` precisam ser
timezone-aware. Valores naive falham fechado. Antes da comparação, os timestamps são
normalizados para UTC.

O classificador não chama `datetime.now()` nem `datetime.utcnow()`.

## `DISCONNECTED`

`DISCONNECTED` é um estado operacional terminal e ortogonal ao estado temporal do
consentimento.

Por isso o resultado expõe:

```text
connection_terminal=true
```

A classificação temporal ainda pode ser preservada para histórico, mas:

```text
connection_terminal=true
-> renewal_required=false
```

O sistema não deve pedir renovação de consentimento para uma conexão que já foi
desconectada explicitamente.

## Sinal de renovação

`renewal_required=true` somente quando:

```text
state in {EXPIRING, EXPIRED}
AND connection_terminal=false
```

Esse sinal significa necessidade local percebida. Ele não afirma que o provider
suporta uma operação específica de renewal e não executa nenhuma ação.

A capability `CONSENT_RENEWAL` permanece um fato separado de disponibilidade do
provider/conexão.

## Segurança e minimização

`ConsentLifecycleResult` não contém:

- Item ID / external connection ID;
- UUID da conexão local;
- provider name;
- reason code;
- payload;
- token;
- credencial;
- URL.

Seu `repr` contém apenas estado temporal, `renewal_required` e
`connection_terminal`.

## Persistência

Nenhuma coluna nova é necessária.

O schema atual já contém `consent_expires_at` e o estado local da conexão. Portanto:

```text
MIGRATION=NO
```

## Fora do escopo

- renovar consentimento no provider;
- PATCH de Item;
- Connect real;
- alteração de `BankingProvider`;
- reautenticação Pluggy;
- FastAPI;
- Flutter;
- webhooks;
- sync automática;
- cartões/faturas;
- desconexão;
- deploy/HML/PROD.
