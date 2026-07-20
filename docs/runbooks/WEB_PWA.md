# Runtime Flutter Web/PWA e transição do shell React

Este runbook descreve o runtime Web/PWA do MeuFinanceiro e os contratos operacionais da migração Flutter.

> **Estado da Fase C:** o serviço `web` usa Flutter por padrão. `apps/web` permanece somente como rollback transitório até a Fase D. Nenhuma funcionalidade financeira nova deve ser implementada no shell React.

A sequência completa está em [FLUTTER_CLIENT_MIGRATION.md](FLUTTER_CLIENT_MIGRATION.md).

## Endereços locais

Com o ambiente iniciado por `./infra/scripts/dev-up.sh` ou `./infra/scripts/dev-up.ps1`:

- aplicação: `http://127.0.0.1:8080`;
- componentes: `http://127.0.0.1:8080/componentes`;
- diagnóstico: `http://127.0.0.1:8080/sistema`;
- carregador: `http://127.0.0.1:8080/app_bootstrap.js`;
- manifesto: `http://127.0.0.1:8080/manifest.json`;
- service worker: `http://127.0.0.1:8080/sw.js`;
- documentação da API: `http://127.0.0.1:8080/api/v1/docs`.

As três rotas são contratos de deep link e fallback SPA.

## Build e runtime

O serviço `web` usa `infra/web/Dockerfile`, com targets independentes:

```text
flutter-runtime   target padrão
react-runtime     rollback transitório
```

O estágio Flutter:

1. lê `.flutter-version` e `.flutter-revision`;
2. clona a versão e confirma a revisão exata;
3. resolve `pubspec.lock` com `--enforce-lockfile`;
4. gera `flutter build web --release --no-web-resources-cdn --pwa-strategy=none`;
5. executa o finalizador estrito do artefato;
6. copia somente `build/web` para o runtime final.

O finalizador remove `flutter_service_worker.js` apenas quando o SDK gerar esse arquivo vazio. Conteúdo não vazio bloqueia o build, evitando apagar silenciosamente uma política de cache inesperada.

O runtime final usa Caddy, executa como UID/GID `65534`, escuta em `5173`, remove a capability de bind privilegiado e não inclui SDK Flutter, Git ou fontes do projeto.

O Caddy externo continua sendo a única entrada publicada e encaminha o caminho exato `/api` e `/api/*` diretamente para FastAPI. O Caddy interno do serviço `web` recusa essas mesmas fronteiras, servindo apenas o shell estático.

## Rollback React

O `.env` padrão contém:

```text
WEB_RUNTIME_TARGET=flutter-runtime
```

Para rollback temporário:

```text
WEB_RUNTIME_TARGET=react-runtime
```

Depois reconstrua o serviço:

```bash
docker compose build web
docker compose up --detach --wait web caddy
```

Os scripts `dev-up.sh` e `dev-up.ps1` aceitam somente esses dois targets e validam qual runtime foi efetivamente servido. O rollback deve ser uma decisão operacional explícita. Flutter e React não podem responder simultaneamente pelo alias `web`. Retornar a Flutter usa o mesmo procedimento com `flutter-runtime`.

A Fase D removerá `apps/web`, Node, Vite e esse target somente após a Fase C estar integrada e validada.

## Instalação

### Chrome, Edge e navegadores Chromium

1. Abra a aplicação pelo endereço HTTP local suportado ou por HTTPS no acesso remoto configurado.
2. Use a ação de instalação apresentada pelo navegador quando o manifesto e o service worker estiverem ativos.
3. Alternativamente, use **Instalar MeuFinanceiro** no menu do navegador.

`localhost` e `127.0.0.1` são contextos seguros aceitos pelos navegadores. Para outro dispositivo na rede ou via Tailscale, a instalação do service worker pode exigir HTTPS conforme a política do navegador.

### Safari no iPhone ou iPad

1. Abra a aplicação no Safari.
2. Use **Compartilhar**.
3. Escolha **Adicionar à Tela de Início**.

O evento de instalação programática não é uniforme no Safari; instruções manuais continuam necessárias.

## Manifesto

`apps/app/web/manifest.json` define:

- nome e nome curto `MeuFinanceiro`;
- idioma `pt-BR`;
- `start_url` e `scope` na raiz;
- `display: standalone`;
- cores locais do Design System;
- ícones 192, 512 e variantes maskable;
- nenhuma aplicação relacionada obrigatória.

O validator `infra/scripts/check-flutter-web-contract.py` examina o manifesto versionado e o arquivo copiado para o build release.

## Bootstrap versionado

`index.html` contém apenas metadados e a referência a `app_bootstrap.js`. O carregador versionado:

- registra `sw.js` com `updateViaCache: 'none'`;
- em uma instalação nova, aguarda readiness e aquisição de controle por no máximo três segundos;
- em uma carga já controlada, solicita atualização em segundo plano sem bloquear a aplicação;
- carrega `flutter_bootstrap.js` depois de preparar o worker ou atingir o limite;
- continua inicializando Flutter quando o navegador não suporta service worker ou quando o registro falha.

`app_bootstrap.js` participa do precache mínimo para que o HTML offline consiga iniciar o shell. O arquivo recebe `no-store` no servidor e é atualizado por rede primeiro quando online.

## Política de cache obrigatória

O cache é exclusivamente de shell:

- HTML estático da aplicação;
- carregador versionado;
- manifesto;
- bootstrap e JavaScript compilado;
- arquivos CanvasKit/WASM empacotados localmente;
- fontes e imagens da própria interface;
- ícones da PWA.

O próprio `sw.js` não é armazenado pelo worker. Sua atualização depende da verificação normal do navegador e do header `no-store`.

O service worker não pode interceptar nem armazenar o caminho exato `/api` ou qualquer resposta sob `/api/`, incluindo:

- tokens;
- respostas de health check;
- cadastros;
- lançamentos;
- saldos;
- anexos;
- qualquer futuro dado financeiro retornado pela API.

Não altere essa regra sem issue própria, análise de segurança e novo ADR.

## Service worker do projeto

A toolchain fixada não é usada como autoridade para uma política automática de cache. O projeto mantém `apps/app/web/sw.js`, registrado explicitamente por `app_bootstrap.js`.

Contratos:

- somente `GET` same-origin pode ser considerado;
- o caminho exato `/api` e qualquer pathname iniciado por `/api/` retornam do handler sem `respondWith`;
- navegação usa rede primeiro;
- respostas de navegação são normalizadas para a chave `/index.html`, evitando uma entrada por URL;
- quando a navegação falha offline, o worker pode retornar o `index.html` previamente armazenado;
- bootstrap, JavaScript, WASM e assets também usam rede primeiro;
- somente respostas bem-sucedidas e `basic` entram no cache;
- leituras de fallback consultam somente o namespace de cache do MeuFinanceiro;
- instalação armazena somente os arquivos mínimos do shell;
- `skipWaiting` ocorre somente depois de um precache bem-sucedido;
- ativação remove versões antigas do namespace Flutter;
- ativação também remove caches legados `meufinanceiro-shell-*` do React;
- `clients.claim` ocorre dentro da ativação;
- `flutter_service_worker.js` legado é proibido no artefato final.

O validator exige que `app_bootstrap.js` e `sw.js` gerados sejam idênticos aos arquivos versionados. Também exige configuração efetiva de CanvasKit local e presença de `canvaskit.js` e `canvaskit.wasm`; strings de fallback inativas dentro do loader do SDK não são tratadas como dependência remota por si só.

## Headers do runtime estático

`infra/web/Caddyfile` aplica política conservadora:

| Recurso | Política |
|---|---|
| `index.html`, `app_bootstrap.js`, manifesto, `sw.js`, bootstrap, `main.dart.js`, `version.json` | `no-cache, no-store, must-revalidate` |
| `/assets/*`, `/canvaskit/*`, `/icons/*`, favicon | cache curto com revalidação |
| respostas `404` | `no-store` |
| `/api` e `/api/*` no runtime estático | `404`; nunca fallback SPA |

Nenhum JavaScript, WASM ou bootstrap recebe `immutable` nesta fase. A política poderá ser refinada quando houver nomes de arquivo comprovadamente content-addressed e teste de upgrade equivalente.

## Fallback SPA e arquivos inexistentes

- `/`, `/componentes`, `/sistema` e outras rotas sem extensão recebem `index.html`;
- arquivos existentes são servidos diretamente;
- `/api` e caminhos sob `/api/` não recebem fallback;
- prefixes de assets, ícones e CanvasKit não recebem fallback;
- arquivo inexistente com extensão recebe `404`.

Isso impede que uma requisição por JavaScript ausente receba HTML com status `200`.

## Validação

Contrato source e sintaxe:

```bash
node --check apps/app/web/app_bootstrap.js
node --check apps/app/web/sw.js
python infra/scripts/check-flutter-web-contract.py --source-only
```

Contrato do build:

```bash
cd apps/app
flutter build web --release --no-web-resources-cdn --pwa-strategy=none
python ../../infra/scripts/finalize-flutter-web-build.py --build-dir build/web
cd ../..
python infra/scripts/check-flutter-web-contract.py
```

Integração completa:

```bash
docker compose build --pull web
docker compose up --detach --wait --wait-timeout 180
bash tests/smoke/compose-smoke.sh
```

O smoke comprova:

- API operacional via Caddy externo;
- `/api` não devolvido como HTML da SPA;
- HTML Flutter nas três rotas;
- carregador, manifesto e registro do worker;
- exclusão textual explícita de `/api` e `/api/` no worker;
- headers conservadores;
- `404` para asset inexistente;
- runtime Web não-root;
- health do Worker e idempotência da fila;
- funcionamento após restart.

`Container Quality` também extrai `/srv` diretamente da imagem e executa o validator sobre o artefato que será servido. O target React é construído, iniciado isoladamente e validado quanto a fallback e usuário não-root.

## Diagnóstico no navegador

No DevTools:

1. abra **Application**;
2. verifique **Manifest** e os ícones;
3. confirme que `sw.js` é o worker ativo;
4. em **Cache Storage**, confirme somente o namespace esperado;
5. confirme que caches `meufinanceiro-shell-*` antigos foram removidos após ativação;
6. confirme que não existem entradas distintas para cada rota navegada;
7. em **Network**, confirme que requisições `/api` e `/api/` não têm origem `ServiceWorker`;
8. confirme os headers de `index.html`, `app_bootstrap.js`, `sw.js`, `main.dart.js`, CanvasKit/WASM e assets;
9. simule offline somente depois de uma carga online completa.

Para remover o estado local de teste, use **Clear site data**. Isso não remove o PostgreSQL do Docker Compose.

## Critério para remover o React

A Fase D somente poderá iniciar quando:

- as três rotas Flutter estiverem validadas pelo Compose;
- PWA e cache estiverem validados;
- `Quality` e `Container Quality`, ou a suíte local equivalente documentada quando o Actions estiver indisponível, passarem no HEAD final;
- rollback estiver documentado e executável durante a janela de validação;
- nenhum caminho do runtime padrão usar React;
- houver revisão independente sem achados bloqueantes.
