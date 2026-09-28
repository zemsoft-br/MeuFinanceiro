# Banking Pluggy

Pacote específico da integração bancária opcional com a Pluggy.

A fronteira pública continua sendo o contrato neutro `BankingProvider`. Tipos HTTP e
payloads específicos permanecem internos; o Connect Token é tratado por uma fronteira
efêmera separada e não passa pelo contrato neutro de leitura.

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

### Connect Token

`PluggyConnectTokenHttpTransport` reutiliza o núcleo autenticado e amplia a allowlist
somente para:

```text
POST /connect_token
```

A operação recebe `clientUserId` já derivado pelo backend e fixa
`avoidDuplicates=true`. `itemId`, `webhookUrl`, `oauthRedirectUri`, connector ID e
produtos não são aceitos nesta etapa. `POST /items` continua bloqueado.

O `accessToken` retornado é validado, permanece apenas em memória e nunca é armazenado
no transporte.

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

Pelo contrato `BankingProvider`, continuam retornando `UNSUPPORTED` antes do gateway:

- criação de intenção genérica de conexão;
- reautenticação;
- faturas;
- investimentos;
- empréstimos;
- atualização manual;
- desconexão.

A emissão específica de Connect Token não cria Item e não altera esse contrato.

## Restrições

Este pacote:

- depende de `meufinanceiro-banking` e `httpx` com versões fixadas;
- não lê ambiente, `.env`, argumentos CLI ou arquivos de configuração;
- não persiste Client ID, Client Secret, API key, Connect Token ou respostas;
- aceita HTTP sem TLS somente para hosts loopback usados por testes;
- fixa o host produtivo em `https://api.pluggy.ai`;
- é utilizado pelo pacote de execução apenas atrás das flags bancárias;
- não executa chamadas externas no startup.

A composição runtime e a emissão autenticada por residência estão documentadas em
`docs/architecture/PLUGGY_CONNECT_TOKEN.md`.
