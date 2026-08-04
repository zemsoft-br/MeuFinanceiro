# Banking Pluggy

Pacote específico da integração bancária opcional com a Pluggy.

A fronteira pública continua sendo o contrato neutro `BankingProvider`. Nenhum tipo
HTTP, token ou payload específico da Pluggy atravessa essa fronteira.

## Componentes atuais

### Adapter read-only

`PluggyBankingProvider` converte snapshots sanitizados do
`PluggyReadOnlyGateway` para DTOs neutros:

- estado da conexão;
- capacidades observadas;
- contas;
- transações paginadas;
- estados `POSTED` e `PENDING` preservados separadamente.

### Transporte HTTP interno

O módulo interno `meufinanceiro_banking_pluggy.transport` fornece:

- autenticação server-side com `apiKey` e fallback legado `accessToken`;
- API key somente em memória;
- leitura allowlisted de Item, contas e transações;
- uma única renovação após `401/403`;
- tratamento limitado de `429`, `5xx`, timeout e rede;
- tamanho máximo de resposta;
- rejeição de redirect, conteúdo não JSON e payload inválido;
- erros sanitizados sem URL, headers, corpo HTTP ou identificadores.

O transporte não implementa o `PluggyReadOnlyGateway` e não realiza parsing para os
snapshots do adapter. Essa composição permanece para uma issue posterior.

## Operações bloqueadas

As operações abaixo continuam retornando `UNSUPPORTED` antes do gateway:

- criação de intenção de conexão;
- reautenticação;
- faturas;
- investimentos;
- empréstimos;
- atualização manual;
- desconexão.

## Restrições

Este pacote:

- depende de `meufinanceiro-banking` e `httpx` com versões fixadas;
- não lê ambiente, `.env`, argumentos CLI ou arquivos de configuração;
- não persiste Client ID, Client Secret, API key ou respostas;
- aceita HTTP sem TLS somente para hosts loopback usados por testes;
- fixa o host produtivo em `https://api.pluggy.ai`;
- não é instalado nem registrado no runtime da API;
- não executa chamadas externas durante testes ou CI.

A futura implementação concreta do gateway deverá receber o transporte por injeção,
converter payloads allowlisted para snapshots imutáveis e permanecer desabilitada por
padrão no runtime.
