# Migração do cliente para Flutter

- Issue principal: #24
- Fase A — scaffold e gates: #27 / PR #33
- Fase B — paridade do shell: #34 / PR #35
- Fase C — runtime Web/PWA e remoção do frontend anterior: #36 / PR #37
- Decisão: ADR-0008
- Estado: implementação concluída na branch; validação local completa e autorização de merge permanecem pendentes

## 1. Objetivo

Consolidar o MeuFinanceiro em uma única base Flutter para Web/PWA e futuros alvos Android, iOS e desktop, sem alterar FastAPI, PostgreSQL, worker, OpenAPI ou regras de domínio.

A coexistência temporária com React foi encerrada antecipadamente durante a PR #37. Não existe mais frontend paralelo nem mecanismo de rollback por tecnologia.

## 2. Estado atual

`apps/app` é o único cliente do repositório:

- Flutter 3.44.6 e sua revisão oficial estão fixados;
- Riverpod e GoRouter compõem o cliente;
- `pubspec.lock` está versionado;
- rotas `/`, `/componentes` e `/sistema` estão implementadas;
- navegação desktop/mobile, foco, semântica e responsividade possuem testes;
- tema, componentes, estados comuns e health check estão em Flutter;
- o Compose sempre compila e serve Flutter Web;
- o runtime estático usa Caddy não-root;
- manifesto, bootstrap e service worker são mantidos pelo projeto;
- cache, headers, deep links e artefato gerado possuem validadores;
- `apps/web`, React, Vite, TypeScript, npm lockfile e runtime Node foram removidos;
- Node.js permanece somente para testes do JavaScript próprio do PWA.

## 3. Estrutura canônica

```text
apps/
  app/
    lib/
      app/
      core/
      features/
      routing/
      theme/
      platform/
    test/
    web/
      index.html
      app_bootstrap.js
      manifest.json
      sw.js
    pubspec.yaml
    pubspec.lock
  api/
  worker/
infra/
  caddy/       entrada HTTP e proxy de API
  web/         build Flutter e runtime estático
```

O serviço Docker continua chamado `web`, pois serve o build Web gerado. O nome não representa uma segunda tecnologia de cliente.

## 4. Padrões do cliente

### Estado e dependências

- Riverpod para estado, composição e injeção;
- providers pequenos e organizados por feature;
- dependências de plataforma atrás de interfaces;
- estado de formulário separado de entidades de domínio;
- nenhum singleton mutável global.

### Roteamento

- `go_router`;
- deep links para todas as rotas públicas;
- rotas nomeadas e parâmetros tipados quando possível;
- erros de rota explícitos;
- navegação responsiva sem árvores diferentes para mobile e desktop.

### API

- contratos sob `/api/v1`;
- timeout explícito;
- cancelamento quando aplicável;
- erros estruturados por código;
- health check com `cache: no-store` no servidor;
- nenhuma regra financeira decidida apenas no cliente.

O service worker não intercepta o caminho exato `/api` nem qualquer caminho iniciado por `/api/`.

### Persistência local

A migração do shell não adiciona cache financeiro offline.

- PostgreSQL/backend continua fonte de verdade;
- tokens e dados financeiros não podem ser gravados sem decisão própria;
- Web, Android, iOS e desktop podem ter adaptadores distintos;
- SQLite/WASM só entra após contrato de autoridade, sincronização, criptografia, expiração e revogação.

### UI e acessibilidade

- Material 3 adaptado ao Design System do MeuFinanceiro;
- componentes próprios para padrões financeiros;
- breakpoints definidos no projeto;
- mesmos fluxos e rotas em desktop e mobile;
- teclado, foco, semântica e contraste validados no Web;
- suporte a escalonamento de texto e movimento reduzido quando disponível;
- tabelas densas no desktop e cards/listas no mobile.

## 5. Runtime Web/PWA

O build Web é auditado como artefato estático.

Arquivos críticos:

- `index.html`;
- `app_bootstrap.js`;
- `sw.js` mantido pelo projeto;
- `manifest.json`;
- `version.json`;
- `flutter_bootstrap.js`;
- `flutter.js`;
- `main.dart.js`;
- arquivos CanvasKit/WASM;
- assets locais.

Contratos:

- build release com `--no-web-resources-cdn --pwa-strategy=none`;
- finalização remove somente `flutter_service_worker.js` vazio e rejeita conteúdo não vazio;
- CanvasKit é selecionado e empacotado localmente;
- nenhuma fonte, script, ícone ou engine depende de CDN pública;
- requisições `/api` e `/api/` não são respondidas pelo cache do shell;
- navegação e executáveis usam rede primeiro;
- atualização online não mantém JavaScript ou WASM antigo indefinidamente;
- ativação remove caches antigos conhecidos;
- somente respostas same-origin, `GET`, bem-sucedidas e `basic` podem ser armazenadas;
- espera pela primeira ativação do worker é limitada a três segundos;
- headers de bootstrap e executáveis são conservadores;
- asset inexistente retorna `404`;
- fallback SPA é limitado a rotas sem extensão;
- o runtime final executa sem root.

O contrato é validado no source, no build local e no `/srv` extraído da imagem Docker.

## 6. Fases executadas

### Fase A — Scaffold Flutter e quality gates

Issue #27 / PR #33:

- [x] criar `apps/app` com alvo Web;
- [x] fixar Flutter e dependências diretas;
- [x] versionar lockfile;
- [x] configurar format, analyze, testes e build Web;
- [x] documentar licenças diretas;
- [x] integrar em `develop`.

### Fase B — Paridade do shell

Issue #34 / PR #35:

- [x] portar `/`, `/componentes` e `/sistema`;
- [x] portar tema, componentes, estados e health check;
- [x] implementar navegação desktop/mobile;
- [x] adicionar testes unitários e de widget;
- [x] validar acessibilidade e responsividade;
- [x] integrar em `develop`.

### Fase C — Runtime Web/PWA e consolidação Flutter

Issue #36 / PR #37:

- [x] definir build Flutter Web Docker multi-stage;
- [x] definir runtime estático não-root;
- [x] criar manifesto e service worker próprios;
- [x] definir cache seguro e headers;
- [x] atualizar smoke e gatilhos de containers;
- [x] remover `apps/web` e dependências React/Vite/npm;
- [x] remover seleção e target de rollback;
- [x] remover gates e inventários exclusivos do frontend antigo;
- [x] adicionar bloqueio contra reintrodução do frontend legado;
- [x] atualizar dependências, README e runbooks;
- [ ] executar a suíte local completa no HEAD final;
- [ ] executar o gate local completo de containers no HEAD final;
- [ ] registrar os resultados locais na PR;
- [ ] obter autorização explícita para merge.

Não haverá uma Fase D separada para remoção do React: essa limpeza foi incorporada à Fase C por decisão do mantenedor.

## 7. Gates de paridade preservados

A consolidação mantém:

- três rotas existentes;
- fallback SPA e deep links;
- asset inexistente retorna `404`;
- health operacional, degradado, indisponível e timeout;
- loading, vazio, erro e indisponibilidade;
- formulário inválido e válido;
- sidebar desktop;
- navegação móvel;
- foco e teclado;
- Escape e retorno de foco em overlays;
- contraste WCAG AA;
- ausência de overflow horizontal;
- manifesto instalável;
- service worker próprio registrado;
- atualização de cache;
- `/api` e `/api/` fora do service worker;
- ausência de CDN obrigatória;
- build reproduzível;
- container não privilegiado;
- restart e encerramento gracioso.

## 8. Fora do escopo

- autenticação;
- dados financeiros offline;
- sincronização local-first produtiva;
- publicação em lojas;
- deploy público;
- mudança do backend;
- implementação das telas financeiras do Stitch.

## 9. Conclusão

Toda funcionalidade de interface será implementada em Flutter. Qualquer proposta de um segundo frontend exige novo ADR e justificativa arquitetural explícita.
