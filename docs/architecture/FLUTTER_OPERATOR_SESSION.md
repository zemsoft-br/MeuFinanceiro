# Sessão local do operador no Flutter

## Objetivo

O cliente Flutter consome a autenticação local já exposta pela API sem transformar o navegador em fonte de identidade ou autorização.

A sessão existe somente em memória durante a execução atual do aplicativo. Recarregar a página encerra a sessão do ponto de vista do cliente e exige novo login.

## Contrato HTTP

A autenticação usa exclusivamente:

```text
POST   /api/v1/auth/session
GET    /api/v1/auth/session
DELETE /api/v1/auth/session
```

O login envia somente `login` e `password`. Instalação, operador, residência e papel nunca são parâmetros controlados pelo cliente.

O principal retornado pelo backend é validado de forma estrita antes de entrar no estado observável do Flutter.

## Bearer token

O bearer token:

- permanece apenas em `SessionTokenVault`, em memória;
- não entra em estado Riverpod observável;
- não é persistido em storage, arquivo, SQLite, IndexedDB ou service worker;
- não é colocado em URL, query string ou fragmento;
- não aparece em `toString`, mensagem visual ou diagnóstico;
- é removido imediatamente antes do request de logout;
- é removido quando qualquer request autenticado recebe HTTP 401.

HTTP 403 não apaga uma sessão válida: representa autorização insuficiente para aquela operação, não prova de token inválido.

## Transporte autenticado

`AuthenticatedApiClient` injeta `Authorization: Bearer ...` apenas no instante do request e não possui retry automático.

Rotas protegidas futuras devem usar essa fronteira em vez de receber ou montar tokens diretamente.

Erros são reduzidos a categorias locais e status HTTP. Corpo de resposta e bearer não são incorporados em exceptions.

## Concorrência

`OperatorSessionController` aceita somente uma autenticação ativa por vez e usa uma geração monotônica para impedir que uma resposta tardia restaure uma sessão depois de logout/invalidação.

Logout remove o token local antes de aguardar a API. Assim, novos requests protegidos falham fechado enquanto a revogação remota está em andamento.

## Navegação

`/login` é pública.

`AuthRouteGuard` é a fronteira reutilizável para rotas funcionais protegidas. Um deep link sem sessão é redirecionado para `/login?redirect=...`; somente destinos internos relativos são aceitos para evitar open redirect.

As rotas de fundação existentes (`/`, `/componentes` e `/sistema`) permanecem públicas neste recorte.

## PWA

A política existente do service worker continua excluindo `/api` e `/api/*` de qualquer interceptação/cache. Nenhuma mudança de cache foi necessária para autenticação.

## Fora do escopo

- persistência da sessão após reload;
- cookie HttpOnly;
- refresh token;
- recuperação de senha;
- MFA;
- troca de residência;
- administração de operadores;
- integração Pluggy no cliente.
