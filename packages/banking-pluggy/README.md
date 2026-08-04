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

`PluggyGatewayHttpTransport` fornece:

- autenticação server-side com `apiKey` e fallback legado `accessToken`;
- API key somente em memória;
- leitura allowlisted de Item, contas e transações;
- paginação de transações pelo parâmetro oficial `after`;
- filtro opcional `createdAtFrom` para registros criados após uma janela;
- uma única renovação após `401/403`;
- tratamento limitado de `429`, `5xx`, timeout e rede;
- tamanho máximo de resposta;
- rejeição de redirect, conteúdo não JSON e payload inválido;
- erros sanitizados sem URL, headers, corpo HTTP ou identificadores.

### Gateway concreto

`PluggyHttpReadOnlyGateway` converte payloads JSON para snapshots imutáveis:

- Item e estados de conexão;
- capacidades conservadoras declaradas pelo conector;
- contas com número reduzido a máscara;
- transações, parcelas, vínculo de fatura e cursor opaco;
- associações cross-item e cross-account rejeitadas;
- erros de transporte traduzidos sem cadeia causal.

O gateway encaminha `changed_since` como `createdAtFrom`. Esse filtro cobre registros
criados na janela e não substitui reconciliação periódica de atualizações e exclusões.

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

O próximo recorte poderá registrar condicionalmente o provider, ainda desabilitado por
padrão, sem iniciar sincronização ou importar dados financeiros.
