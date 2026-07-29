# Adaptador Pluggy read-only sem transporte

Status: **implementação inicial da issue #72**.

## Objetivo

Materializar o primeiro adapter específico da Pluggy sem introduzir autenticação,
credenciais, Connect Widget, cliente HTTP ou chamadas externas.

A composição é dividida em três fronteiras:

```text
BankingProvider
    ↑ DTOs neutros
PluggyBankingProvider
    ↑ snapshots específicos sanitizados
PluggyReadOnlyGateway
```

O domínio e os casos de uso enxergam somente `BankingProvider`. Os snapshots do
gateway permanecem confinados ao pacote `meufinanceiro-banking-pluggy`.

## Pacote separado

O adapter não foi adicionado ao pacote neutro `meufinanceiro-banking`.

Essa separação preserva:

- ausência de nomes e tipos específicos da Pluggy no contrato neutro;
- instalação opcional do adapter;
- operação completa sem provider externo;
- possibilidade de outros adapters implementarem o mesmo contrato;
- auditoria independente das dependências e superfícies de segurança.

## Gateway sanitizado

`PluggyReadOnlyGateway` não é um cliente HTTP. Ele define apenas:

```text
get_item
list_accounts
list_transactions
```

O gateway retorna dataclasses imutáveis e validadas. Nenhum método recebe ou retorna
credencial, token, sessão, cliente HTTP ou resposta bruta.

A futura camada de transporte deverá converter a resposta externa para esses snapshots
antes de chamar o adapter. Payload inválido deve falhar na borda do transporte ou na
validação do snapshot.

## Operações suportadas

### Conexão

`get_connection` converte a fase específica para `ConnectionStatus`, preservando:

- última atualização bem-sucedida;
- última tentativa;
- próxima janela permitida;
- expiração de consentimento;
- exigência de ação do usuário;
- código de motivo sanitizado.

O `item_id` retornado pelo gateway deve corresponder ao identificador solicitado.
Divergência é tratada como snapshot inválido.

### Capacidades

O gateway declara somente capacidades observadas no recorte:

```text
IDENTITY
BANK_ACCOUNTS
CREDIT_ACCOUNTS
TRANSACTIONS
```

Cada entrada preserva disponibilidade, fonte de evidência, instante observado e código
de motivo opcional. O adapter converte esses valores para os enums neutros.

### Contas

São normalizadas contas:

```text
BANK
CREDIT
OTHER
```

Toda conta deve pertencer ao Item solicitado. O adapter não aceita associação
cross-item.

### Transações

Estados suportados:

```text
POSTED  -> CONFIRMED
PENDING -> PENDING
```

O adapter preserva:

- identificador externo opcional;
- data efetiva;
- valor decimal e moeda;
- atualização do provider;
- descrição e categoria opcionais;
- referência de fatura opcional;
- metadados conservadores de parcela.

Toda transação deve pertencer à conta solicitada.

## Cursor e filtro incremental

O cursor é tratado como identificador opaco:

- não é interpretado;
- não é transformado;
- não é incluído em mensagens de erro;
- é encaminhado ao gateway e devolvido no `ExternalPage`.

`changed_since` também é apenas encaminhado. O adapter exige `datetime` com timezone,
mas não implementa política de reconciliação ou avanço de cursor.

## Operações não suportadas

Nesta etapa retornam `ProviderErrorCategory.UNSUPPORTED` sem acessar o gateway:

- conexão e reautenticação;
- faturas;
- investimentos;
- empréstimos;
- atualização manual;
- desconexão.

Isso evita transformar o recorte read-only em uma integração parcialmente mutável.

## Erros

`PluggyGatewayError` contém somente:

- categoria allowlisted;
- indicação de retry;
- código de motivo opcional e limitado.

O adapter remove a cadeia causal ao converter para `BankingProviderError`.
Exceções inesperadas do gateway são convertidas para `INTERNAL` não retryable.

Erros de construção dos DTOs neutros, IDs divergentes ou snapshot inconsistente também
resultam em `INTERNAL` sanitizado.

## Runtime

O adapter não é instalado pela imagem da API e não é registrado no
`BankingProviderRegistry`.

A composição da API permanece:

```text
registry vazio
registry congelado
APP_BANKING_ENABLED=false por padrão
```

Portanto, esta issue não cria qualquer caminho de execução externa.

## Próximos recortes

Ainda serão necessários, em issues independentes:

1. transporte HTTP e autenticação server-side com credencial efêmera;
2. parser explícito dos payloads externos para snapshots sanitizados;
3. registro condicional do adapter no runtime;
4. leitura real controlada de conexão, contas e transações;
5. importação idempotente e reconciliação local;
6. conexão, reautenticação e refresh manual;
7. demais produtos e operações destrutivas.
