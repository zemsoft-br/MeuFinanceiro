# Transporte HTTP Pluggy read-only

Status: **implementação inicial da issue #74**.

## Decisão

O transporte HTTP permanece dentro do pacote específico
`meufinanceiro-banking-pluggy` e abaixo do gateway:

```text
BankingProvider
    ↑ DTOs neutros
PluggyBankingProvider
    ↑ snapshots sanitizados
PluggyReadOnlyGateway
    ↑ payload JSON validado
PluggyHttpTransport
    ↑ HTTP allowlisted
Pluggy API
```

O transporte não é exportado pelo `__init__.py` público do pacote, não implementa o
gateway e não é instalado na imagem da API.

## Autenticação

`PluggyApplicationCredentials` recebe Client ID e Client Secret em memória. O módulo:

- não lê ambiente, `.env`, CLI ou arquivo;
- chama somente `POST /auth` para autenticação;
- aceita `apiKey` e o campo legado `accessToken`;
- mantém a chave ativa somente na instância do transporte;
- não possui propriedade que devolva a chave;
- remove chave e referência às credenciais em `close()`;
- renova no máximo uma vez após `401/403`;
- encerra após nova rejeição, sem loop.

A representação de credenciais e transporte é redigida. Exceções não encadeiam erros
do cliente HTTP, pois eles podem conter URL ou outros diagnósticos externos.

## Allowlist de operações

O transporte expõe somente:

```text
POST /auth
GET  /items/{itemId}
GET  /accounts?itemId=...
GET  /v2/transactions?accountId=...&cursor=...
```

Não existe método público genérico para executar HTTP arbitrário. Identificadores e
cursores são validados e codificados pelo cliente HTTP.

## Base URL e rede

A base produtiva é fixa:

```text
https://api.pluggy.ai
```

Bases `http://` são aceitas somente quando o host é loopback. O cliente usa:

- `follow_redirects=False`;
- `trust_env=False`, evitando proxies herdados do processo;
- timeouts separados de conexão, leitura, escrita e pool;
- ausência de cookie persistente entre operações;
- limite configurável e limitado para bytes decodificados da resposta.

## Retry

Cada requisição possui no máximo três tentativas.

| Falha | Comportamento |
|---|---|
| `401/403` | uma renovação da API key para a operação autenticada |
| `429` | prefere `RateLimit-Reset`, usa `Retry-After` como fallback |
| `429` sem janela segura | falha sem retry agressivo |
| `5xx` | backoff exponencial limitado com jitter |
| timeout/rede | backoff exponencial limitado com jitter |
| `400/404` | sem retry automático |
| redirect ou status inesperado | falha fechada |

A espera informada pelo provedor só é aceita entre zero e sessenta segundos. Não há
polling, agendamento ou execução em segundo plano neste recorte.

## Respostas

Somente respostas `2xx` com media type JSON são decodificadas. O transporte:

- lê o corpo de forma incremental;
- interrompe ao ultrapassar o limite permitido;
- rejeita JSON inválido;
- exige objeto JSON no nível raiz;
- não retorna `httpx.Response`, headers ou corpo bruto;
- não interpreta entidades financeiras.

O retorno é um objeto JSON validado destinado exclusivamente ao futuro parser do
gateway.

## Erros

`PluggyTransportError` expõe somente:

- categoria estável;
- `retryable`;
- status HTTP opcional;
- reason code allowlisted.

Não são incluídos:

- URL completa;
- query string;
- headers;
- corpo HTTP;
- Client ID ou Client Secret;
- API key;
- Item ID, Account ID ou cursor;
- mensagem original de exceção de rede.

## Testes

A suíte usa `httpx.MockTransport` e bases loopback. Ela cobre:

- autenticação atual e legado;
- refresh único e rejeição subsequente;
- `429` com e sem janela segura;
- `5xx` e rede;
- ausência de retry em erros funcionais;
- resposta excessiva, tipo de conteúdo e JSON inválidos;
- redirects;
- cookies;
- redaction;
- fechamento da instância;
- parâmetros vinculados às operações permitidas.

Nenhum teste ou gate acessa a Pluggy real.

## Runtime preservado

Permanecem inalterados:

```text
registry vazio e congelado
APP_BANKING_ENABLED=false
pacote ausente da imagem da API
nenhuma credencial carregada no startup
nenhuma chamada externa
```

## Próximos recortes

1. parser explícito de Item, contas e transações para snapshots sanitizados;
2. implementação concreta do `PluggyReadOnlyGateway` por composição;
3. registro condicional do provider, ainda desabilitado por padrão;
4. leitura real controlada;
5. importação idempotente e reconciliação local.
