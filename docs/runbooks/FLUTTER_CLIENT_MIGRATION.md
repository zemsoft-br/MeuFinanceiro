# Migração do cliente para Flutter

- Issue principal: #24
- Fase A — scaffold e gates: #27 / PR #33
- Fase B — paridade do shell: #34 / PR #35
- Fase C — runtime Web/PWA: #36 / PR #37
- Decisão: ADR-0008
- Estado: Fases A e B integradas; Fase C implementada e revisada, pendente de validação local completa e autorização de merge

## 1. Objetivo

Substituir o shell React integrado pela PR #21 por uma única base Flutter para Web/PWA e futuros alvos Android, iOS e desktop, sem alterar FastAPI, PostgreSQL, worker, OpenAPI ou regras de domínio.

A migração preserva os contratos executáveis já validados e evita dois clientes funcionais permanentes.

## 2. Estado atual

Em `develop`, após as PRs #33 e #35:

- `apps/app` contém o cliente Flutter Web;
- Flutter 3.44.6 e sua revisão oficial estão fixados;
- Riverpod e GoRouter compõem o cliente;
- `pubspec.lock` está versionado;
- rotas `/`, `/componentes` e `/sistema` estão portadas;
- navegação desktop/mobile, foco, semântica e responsividade possuem testes;
- tema, componentes, estados comuns e health check foram portados;
- o workflow `Quality` valida Python, React transitório e Flutter;
- o Compose ainda serve React até a integração da Fase C.

Na PR #37, a Fase C:

- produz o build Flutter Web em Docker;
- usa Flutter como target padrão do serviço `web`;
- mantém `react-runtime` como rollback explícito;
- adiciona runtime estático Caddy não-root;
- registra manifesto e service worker próprios;
- valida cache, headers, deep links e artefato gerado;
- adiciona suíte local equivalente aos gates de `Quality` e `Container Quality`.

A remoção definitiva do React continua bloqueada até a Fase C ser integrada e validada localmente no HEAD final.

## 3. Estrutura alvo

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
  web/         build multi-target e runtime estático
```

`apps/app` representa o cliente multiplataforma. Android, iOS e desktop serão gerados somente quando entrarem em escopo. O serviço Docker continua chamado `web`, pois serve o build Web gerado.

Enquanto a Fase D não for concluída, `apps/web` permanece no repositório apenas como rollback transitório.

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
- ativação remove caches antigos Flutter e o cache legado React;
- somente respostas same-origin, `GET`, bem-sucedidas e `basic` podem ser armazenadas;
- espera pela primeira ativação do worker é limitada a três segundos;
- headers de bootstrap e executáveis são conservadores;
- asset inexistente retorna `404`;
- fallback SPA é limitado a rotas sem extensão;
- o runtime final executa sem root.

O contrato é validado no source, no build local e no `/srv` extraído da imagem Docker.

## 6. Decomposição em PRs

### Fase A — Scaffold Flutter e quality gates

Issue #27 / PR #33:

- [x] criar `apps/app` com alvo Web;
- [x] fixar Flutter e dependências diretas;
- [x] versionar lockfile;
- [x] configurar format, analyze, testes e build Web;
- [x] documentar licenças diretas;
- [x] manter React nos gates;
- [x] não alterar o runtime servido;
- [x] concluir revisão independente e Quality;
- [x] integrar em `develop`.

### Fase B — Paridade do shell

Issue #34 / PR #35:

- [x] portar `/`, `/componentes` e `/sistema`;
- [x] portar tema, componentes, estados e health check;
- [x] implementar navegação desktop/mobile;
- [x] adicionar testes unitários e de widget;
- [x] validar acessibilidade e responsividade;
- [x] integrar em `develop`.

### Fase C — Runtime Web/PWA

Issue #36 / PR #37:

- [x] definir build Flutter Web Docker multi-stage;
- [x] definir runtime estático não-root;
- [x] configurar Flutter como target padrão e React como rollback;
- [x] criar manifesto e service worker próprios;
- [x] definir cache seguro e headers;
- [x] atualizar smoke e gatilhos de containers;
- [x] concluir revisão independente estática;
- [x] corrigir os achados identificados na revisão e nas execuções parciais do CI;
- [ ] executar `python infra/scripts/run-quality.py --recreate` localmente no HEAD final;
- [ ] executar o gate local completo de containers no HEAD final;
- [ ] registrar os resultados locais na PR;
- [ ] obter autorização explícita para merge.

### Fase D — Remoção do React

Somente após as Fases A–C aprovadas:

- remover `apps/web` React/Vite;
- remover Node do runtime e quality gates, salvo ferramenta ainda justificada;
- remover scripts e auditorias exclusivas do frontend antigo;
- remover o target de rollback;
- atualizar dependências, README e runbooks;
- confirmar que nenhum caminho do runtime usa React.

## 7. Gates de paridade

Antes de remover React, validar:

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
- restart e encerramento gracioso;
- rollback React construível durante a janela da Fase C.

## 8. Documentos afetados

Durante a migração, manter alinhados:

- `README.md`;
- `docs/ARCHITECTURE.md`;
- `docs/DEPENDENCIES.md`;
- `docs/ROADMAP.md`;
- `docs/runbooks/WEB_PWA.md`;
- `docs/runbooks/QUALITY_GATES.md`;
- `docs/runbooks/LOCAL_DEVELOPMENT.md`;
- `apps/app/README.md`;
- `apps/web/README.md` enquanto existir;
- workflows de Quality e Container Quality;
- scripts de segurança e licenças;
- Compose e Caddy.

Até a remoção final, os documentos distinguem:

- arquitetura canônica Flutter;
- runtime padrão Flutter;
- shell React ainda versionado apenas para rollback;
- Fase D ainda pendente.

## 9. Fora do escopo da migração do shell

- autenticação;
- dados financeiros offline;
- sincronização local-first produtiva;
- publicação em lojas;
- deploy público;
- mudança do backend;
- implementação das telas financeiras do Stitch.

## 10. Conclusão

Nenhuma nova funcionalidade financeira deve ser implementada em React. Após a validação local e integração da Fase C, o próximo passo é remover o shell antigo em uma PR isolada, sem misturar essa limpeza com módulos de negócio.
