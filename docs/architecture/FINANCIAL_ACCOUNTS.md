# Contas financeiras canônicas

Status: **primeira persistência do núcleo financeiro / issue #133**.

## Objetivo

A conta financeira é o primeiro recurso financeiro persistente do usuário. Ela representa onde o dinheiro é mantido ou acompanhado, mas **não armazena saldo autoritativo** neste recorte.

A implementação aplica desde o primeiro schema os contratos já aceitos:

```text
Money / moeda       -> ADR-0015
Audiência           -> ADR-0016
Resource ID         -> ADR-0017
```

## Tipos

Tipos iniciais provider-neutral:

```text
CHECKING
SAVINGS
CASH
DIGITAL_WALLET
INVESTMENT
BENEFIT
CUSTOM
```

`CUSTOM` exige `custom_type_name`. Os demais tipos proíbem esse campo.

Esses tipos pertencem ao domínio do MeuFinanceiro e não reproduzem taxonomia Pluggy ou de outra instituição.

## Estado

Estados de schema:

```text
ACTIVE
ARCHIVED
```

Neste primeiro recorte o runtime cria somente `ACTIVE`.

`ARCHIVED` já possui constraint estrutural para uso futuro, mas nenhuma permissão runtime de `UPDATE` ou `DELETE` é concedida. O caso de uso de arquivamento será implementado somente após a matriz de capacidades por papel e auditoria correspondente.

A policy de `INSERT` também exige `ACTIVE` + `archived_at IS NULL`, portanto SQL runtime fora do store não consegue antecipar um estado arquivado.

## Estrutura

Tabela principal:

```text
finance.accounts
```

Campos:

```text
id
installation_id
residence_id
owner_operator_id
visibility_scope
account_type
custom_type_name
name
currency
status
created_at
updated_at
archived_at
```

Não existem campos:

```text
balance
available_balance
initial_balance
provider_balance
```

Saldo de abertura e saldo calculado pertencem a etapas posteriores do livro financeiro.

## Identidade

`id` é UUID v4 RFC 4122 local e opaco, gerado pelo backend conforme ADR-0017.

Além da validação no domínio, `finance.accounts` possui constraint PostgreSQL para aceitar somente UUID v4 com variant RFC 4122.

A conta não contém ID Pluggy, FITID, external account ID, fingerprint ou qualquer identidade de provider.

Integrações futuras poderão vincular observações externas à conta local por uma relação explícita; nunca substituirão o UUID canônico.

## Audiência

Toda conta possui:

```text
residence_id
owner_operator_id
visibility_scope
```

Semântica:

```text
PERSONAL  -> somente owner
SHARED    -> owner + grants explícitos
HOUSEHOLD -> toda membership ativa da residência
```

`owner`/`administrator` household não recebe bypass para conta `PERSONAL` de outro operador.

## Grants compartilhados

Tabela:

```text
finance.account_grants
```

Cada grant contém o UUID local da conta, residência, owner e `visibility_scope` copiados da conta, além do operador compartilhado.

A tabela exige:

```text
visibility_scope = SHARED
```

A FK composta:

```text
(account_id, installation_id, residence_id, owner_operator_id, visibility_scope)
```

fecha o grant sobre a conta e seu escopo exatos. Assim nem uma conexão administrativa consegue persistir grant para conta `PERSONAL` ou `HOUSEHOLD` usando um scope artificial. Outra FK exige que o target seja membership da mesma residência.

Owner redundante é proibido por constraint.

Neste recorte o runtime recebe somente `SELECT` sobre grants. Não existe API/store para adicionar, remover ou editar compartilhamento.

## RLS

`finance.accounts` e `finance.account_grants` usam:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
```

Contexto confiável:

```text
app.current_residence_id
app.current_operator_id
```

### SELECT de contas

Exige:

1. mesma residência;
2. membership ativa do ator;
3. uma das condições de audiência:
   - ator é owner;
   - conta é `HOUSEHOLD`;
   - conta é `SHARED` e há grant explícito do ator.

### INSERT de contas

Exige:

```text
mesma residência
owner_operator_id = current_operator_id
status = ACTIVE
archived_at IS NULL
membership ativa
```

O store não aceita owner recebido pelo payload: o owner é o próprio `operator_id` confiável recebido da camada autenticada.

### Grants sem policy recursiva

A policy de `account_grants` não consulta `finance.accounts`.

Ela permite leitura somente para o próprio grantee ou owner, sempre dentro da residência e membership ativa. Assim a policy de contas pode consultar grants sem criar ciclo de policies.

## Permissões runtime

A migration concede somente:

```text
finance.accounts       -> SELECT, INSERT
finance.account_grants -> SELECT
```

Não há `UPDATE`/`DELETE` de contas e nenhuma mutação de grants para o usuário de runtime.

## Store mínimo

`FinancialAccountStore` oferece somente:

```text
create_account
list_accounts
get_account
```

`create_account`:

```text
set installation/residence/operator context
  -> confirmar membership ativa
  -> gerar UUID v4 local
  -> owner = ator atual
  -> INSERT ACTIVE
  -> retornar registro canônico
```

`list_accounts` e `get_account` dependem de RLS para a audiência efetiva.

`get_account` retorna o mesmo erro sanitizado quando o UUID não existe ou está fora da audiência:

```text
financial account was not found
```

Isso evita transformar a diferença entre inexistência e falta de acesso em canal de enumeração.

## Moeda

Conta possui `currency` ASCII uppercase de três letras, usando o mesmo validator do contrato `Money`.

Não existe amount na conta neste estágio.

## Fora do escopo

- saldo de abertura;
- saldo calculado;
- movements/ledger;
- transferências/rateios;
- categorias;
- edição/arquivamento/exclusão;
- mutação de grants;
- FastAPI;
- Flutter;
- vínculo automático com Pluggy;
- importação/conciliação;
- deploy, HML ou produção.

## Validação

Foram adicionados testes sintéticos para contrato de domínio, migration, RLS, acesso `PERSONAL`/`SHARED`/`HOUSEHOLD`, membership inativa, cross-residence, owner spoofing, UUID não-v4, grant em escopo inválido e permissões runtime.

Nesta sessão, a revisão é estática via GitHub; Ruff, Ruff format, mypy, pytest, PostgreSQL integration e Quality integral só podem ser declarados quando forem realmente executados.
