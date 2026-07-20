# Migração do cliente para Flutter

- Issue principal: #24
- Scaffold e gates: #27 / PR #33
- Decisão: ADR-0008
- Estado: Fase A em implementação; shell React ainda é o runtime ativo

## 1. Objetivo

Substituir o shell React integrado pela PR #21 por uma única base Flutter para Web/PWA e futuros alvos Android, iOS e desktop, sem alterar FastAPI, PostgreSQL, worker, OpenAPI ou regras de domínio.

A migração deve preservar os contratos executáveis já validados e evitar dois clientes funcionais permanentes.

## 2. Estado atual

Na PR #33:

- `apps/app` contém um scaffold Flutter gerado pelo Flutter 3.44.6;
- o alvo ativo do scaffold é Web;
- `ProviderScope`, Riverpod e GoRouter compõem o bootstrap mínimo;
- `pubspec.lock` está versionado;
- formatação, análise, teste e build Web passam no scaffold;
- o workflow `Quality` passa a validar Python, React transitório e Flutter;
- o Compose não foi alterado.

Em `develop`, até o merge e as fases seguintes:

- `apps/web` contém o shell React/Vite;
- Docker gera os assets React compilados e usa runtime estático;
- Caddy expõe o frontend e encaminha `/api/v1` para FastAPI;
- as rotas `/`, `/componentes` e `/sistema` estão funcionais;
- PWA, manifesto, health check, acessibilidade e cache seguro foram validados;
- não existem funcionalidades financeiras no frontend.

O shell React permanece como referência executável e rollback até a paridade e a troca de runtime.

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
    integration_test/
    web/
    pubspec.yaml
    pubspec.lock
  api/
  worker/
```

O diretório `apps/app` representa o cliente multiplataforma. Android, iOS e desktop serão gerados somente quando entrarem em escopo. O serviço Docker pode continuar chamado `web`, pois serve o build Web gerado.

Estrutura inicial já criada:

```text
lib/
  main.dart
  app/
    app.dart
  routing/
    app_router.dart
  features/
    bootstrap/
      bootstrap_screen.dart
```

As pastas `core`, `theme`, `platform` e as features funcionais serão criadas conforme contratos reais entrarem em implementação, sem diretórios vazios antecipados.

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
- navegação responsiva sem criar árvores diferentes para mobile e desktop.

### API

- contratos sob `/api/v1`;
- timeout explícito;
- cancelamento quando aplicável;
- erros estruturados por código;
- health check com `cache: no-store` no servidor;
- nenhuma regra financeira decidida apenas no cliente.

O scaffold da Fase A não realiza chamadas à API.

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

O bootstrap da Fase A não representa a identidade visual final.

## 5. PWA e cache

O build Web precisa ser auditado como artefato estático.

Arquivos que exigem revalidação ou política conservadora:

- `index.html`;
- `flutter_service_worker.js` ou equivalente gerado;
- `manifest.json`;
- `version.json`;
- `main.dart.js`;
- arquivos WASM quando existirem;
- arquivos de bootstrap sem nome versionado.

Requisitos futuros da Fase C:

- requisições `/api/` não podem ser respondidas por cache de shell;
- atualização não pode manter indefinidamente JavaScript ou WASM antigo;
- upgrade do service worker precisa ser testado;
- o app deve funcionar sem CDN de fontes, ícones ou scripts;
- headers devem ser validados no smoke test.

O build da Fase A comprova compilação, não política final de PWA nem runtime de produção.

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
- [ ] concluir revisão independente e Quality no HEAD final;
- [ ] obter autorização explícita para merge.

### Fase B — Paridade do shell

- portar `/`, `/componentes` e `/sistema`;
- portar tema, componentes, estados e health check;
- implementar navegação desktop/mobile;
- adicionar testes unitários e de widget;
- validar acessibilidade e responsividade.

### Fase C — Runtime Web/PWA

- gerar build Flutter Web em Docker multi-stage;
- servir o artefato estático;
- configurar Caddy e headers;
- validar manifesto, service worker e cache;
- atualizar smoke do Compose;
- manter rollback para o shell React durante a validação.

### Fase D — Remoção do React

Somente após as Fases A–C aprovadas:

- remover `apps/web` React/Vite;
- remover Node do runtime e quality gates, salvo ferramenta ainda justificada;
- remover scripts e auditorias exclusivas do frontend antigo;
- atualizar dependências, README e runbooks;
- confirmar que nenhum caminho de produção usa React.

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
- instalação PWA;
- atualização de cache;
- `/api/` fora do service worker;
- build reproduzível;
- container não privilegiado;
- restart e encerramento gracioso.

## 8. Documentos afetados

Durante a migração, manter alinhados:

- `README.md`;
- `docs/ARCHITECTURE.md`;
- `docs/DEPENDENCIES.md`;
- `docs/ROADMAP.md`;
- `docs/runbooks/WEB_PWA.md`;
- `docs/runbooks/QUALITY_GATES.md`;
- `apps/app/README.md`;
- `apps/web/README.md` enquanto existir;
- workflows de Quality e Container Quality;
- scripts de segurança e licenças;
- Compose e Caddy quando o runtime mudar.

Até a remoção final, os documentos devem distinguir:

- arquitetura alvo Flutter;
- shell React transitório ainda presente;
- runtime atualmente ativo.

## 9. Fora do escopo da migração do shell

- autenticação;
- dados financeiros offline;
- sincronização local-first produtiva;
- publicação em lojas;
- deploy público;
- mudança do backend;
- implementação das telas financeiras do Stitch.

## 10. Conclusão

Nenhuma nova funcionalidade financeira deve ser implementada em React. Após a Fase A, o próximo trabalho de interface é a paridade do shell existente em Flutter, ainda sem trocar o runtime servido.
