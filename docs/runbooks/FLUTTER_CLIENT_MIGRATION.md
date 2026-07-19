# Migração do cliente para Flutter

- Issue: #24
- Decisão: ADR-0008
- Estado: planejamento aprovado; implementação ainda não iniciada

## 1. Objetivo

Substituir o shell React integrado pela PR #21 por uma única base Flutter para Web/PWA e futuros alvos Android, iOS e desktop, sem alterar FastAPI, PostgreSQL, worker, OpenAPI ou regras de domínio.

A migração deve preservar os contratos executáveis já validados e evitar dois clientes funcionais permanentes.

## 2. Estado atual

Em `develop`:

- `apps/web` contém o shell React/Vite;
- Docker gera assets Web compilados e usa runtime estático;
- Caddy expõe o frontend e encaminha `/api/v1` para FastAPI;
- as rotas `/`, `/componentes` e `/sistema` estão funcionais;
- PWA, manifesto, health check, acessibilidade e cache seguro foram validados;
- não existem funcionalidades financeiras no frontend.

Esse é o melhor ponto para migrar: o shell é pequeno e ainda não há telas de domínio para portar.

## 3. Estrutura alvo

```text
apps/
  app/
    android/
    ios/
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
  api/
  worker/
```

O diretório `apps/app` representa o cliente multiplataforma. O serviço Docker pode continuar chamado `web`, pois serve o build Web gerado.

Estrutura inicial de `lib/`:

```text
lib/
  main.dart
  app/
    app.dart
    bootstrap.dart
  routing/
    app_router.dart
    routes.dart
  core/
    api/
    config/
    errors/
    health/
    localization/
    persistence/
    security/
  theme/
    app_theme.dart
    tokens.dart
    components/
  features/
    home/
    components_catalog/
    system_health/
  platform/
    pwa/
    storage/
```

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

### Persistência local

A migração do shell não adiciona cache financeiro offline.

A camada deve ser preparada por portas/adaptadores para futura persistência local, mas:

- PostgreSQL/backend continua fonte de verdade;
- tokens e dados financeiros não podem ser gravados sem decisão própria;
- Web, Android, iOS e desktop podem ter adaptadores distintos;
- SQLite/WASM só entra quando o contrato de sincronização, criptografia, expiração e revogação estiver definido.

### UI e acessibilidade

- Material 3 adaptado ao Design System do MeuFinanceiro;
- componentes próprios para padrões financeiros;
- breakpoints definidos no projeto;
- mesmos fluxos e rotas em desktop e mobile;
- teclado, foco, semântica e contraste validados no Web;
- suporte a escalonamento de texto e movimento reduzido quando disponível;
- tabelas densas no desktop e cards/listas no mobile.

## 5. PWA e cache

O build Web precisa ser auditado como artefato estático.

Arquivos que exigem revalidação ou política conservadora:

- `index.html`;
- `flutter_service_worker.js` ou equivalente gerado;
- `manifest.json`/manifesto;
- `version.json`;
- `main.dart.js`;
- `sqlite3.wasm` ou outros WASM, quando existirem;
- arquivos de bootstrap sem nome versionado.

Somente assets com nome realmente imutável recebem cache longo.

Requisitos:

- requisições `/api/` não podem ser respondidas por cache de shell;
- atualização não pode manter indefinidamente `main.dart.js` antigo;
- a versão do service worker precisa ser testada em upgrade;
- o app deve funcionar sem CDN de fontes, ícones ou scripts;
- headers devem ser validados no smoke test.

## 6. Decomposição em PRs

### PR A — Scaffold Flutter e quality gates

- criar `apps/app`;
- fixar Flutter/Dart e dependências diretas;
- configurar format, analyze, testes e build Web;
- adicionar licença e auditoria de dependências;
- não alterar o runtime servido ao usuário.

### PR B — Paridade do shell

- portar `/`, `/componentes` e `/sistema`;
- portar tema, componentes, estados e health check;
- implementar navegação desktop/mobile;
- adicionar testes unitários e widget;
- validar acessibilidade e responsividade.

### PR C — Runtime Web/PWA

- gerar build Flutter Web em Docker multi-stage;
- servir artefato estático;
- configurar Caddy e headers;
- validar manifesto, service worker e cache;
- atualizar smoke do Compose;
- manter rollback para o shell React durante a validação.

### PR D — Remoção do React

Somente após PRs A–C aprovadas:

- remover `apps/web` React/Vite;
- remover Node do runtime e quality gates, salvo ferramenta ainda justificada;
- remover scripts e auditorias exclusivas do frontend antigo;
- atualizar dependências, README e runbooks;
- confirmar que nenhum caminho de produção usa React.

## 7. Gates de paridade

Antes de remover React, validar:

- três rotas existentes;
- fallback SPA/deep link;
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

## 8. Documentos que precisam ser atualizados durante a implementação

- `README.md`;
- `docs/ARCHITECTURE.md`;
- `docs/DEPENDENCIES.md`;
- `docs/ROADMAP.md`;
- `docs/runbooks/WEB_PWA.md`;
- `docs/runbooks/QUALITY_GATES.md`;
- `apps/web/README.md` ou seu substituto;
- workflows de Quality e Container Quality;
- scripts de segurança e licenças;
- Compose e Caddy.

Até a remoção final, documentos devem distinguir claramente:

- arquitetura alvo Flutter;
- shell React transitório ainda presente;
- runtime atualmente ativo.

## 9. Fora do escopo

- autenticação;
- dados financeiros offline;
- sincronização local-first produtiva;
- publicação em lojas;
- deploy público;
- mudança do backend;
- implementação das telas funcionais do Stitch.

## 10. Conclusão

Nenhuma nova funcionalidade financeira deve ser implementada em React. O próximo trabalho de interface é o scaffold Flutter e a paridade do shell já validado.
