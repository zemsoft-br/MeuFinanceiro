# Banking Pluggy Execution

Pacote de orquestração read-only e contextual da integração Pluggy.

## Fronteiras

O pacote compõe:

```text
BankingIntegrationStore
    -> conexão interna com RLS por residência
    -> credenciais efêmeras habilitadas
PluggyGatewayHttpTransport
    -> PluggyHttpReadOnlyGateway
    -> PluggyBankingProvider
    -> DTOs neutros
```

A API pública do serviço recebe somente:

- installation ID;
- residence ID;
- connection ID interno;
- account ID externo somente para a leitura de transações, após validação de
  pertencimento à conexão.

Item ID nunca é aceito como argumento público.

## Operações

`PluggyReadOnlyExecutionService` oferece:

- estado da conexão;
- capacidades;
- contas;
- uma página de transações.

Cada chamada cria uma sessão efêmera separada. O transporte é fechado no `finally` em
sucesso ou falha.

## Segurança

- conexão resolvida pelo store sob RLS;
- provider diferente de `pluggy` é rejeitado antes da decriptação;
- conexão desconectada é rejeitada antes da decriptação;
- configuração deve estar `enabled`;
- credenciais existem somente dentro do callback do store;
- factory e transporte são injetáveis nos testes;
- erros inesperados são convertidos para `BankingProviderError` sanitizado;
- conta é validada contra as contas da conexão antes das transações;
- nenhum log, payload bruto ou credencial é produzido pelo pacote.

Os DTOs neutros ainda contêm identificadores externos operacionais. Este pacote é uma
fronteira interna e não deve ser exposto diretamente por endpoint HTTP. A futura
persistência de contas e transações deverá mapear esses identificadores para IDs locais
antes da exposição ao cliente.

## Runtime

O pacote não é instalado na imagem da API, não é registrado no startup e não executa
chamadas externas durante testes ou CI.
