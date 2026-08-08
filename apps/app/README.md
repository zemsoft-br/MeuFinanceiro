# Cliente Flutter

Base canônica do cliente MeuFinanceiro.

## Estado

A Fase C da migração torna o build Flutter Web o runtime padrão do Docker
Compose. O shell React continua versionado apenas como rollback transitório e
não recebe funcionalidades novas.

O cliente contém:

- rotas nomeadas `/login`, `/`, `/componentes`, `/sistema` e o deep link
  protegido `/app/integracoes/pluggy/conectar`;
- shell responsivo com sidebar desktop, drawer e navegação inferior móvel;
- tema e tokens locais, sem fontes ou assets remotos;
- catálogo de componentes, formulário demonstrativo e estados comuns;
- health check testável com timeout e classificação operacional, degradada e
  indisponível;
- autenticação local com bearer token mantido exclusivamente em memória;
- transporte autenticado reutilizável e guarda para rotas protegidas;
- Pluggy Connect Web atrás de adaptador de plataforma, carregado somente após
  ação explícita do usuário;
- dependências de plataforma atrás de interfaces;
- manifesto PWA, carregador e service worker próprios;
- cache exclusivamente de shell, com `/api` e `/api/` fora da interceptação;
- testes de rota, widget, foco, semântica, responsividade, health e contrato
  Web/PWA.

## Runtime Web

O Compose usa, por padrão:

```text
WEB_RUNTIME_TARGET=flutter-runtime
```

O build é gerado pela toolchain exata registrada em `/.flutter-version` e
`/.flutter-revision`, sem recursos Web do Flutter carregados de CDN. O container
final usa Caddy não-root e serve somente o artefato estático em `/srv`.

A integração Pluggy é uma dependência externa opcional em runtime: a CDN do
Connect não participa do bootstrap do Flutter e só é acessada depois que o
usuário autenticado inicia explicitamente uma conexão bancária.

O rollback React permanece disponível durante a validação:

```text
WEB_RUNTIME_TARGET=react-runtime
```

Depois de alterar o target em `.env`, reconstrua o serviço `web`. Não mantenha
os dois runtimes respondendo simultaneamente pelo mesmo alias.

## PWA e cache

`web/index.html` carrega `web/app_bootstrap.js`. O carregador registra
`web/sw.js` antes de iniciar o bootstrap Flutter. Em uma instalação nova, a
espera por readiness e aquisição de controle é limitada a três segundos; falha
ou lentidão do worker nunca bloqueia indefinidamente a inicialização do app.

O worker:

- ignora métodos diferentes de `GET`;
- ignora recursos de outra origem, incluindo os recursos externos da Pluggy;
- ignora o caminho exato `/api` e todos os caminhos iniciados por `/api/`;
- usa rede primeiro para navegação e recursos executáveis;
- utiliza `index.html` armazenado apenas como fallback offline de navegação;
- consulta somente o namespace de cache do MeuFinanceiro;
- remove caches antigos do Flutter e o cache legado do shell React;
- não armazena o próprio `sw.js`, tokens, respostas de health ou dados
  financeiros.

## Organização

```text
lib/
  app/        composição e shell
  core/       contratos e serviços independentes de UI
  features/   páginas e estados por experiência
  platform/   adaptadores condicionais de plataforma
  routing/    rotas e destinos canônicos
  theme/      tokens, tema e componentes-base
web/
  index.html       metadados e carregamento do bootstrap versionado
  app_bootstrap.js registro do worker e inicialização do Flutter
  manifest.json
  sw.js            política de cache do shell
```

## Autenticação local

A rota `/login` consome `POST /api/v1/auth/session`. O token bearer retornado
fica somente em `SessionTokenVault` durante a execução atual do aplicativo e
não é gravado em storage, arquivo, URL ou cache.

`AuthenticatedApiClient` injeta o bearer apenas durante requests protegidos,
sem retry automático. HTTP 401 invalida a sessão local; HTTP 403 preserva o
token e representa autorização insuficiente para a operação.

O logout remove primeiro a referência local do token e depois chama
`DELETE /api/v1/auth/session`. Um reload completo exige novo login.

Rotas funcionais protegidas devem usar `AuthRouteGuard`. A especificação
completa está em `../../docs/architecture/FLUTTER_OPERATOR_SESSION.md`.

## Pluggy Connect Web

A rota protegida `/app/integracoes/pluggy/conectar` implementa a primeira
experiência bancária online do Flutter Web/PWA.

O cliente não cria identidade Pluggy nem calcula escopo de residência. O fluxo
é:

```text
sessão local
  -> POST /api/v1/banking/pluggy/connect-token
  -> Connect Token efêmero em memória
  -> Pluggy Connect Web carregado de forma lazy
  -> item.id transitório do callback
  -> POST /api/v1/banking/pluggy/connections
  -> connectionId/status locais
```

O callback do widget é tratado como entrada não confiável. O Flutter extrai
somente o `item.id` e o backend comprova ownership diretamente na Pluggy antes
de persistir/reutilizar a conexão local. Connect Token e Item ID não entram em
storage, URL, cache, logs ou estado observável durável.

No runtime Web não é usado o pacote `flutter_pluggy_connect`: a versão avaliada
para este recorte não declara suporte Web. O adaptador JavaScript fica isolado
em `lib/platform/pluggy/` e fixa a versão da biblioteca oficial carregada pela
CDN; nenhum script Pluggy é colocado em `index.html` ou no bootstrap.

No modo demonstração a integração externa é bloqueada antes da emissão de
Connect Token. Não existe fila offline nem retry automático das mutações.

A especificação e as referências oficiais estão em
`../../docs/architecture/FLUTTER_PLUGGY_CONNECT.md`.

## Comandos

```bash
flutter pub get --enforce-lockfile
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
node --check web/app_bootstrap.js
node --check web/sw.js
flutter build web --release --no-web-resources-cdn --pwa-strategy=none
python ../../infra/scripts/finalize-flutter-web-build.py --build-dir build/web
python ../../infra/scripts/check-flutter-web-contract.py
```

O finalizador remove somente o arquivo legado vazio produzido pelo SDK. Se
`flutter_service_worker.js` contiver código, o comando falha em vez de apagar o
artefato silenciosamente.

Use exatamente a versão e a revisão registradas na raiz do repositório.
