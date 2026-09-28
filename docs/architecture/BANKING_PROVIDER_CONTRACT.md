# Contrato `BankingProvider`

Status: **validado para implementação futura**, com as limitações registradas na
issue #61. Não existe implementação produtiva, schema ou persistência associada.

## Decisão

O MeuFinanceiro deve integrar provedores de Open Finance por uma fronteira neutra
chamada `BankingProvider`. A Pluggy é o primeiro provedor estudado, mas nenhum tipo,
SDK, código de erro ou payload específico da Pluggy pode atravessar essa fronteira
até o domínio financeiro.

A validação é suficiente para orientar a futura implementação porque o laboratório
isolado comprovou autenticação, conexão, contas, transações, cartão de crédito,
faturas, estados pendentes, metadados de parcelas, deduplicação inicial e política
de retry. A decisão não significa que todos os produtos estejam disponíveis em toda
conexão, nem autoriza integração produtiva.

## Princípios

- PostgreSQL local permanece a fonte principal de verdade.
- Integração bancária é opcional e configurada por instalação.
- O sistema deve operar integralmente sem provedor bancário.
- O provedor nunca inicia pagamentos, DDA ou transferências.
- Application, API key, Connect Token, Item, consentimento e sincronização são
  conceitos distintos.
- Respostas externas são convertidas em DTOs neutros antes de qualquer regra de
  domínio.
- Identificadores externos são opacos e tratados como dados sensíveis.
- Dados confirmados, pendentes e inferidos não são misturados.
- Ausência de registros não prova ausência de capacidade.
- Remoção de conexão não apaga automaticamente registros financeiros importados.
- Webhooks podem otimizar uma integração futura, mas não são requisito para o modo
  local e para a sincronização manual.

## Conceitos de ciclo de vida

### Application

Representa a instalação configurada no provedor. `CLIENT_ID` e `CLIENT_SECRET`
pertencem ao mecanismo seguro de configuração da instalação, nunca ao domínio.

### API key

Credencial efêmera do backend. É criada por autenticação server-side, permanece em
memória e pode ser renovada uma única vez diante de `401/403` antes de a operação
falhar de forma controlada.

### Connect Token

Credencial efêmera e de escopo reduzido destinada ao widget de conexão ou
reautenticação. Não substitui a API key.

### ExternalConnection

Representação neutra de uma conexão externa. Na Pluggy, corresponde ao Item. Uma
conexão pode existir, estar saudável e ainda assim não disponibilizar determinada
entidade financeira.

### Consentimento

Autorização concedida pelo usuário na instituição. Expiração ou exigência de nova
autorização deve reutilizar a conexão existente quando o provedor permitir. Criar
uma nova conexão para renovar consentimento é proibido por padrão.

### Execução de sincronização

Processo separado da conexão e do consentimento. Pode terminar com dados completos,
parciais, nenhuma mudança ou exigência de ação do usuário.

## Modelo de capacidades

Capacidades são declaradas por conexão, não globalmente pelo provedor.

```text
identity
bank_accounts
credit_accounts
transactions
credit_card_bills
investments
loans
manual_refresh
consent_renewal
disconnect
webhooks
```

Cada capacidade possui um estado neutro:

```text
SUPPORTED
NOT_AVAILABLE
REQUIRES_USER_ACTION
NOT_OBSERVED
UNKNOWN
```

- `SUPPORTED`: operação ou produto foi comprovado para a conexão.
- `NOT_AVAILABLE`: o provedor declarou indisponibilidade para a conexão ou operação.
- `REQUIRES_USER_ACTION`: existe, mas depende de consentimento, MFA ou reautenticação.
- `NOT_OBSERVED`: a consulta foi válida, porém não retornou registros na amostra.
- `UNKNOWN`: ainda não houve evidência suficiente.

O snapshot de capacidades deve registrar, no mínimo:

```text
capability
state
observed_at
source
provider_reason_code opcional
```

`provider_reason_code` é diagnóstico sensível: pode ser persistido de forma limitada,
mas nunca exibido como regra de domínio nem incluído em logs públicos.

## Matriz validada pela spike

| Capacidade | Evidência | Decisão contratual |
|---|---|---|
| autenticação | comprovada contra a API real | suportada pelo adaptador |
| intenção de conexão | comprovada pelo Connect Widget | suportada e efêmera |
| contas bancárias | observadas em uma conexão | capacidade por conexão |
| conta de cartão | observada como conta de crédito | capacidade por conexão |
| transações | observadas com `POSTED` e `PENDING` | suportada com paginação |
| faturas | observadas para conta de cartão | capacidade por conta |
| parcelas | metadados observados sem ID agregador garantido | tratamento conservador |
| investimentos | consulta válida sem registros | `NOT_OBSERVED` na amostra |
| empréstimos | consulta válida sem registros | `NOT_OBSERVED` na amostra |
| atualização manual | contrato oficial disponível, não executado na spike | futura, limitada e single-flight |
| renovação de consentimento | contrato oficial disponível, não executado | futura via reautenticação da conexão |
| desconexão | contrato oficial destrutivo, não executado | futura e sempre explícita |
| webhooks | contrato oficial disponível, não exercitado | otimização opcional |

## Tipos de fronteira propostos

O exemplo permanece documental. A interface executável deve nascer junto do primeiro
caso de uso produtivo e após ADR de persistência.

```python
class BankingProvider:
    provider_name: str

    def create_connection_intent(
        self, residence_id: str, actor_id: str
    ) -> ConnectionIntent: ...

    def create_reauthentication_intent(
        self, external_connection_id: str, actor_id: str
    ) -> ConnectionIntent: ...

    def get_connection(self, external_connection_id: str) -> ConnectionState: ...

    def get_capabilities(
        self, external_connection_id: str
    ) -> list[ConnectionCapability]: ...

    def list_accounts(self, external_connection_id: str) -> list[ExternalAccount]: ...

    def list_transactions(
        self,
        external_account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> ExternalPage[ExternalTransaction]: ...

    def list_credit_card_bills(
        self, external_account_id: str
    ) -> list[ExternalCreditCardBill]: ...

    def list_investments(
        self, external_connection_id: str
    ) -> list[ExternalInvestment]: ...

    def list_loans(self, external_connection_id: str) -> list[ExternalLoan]: ...

    def request_refresh(
        self, external_connection_id: str, actor_id: str
    ) -> RefreshRequest: ...

    def disconnect(self, external_connection_id: str, actor_id: str) -> None: ...
```

O contrato não retorna payload bruto, cliente HTTP, sessão, API key, Connect Token
ou objeto do SDK.

## DTOs neutros mínimos

### ConnectionState

```text
external_connection_id
status
capabilities
last_successful_sync_at
last_attempt_at
next_refresh_allowed_at
consent_expires_at opcional
requires_user_action
provider_reason_code opcional
```

### ExternalAccount

```text
external_account_id
external_connection_id
type
subtype
currency
name opcional
number_mask opcional
```

### ExternalTransaction

```text
external_transaction_id opcional
external_account_id
status
effective_date
provider_updated_at opcional
amount
currency
description opcional
category opcional
bill_reference opcional
installment_metadata opcional
```

### ExternalPage

```text
records
next_cursor opcional
source_window
retrieved_at
```

Cursores são opacos, não são aceitos de entrada do usuário e nunca entram em logs.

## Estados internos

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

O adaptador preserva o código externo para diagnóstico controlado, mas o domínio
decide apenas pelo estado neutro.

Transições essenciais:

```text
PENDING_USER_ACTION -> SYNCING -> AVAILABLE
AVAILABLE -> SYNC_REQUESTED -> SYNCING
SYNCING -> PARTIAL
SYNCING -> REAUTHENTICATION_REQUIRED
SYNCING -> RATE_LIMITED
SYNCING -> TEMPORARILY_UNAVAILABLE
qualquer estado ativo -> DISCONNECTED, somente por ação explícita
```

## Sincronização manual sem webhook obrigatório

A primeira implementação produtiva deve suportar sincronização manual sem depender
de endpoint público.

1. O usuário solicita atualização explicitamente.
2. O backend aplica autorização por residência e registra uma chave idempotente.
3. Somente uma atualização pode permanecer ativa por conexão.
4. O adaptador consulta `next_refresh_allowed_at` e a política da instalação.
5. Se permitido, solicita a atualização ao provedor.
6. Enquanto a execução está ativa, o backend faz polling limitado do estado da
   conexão com deadline e backoff.
7. Ao concluir, busca produtos disponíveis e aplica importação idempotente.
8. Falha ou timeout não avançam cursores globais.
9. A interface informa última atualização, estado parcial e próxima tentativa
   permitida.

Não existe polling contínuo. O backend encerra a observação após o deadline e exige
nova ação ou agendamento futuro explícito.

A frequência exata não é hardcoded no domínio. Ela depende do plano, conector,
produto e limites informados pelo provedor. Ausência de informação segura bloqueia
a atualização manual em vez de adivinhar uma janela.

## Uso opcional de webhooks

Webhooks podem reduzir polling e informar conclusão de execução ou mudança de dados,
mas são uma otimização posterior.

Uma futura implementação deve:

- validar autenticidade e allowlist de eventos;
- responder `2xx` rapidamente antes do processamento;
- persistir evento idempotente antes de enfileirar trabalho;
- tolerar duplicidade, atraso e perda de evento;
- nunca depender somente do webhook para consistência;
- permitir reconciliação manual e periódica.

O modo local permanece funcional sem URL pública.

## Transações e reconciliação

Estados neutros:

```text
CONFIRMED
PENDING
INFERRED
DELETED
```

- `CONFIRMED`: confirmado pela instituição.
- `PENDING`: sujeito a alteração ou desaparecimento.
- `INFERRED`: criado por regra local, nunca atribuído ao provedor.
- `DELETED`: antes fornecido e depois removido pelo provedor.

A chave de deduplicação não pode depender apenas de descrição, data e valor. A
estratégia inicial combina:

```text
provider
external_connection_id
external_account_id
external_transaction_id, quando presente
status
effective_date
amount
currency
fingerprint de campos estáveis
```

Regras:

- repetir a mesma página não cria novos lançamentos;
- mudança de `PENDING` para `CONFIRMED` atualiza a importação existente;
- mudança material pode alterar o ID externo e exige reconciliação por fingerprint;
- exclusão externa marca a representação importada para revisão, sem apagar o
  lançamento do usuário silenciosamente;
- parcelas não são agrupadas apenas por descrição, valor ou proximidade temporal;
- ausência de identificador agregador mantém as parcelas independentes até haver
  evidência suficiente.

## Idempotência e cursores

- cada execução recebe chave idempotente local;
- cada página importada possui identidade local de processamento;
- cursores externos são opacos e vinculados à conta correspondente;
- falha parcial não avança cursor global;
- `provider_updated_at`, quando disponível, auxilia atualização incremental, mas não
  substitui reconciliação;
- reprocessamento completo deve ser seguro.

## Retry e limites

- `401/403`: renovar API key uma vez; segundo erro encerra a operação;
- conflito ou conexão em atualização: não iniciar execução concorrente;
- `429`: respeitar `RateLimit-Reset` ou `Retry-After` quando seguros;
- `5xx`, timeout e rede: no máximo três tentativas com backoff exponencial limitado
  e jitter;
- `400/404` funcionais: sem retry automático;
- erro de credencial, MFA ou consentimento: exigir ação do usuário;
- limite de produto: registrar estado parcial e próxima tentativa conhecida;
- atualização manual não promete dados em tempo real.

## Renovação de consentimento

Consentimento expirado ou login inválido deve produzir
`REAUTHENTICATION_REQUIRED`. O sistema cria uma intenção de reautenticação vinculada
à conexão existente. Uma nova conexão só pode ser criada quando o provedor declarar
que a anterior não pode ser reutilizada e após confirmação explícita do usuário.

## Desconexão

Desconectar é uma operação destrutiva distinta de pausar sincronização.

- exige autorização forte do ator;
- exige confirmação explícita na interface;
- revoga a referência no provedor quando aplicável;
- invalida futuras sincronizações;
- não apaga automaticamente lançamentos já importados;
- registra auditoria local sem armazenar credenciais ou payload bruto;
- não possui retry automático cego.

A spike não executou desconexão real para preservar os Items e consentimentos do
mantenedor.

## Persistência e classificação de dados

### Nunca persistir

- senha bancária;
- código MFA;
- API key;
- Connect Token;
- resposta HTTP bruta;
- headers de autenticação;
- material de chave privada ou certificado;
- credenciais não utilizadas pelo domínio.

### Configuração segura da instalação

- `CLIENT_ID`;
- `CLIENT_SECRET`;
- configuração opcional de webhook;
- parâmetros de plano e frequência fornecidos pelo operador.

Esses dados pertencem ao keyring ou secret store, não às tabelas financeiras.

### Persistência operacional protegida

- identificadores externos opacos;
- estado da conexão;
- capacidades observadas;
- cursores;
- timestamps de sincronização;
- códigos externos limitados para diagnóstico;
- consentimento e expiração quando fornecidos.

Não podem aparecer em logs públicos, analytics ou mensagens de erro do usuário.

### Persistência de domínio

Dados financeiros importados somente após definição de schema, RLS, retenção,
auditoria e regras de reconciliação em issues próprias.

## Threat model mínimo

| Ameaça | Controle obrigatório |
|---|---|
| vazamento de credencial da Application | keyring, rotação e ausência em logs |
| exposição de API key ou Connect Token | somente memória e vida curta |
| criação duplicada de conexão | `avoidDuplicates`, vínculo local e confirmação |
| abuso de atualização manual | autorização, single-flight e próxima janela |
| cursor injetado ou trocado entre contas | cursor opaco e vinculado à conta |
| importação duplicada | idempotência por execução e página |
| dado pendente tratado como definitivo | estados separados e reconciliação |
| exclusão externa apagando dado local | tombstone/revisão, nunca delete silencioso |
| desconexão não autorizada | confirmação forte e auditoria |
| indisponibilidade de webhook | reconciliação manual independente |
| excesso de coleta | allowlist de campos e minimização |

## Mapeamento da Pluggy

```text
Pluggy Item           -> ExternalConnection
Pluggy Account        -> ExternalAccount
Pluggy Transaction    -> ExternalTransaction
Pluggy Bill           -> ExternalCreditCardBill
Pluggy Investment     -> ExternalInvestment
Pluggy Loan           -> ExternalLoan
Connect Token         -> ConnectionIntent temporário
Item execution        -> RefreshRequest / SyncState
```

Nenhum objeto Pluggy é retornado pelo contrato neutro.

## Evidências e limitações

Evidências consolidadas:

- PR #54: laboratório isolado e contrato inicial;
- PR #56: contrato real de autenticação com `apiKey`;
- PR #58: contas, transações, cartão, faturas, parcelas e deduplicação;
- PR #60: renovação de API key, retry e rate limit.

Limitações conhecidas:

- a spike utilizou amostra própria do mantenedor;
- investimentos e empréstimos retornaram zero registros;
- paginação por cursor não ocorreu na amostra real, embora esteja coberta por testes;
- atualização manual de Item não foi executada;
- renovação e revogação reais de consentimento não foram executadas;
- desconexão real não foi executada;
- webhooks não foram cadastrados;
- frequência e disponibilidade variam por plano, instituição e produto;
- campos e códigos externos podem evoluir.

## Fontes oficiais verificadas em 27/07/2026

- https://docs.pluggy.ai/reference/auth
- https://docs.pluggy.ai/docs/item
- https://docs.pluggy.ai/docs/item-lifecycle
- https://docs.pluggy.ai/docs/updating-an-item
- https://docs.pluggy.ai/reference/items-update
- https://docs.pluggy.ai/docs/consents
- https://docs.pluggy.ai/docs/consent-management-delete-an-item
- https://docs.pluggy.ai/docs/webhooks
- https://docs.pluggy.ai/docs/rate-limits
- https://docs.pluggy.ai/docs/rate-limits-of
- https://docs.pluggy.ai/docs/transactions
- https://docs.pluggy.ai/reference/transactions-list-by-cursor

## Próxima fronteira

A validação deste documento encerra a spike técnica, não inicia a integração. O
primeiro recorte produtivo deve criar um ADR de persistência e segurança, seguido de
uma interface executável mínima e um adaptador Pluggy atrás de feature flag, sem
sincronização automática e sem alterar módulos financeiros existentes.
