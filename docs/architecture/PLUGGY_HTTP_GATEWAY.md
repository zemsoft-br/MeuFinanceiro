# Gateway HTTP Pluggy read-only

Status: **implementação inicial da issue #76**.

## Objetivo

Compor o transporte HTTP da issue #74 com o contrato `PluggyReadOnlyGateway`,
convertendo respostas externas para snapshots específicos e sanitizados antes que o
adapter neutro seja chamado.

```text
Pluggy API
    ↓ JSON limitado
PluggyGatewayHttpTransport
    ↓ payload por allowlist
PluggyHttpReadOnlyGateway
    ↓ snapshots imutáveis
PluggyBankingProvider
    ↓ DTOs neutros
BankingProvider
```

Nenhum payload JSON, resposta `httpx`, header, token ou erro bruto atravessa o gateway.

## Paginação de transações

A paginação atual de `GET /v2/transactions` usa:

```text
after=<cursor opaco>
```

O campo `next` retornado pelo provedor é validado como URL relativa. O gateway exige:

- caminho vazio ou `/v2/transactions`;
- ausência de scheme, host e fragmento;
- exatamente um `accountId` correspondente à conta solicitada;
- exatamente um parâmetro `after` não vazio;
- ausência de campos inesperados.

Somente o valor de `after` é devolvido no `PluggyTransactionPageSnapshot`. A query
completa nunca sai do pacote específico.

## Item

O parser usa apenas:

- `id`;
- `status`;
- `executionStatus`;
- `updatedAt`;
- `lastUpdatedAt`;
- `consentExpiresAt`, quando explicitamente fornecido;
- `connector.products`.

São descartados:

- parâmetros de login ou MFA;
- `userAction` e instruções;
- imagens, QR codes e atributos;
- mensagens do provedor;
- credenciais e dados de usuário.

Mapeamentos principais:

| Pluggy | Snapshot |
|---|---|
| `UPDATED` + `SUCCESS` | `AVAILABLE` |
| `UPDATED` + `PARTIAL_SUCCESS` | `PARTIAL` |
| `UPDATING` / execução em andamento | `SYNCING` |
| `WAITING_USER_INPUT` / `WAITING_USER_ACTION` | `USER_ACTION_REQUIRED` |
| `LOGIN_ERROR` / `INVALID_CREDENTIALS` | `REAUTHENTICATION_REQUIRED` |
| `OUTDATED` | `TEMPORARILY_UNAVAILABLE` |
| item removido | `DISCONNECTED` |
| combinação desconhecida | `FAILED` |

Capacidades são conservadoras. `connector.products` pode provar `IDENTITY` e
`TRANSACTIONS`; a presença de `ACCOUNTS` não prova isoladamente se existem contas
bancárias ou de crédito, portanto esses dois tipos permanecem `UNKNOWN` até observação.

## Contas

O parser aceita somente a coleção `results` e conserva:

- `id`;
- `itemId`;
- `type`;
- `subtype`;
- `currencyCode`;
- `name` opcional;
- máscara derivada de `number`.

Saldo, titular, documento, limites e estruturas `bankData`/`creditData` são ignorados.
O número é reduzido para `***` seguido de no máximo quatro caracteres alfanuméricos
finais.

## Transações

O parser conserva somente:

- `id` opcional;
- `accountId`;
- `status` (`POSTED` ou `PENDING`);
- `date`;
- `updatedAt` opcional;
- `amount` como `Decimal`;
- `currencyCode`;
- descrição e categoria opcionais;
- `creditCardMetadata.billId`;
- número, total e valor total da parcela quando completos.

Metadados de parcela incompletos falham fechado. IDs duplicados na mesma página e
associação a outra conta também são rejeitados.

## Janela incremental

`changed_since` é encaminhado ao transporte como `createdAtFrom`, sempre em UTC.
Esse filtro representa somente registros criados após o instante informado. Ele não
captura, sozinho, todas as atualizações ou exclusões e não substitui:

- reprocessamento idempotente;
- reconciliação periódica;
- webhooks opcionais;
- busca por IDs modificados em recortes futuros.

O snapshot registra `source_window=CREATED_AT_FROM` para tornar essa limitação explícita.

## Erros

Erros do transporte são convertidos para categorias do gateway. O gateway remove a
cadeia causal e expõe apenas:

- categoria estável;
- retryability;
- reason code allowlisted.

Payload inválido gera `INTERNAL` não retryable. Mensagens não incluem identificadores,
valores, descrições, URL, query string, headers ou corpo bruto.

## Runtime preservado

O recorte não:

- instala o pacote na imagem da API;
- registra o provider;
- altera `APP_BANKING_ENABLED=false`;
- lê credenciais da persistência;
- executa chamadas reais;
- cria migration, endpoint, worker ou sincronização;
- executa deploy, HML ou produção.
