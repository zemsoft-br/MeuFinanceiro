# Implementação executável da fronteira bancária

Status: **implementação inicial da issue #66**.

Este documento complementa o contrato aceito em
`BANKING_PROVIDER_CONTRACT.md` e o ADR-0012. Ele descreve apenas o pacote neutro
executável; não representa integração produtiva com banco, Pluggy ou Open Finance.

## Localização

```text
packages/banking/
  src/meufinanceiro_banking/
    models.py
    provider.py
    fake.py
```

O pacote publicado internamente chama-se `meufinanceiro-banking` e utiliza somente
a biblioteca padrão do Python 3.13.

## Fronteira pública

`BankingProvider` é um `typing.Protocol` síncrono e verificável em runtime. O
protocolo cobre:

- criação de intenção de conexão;
- criação de intenção de reautenticação;
- leitura do estado da conexão;
- leitura de capacidades;
- listagem de contas;
- paginação de transações;
- leitura de faturas;
- leitura de investimentos;
- leitura de empréstimos;
- solicitação de atualização manual;
- desconexão explícita.

A escolha síncrona preserva o contrato arquitetural atual. Um adaptador futuro pode
encapsular I/O internamente, mas não pode retornar coroutine, cliente HTTP, sessão ou
tipo específico do provider pela fronteira pública sem novo ADR.

## DTOs

Os DTOs são `dataclass(frozen=True, slots=True)` e utilizam:

- `Decimal` para valores monetários;
- `date` para datas civis;
- `datetime` timezone-aware para instantes;
- `tuple` para coleções públicas;
- `StrEnum` para estados e capacidades.

As validações de fronteira rejeitam:

- identificador vazio ou com caractere de controle;
- moeda fora do formato ASCII de três letras;
- timestamp sem timezone;
- valor monetário não representado por `Decimal`;
- capacidade duplicada;
- estado que exige ação do usuário sem o marcador correspondente;
- intenção de reautenticação sem conexão existente;
- cursor inválido;
- diagnóstico livre, multilinha ou excessivamente longo.

## Tipos neutros

### Capacidades

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

### Estados de capacidade

```text
SUPPORTED
NOT_AVAILABLE
REQUIRES_USER_ACTION
NOT_OBSERVED
UNKNOWN
```

### Estados de conexão

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

### Estados de transação

```text
CONFIRMED
PENDING
INFERRED
DELETED
```

## Erros

`BankingProviderError` expõe somente:

```text
category
retryable
provider_reason_code opcional e limitado
safe_message sanitizada
```

O erro não aceita resposta HTTP, URL completa, headers, stack externo, payload,
credencial ou identificador sensível na mensagem.

## Provider fake

`FakeBankingProvider` existe exclusivamente para testes de domínio e orquestração.
Ele:

- não executa rede;
- não acessa PostgreSQL;
- não lê configuração ou keyring;
- recebe fixtures explícitas por conexão;
- gera IDs sequenciais determinísticos;
- pagina transações por cursor opaco do fake;
- respeita `changed_since`;
- representa rate limit conhecido;
- exige ação do usuário quando o estado da conexão determina;
- desconecta sem apagar contas ou transações semeadas.

O fake não pretende reproduzir a API de nenhum provider e não deve ser usado como
base de serialização externa.

## Proibições permanentes da fronteira

A API pública do pacote não contém:

- SDK ou tipo Pluggy;
- cliente HTTP ou sessão;
- API key;
- Connect Token;
- senha bancária;
- MFA;
- payload bruto;
- headers de autenticação;
- modelo SQLAlchemy;
- endpoint FastAPI.

## Integração com quality gates

O pacote participa de:

- instalação editável do ambiente de qualidade;
- Ruff lint;
- Ruff format;
- `mypy --strict`;
- pytest;
- inventário de licenças;
- `pip-audit`.

Os testes do pacote não exigem internet nem PostgreSQL.

## Fora do escopo

Continuam pendentes em issues separadas:

- registro/registry fail-closed de providers;
- migration do schema `integrations`;
- armazenamento de configuração cifrada;
- adaptador Pluggy;
- API key efêmera;
- Connect Widget;
- endpoints;
- sincronização manual produtiva;
- reconciliação e importação no domínio;
- webhook;
- deploy, HML ou produção.
