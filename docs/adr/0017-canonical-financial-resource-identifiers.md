# ADR-0017 — Identificadores canônicos de recursos financeiros

- Status: Accepted
- Data: 2026-08-11
- Decisores: mantenedores

## Contexto

O núcleo financeiro já possui representação monetária canônica (ADR-0015) e audiência/autorização por recurso (ADR-0016). Antes da primeira tabela de conta financeira, ainda é necessário definir como recursos locais são identificados sem acoplar identidade a provider, residência, sequência pública ou semântica de negócio.

Outros módulos do repositório já usam UUIDs, porém esse uso não constitui por si só um contrato do domínio financeiro. Conta, movimento, categoria, cartão e demais agregados precisam compartilhar uma regra explícita e estável.

## Decisão

### Identidade local

Todo recurso financeiro canônico usa um UUID v4 RFC 4122 como identificador local opaco.

A geração padrão ocorre no backend/domínio por `uuid4()`, que utiliza a fonte de aleatoriedade do sistema operacional no Python suportado pelo projeto.

O contrato aceita somente objetos `UUID` que sejam:

```text
não nil
variant RFC 4122
version 4
```

Strings, inteiros ou outras representações não são convertidos implicitamente pelo value contract.

### Semântica zero

O UUID local não codifica:

- residência;
- operador/proprietário;
- tipo de conta ou recurso;
- timestamp/data;
- valor monetário;
- moeda;
- provider;
- identificador externo;
- status ou visibilidade.

Autorização nunca é inferida do ID. `residence_id`, `owner_operator_id` e `visibility_scope` continuam sendo campos e regras independentes conforme ADR-0016.

### IDs externos

Identificadores de provider/importador são identidades de fonte, não identidade canônica do recurso financeiro.

Exemplos:

```text
external_resource_id
FITID
provider item/account/transaction id
hash
fingerprint
```

Esses valores podem participar de observação, deduplicação, reconciliação e vínculos, mas não substituem o UUID local do livro financeiro.

### IDs de operação

Os seguintes conceitos permanecem separados do resource ID:

- idempotency key;
- correlation ID;
- reconciliation/link ID;
- transfer ID;
- import batch ID;
- audit event ID.

Compartilhar o tipo UUID em algum caso futuro não torna os conceitos intercambiáveis.

### Geração pelo cliente

Este ADR não autoriza o Flutter ou outro cliente a escolher o ID autoritativo de um novo recurso financeiro.

Um futuro modo offline pode justificar client-generated UUID, mas isso exige contrato próprio para criação, idempotência, conflito, ownership e sincronização. Até essa decisão, a geração canônica é server-side.

### Exposição

UUID é identificador opaco, não segredo. Pode aparecer em rotas e contratos quando necessário, mas conhecer um UUID nunca comprova acesso.

Endpoints e repositórios devem aplicar autenticação, residência e audiência independentemente da forma do ID.

## Alternativas consideradas

### Sequência numérica

Rejeitada como identidade canônica. Facilita enumeração, acopla geração ao banco e não traz benefício relevante para um domínio local-first distribuível.

### UUID v1

Rejeitado por carregar informação temporal/hardware e por não ser necessário ao produto.

### UUID v5

Rejeitado como identidade geral porque exige namespace/material determinístico e incentiva derivar identidade de atributos mutáveis ou externos.

### UUID v7

Adiado. Ordenação temporal pode ser útil em outros eventos, mas não é necessária para a primeira identidade de recurso e adicionaria uma decisão/toolchain sem benefício atual.

### ULID

Adiado pelo mesmo motivo: ordenação/representação textual não justificam uma dependência ou contrato adicional neste estágio.

### Usar ID do provider

Rejeitado. Viola source-of-truth local, impede recursos manuais e acopla o livro à integração.

## Consequências positivas

- identidade local simples e provider-neutral;
- geração sem round-trip para sequência global;
- nenhum dado financeiro ou de escopo vaza pela estrutura do ID;
- IDs externos podem mudar/ser conciliados sem trocar a identidade local;
- mesma convenção pode atender contas, categorias, movimentos e outros agregados;
- autorização permanece explicitamente separada da identidade.

## Consequências negativas e riscos

- UUID v4 não possui ordenação temporal natural;
- índices UUID aleatórios podem ter localidade inferior a IDs ordenáveis;
- APIs precisam tratar UUID como identificador opaco, não como prova de existência/autorização;
- eventual criação offline exigirá ADR/caso de uso adicional.

Esses custos são aceitáveis para a escala e o estágio atual do MeuFinanceiro.

## Validação

O pacote `meufinanceiro-finance` fornece:

```text
new_financial_resource_id()
validate_financial_resource_id()
```

Os testes cobrem:

- geração UUID v4 RFC 4122 não-nil;
- amostra sintética sem IDs repetidos;
- aceitação do próprio objeto UUID válido;
- rejeição de string mesmo contendo UUID válido;
- rejeição de UUID nil;
- rejeição de UUID de versão diferente;
- rejeição de variant não RFC 4122;
- ausência de dependências de provider/persistência no helper.

## Referências

- #124
- #131
- ADR-0015
- ADR-0016
- `docs/architecture/FINANCIAL_INVARIANTS.md`
- `docs/architecture/IMPLEMENTATION_SEQUENCE.md`
