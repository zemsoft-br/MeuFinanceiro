# Cliente Flutter

Base canônica do cliente MeuFinanceiro.

## Estado

A Fase C da migração torna o build Flutter Web o runtime padrão do Docker
Compose. O shell React continua versionado apenas como rollback transitório e
não recebe funcionalidades novas.

O cliente contém:

- rotas nomeadas `/`, `/componentes` e `/sistema`;
- shell responsivo com sidebar desktop, drawer e navegação inferior móvel;
- tema e tokens locais, sem fontes ou assets remotos;
- catálogo de componentes, formulário demonstrativo e estados comuns;
- health check testável com timeout e classificação operacional, degradada e
  indisponível;
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
`/.flutter-revision`, sem recursos Web carregados de CDN. O container final usa
Caddy não-root e serve somente o artefato estático em `/srv`.

O rollback React permanece disponível durante a validação:

```text
WEB_RUNTIME_TARGET=react-runtime
```

Depois de alterar o target em `.env`, reconstrua o serviço `web`. Não mantenha
os dois runtimes respondendo simultaneamente pelo mesmo alias.

## PWA e cache

`web/index.html` carrega `web/app_bootstrap.js`. O carregador registra
`web/sw.js` antes de iniciar o bootstrap Flutter, permitindo que a primeira
carga já seja controlada quando o navegador concluir a instalação do worker.

O worker:

- ignora métodos diferentes de `GET`;
- ignora recursos de outra origem;
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

## Comandos

```bash
flutter pub get --enforce-lockfile
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
node --check web/app_bootstrap.js
node --check web/sw.js
flutter build web --release --no-web-resources-cdn
python ../../infra/scripts/check-flutter-web-contract.py
```

Use exatamente a versão e a revisão registradas na raiz do repositório.
