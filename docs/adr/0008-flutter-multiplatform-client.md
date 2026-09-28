# ADR-0008 — Flutter como cliente canônico multiplataforma

- Status: Accepted
- Data: 2026-07-19
- Emenda operacional: 2026-07-21
- Decisores: mantenedores
- Supersede: ADR-0001 e ADR-0007 na escolha e implementação da tecnologia de interface

## Contexto

O MeuFinanceiro precisa oferecer uma única experiência em desktop e dispositivos móveis, preservar operação autohospedada e manter as regras financeiras fora do cliente.

O ADR-0001 escolheu React e TypeScript para a PWA. O ADR-0007 e a PR #21 concretizaram essa decisão com um shell responsivo, navegação acessível, health check degradável, manifesto, política conservadora de cache e runtime estático reproduzível.

Após essa validação, o mantenedor corrigiu a decisão de stack para alinhar o MeuFinanceiro aos demais produtos Zemsoft: a interface operacional deve usar Flutter. O objetivo é compartilhar uma única base entre Web/PWA e futuros alvos Android, iOS e desktop, em vez de manter clientes paralelos.

A mudança não invalida os contratos funcionais comprovados pela PR #21. Ela substitui a tecnologia usada para implementá-los.

## Decisão

### Cliente canônico

1. Flutter é a única tecnologia de cliente do MeuFinanceiro.
2. Existe uma única base de código em `apps/app` para Web/PWA e futuros alvos Android, iOS e desktop.
3. Não será mantido frontend React funcional, target de rollback ou segunda árvore de interface.
4. O serviço Docker e a rota pública continuam chamados `web`, pois representam o artefato Web compilado, não a tecnologia-fonte.
5. Node.js pode existir apenas como ferramenta de teste do JavaScript próprio do PWA; não faz parte do runtime nem do build do frontend.
6. A reintrodução de outro frontend exige novo ADR e justificativa explícita.

### Arquitetura do cliente

A implementação adota:

- `go_router` para roteamento declarativo e deep links;
- Riverpod para estado, composição e injeção de dependências;
- clientes e DTOs separados dos modelos de apresentação;
- portas/adaptadores para persistência local e recursos de plataforma;
- internacionalização nativa do Flutter para `pt-BR`;
- tema e componentes próprios derivados do Design System do projeto;
- fontes, ícones e assets empacotados, sem CDN obrigatória.

Versões diretas são fixadas no `pubspec.yaml` e inventariadas com licença antes do merge da implementação.

### Backend e domínio

Permanecem vigentes:

- FastAPI e OpenAPI como contrato HTTP;
- PostgreSQL local como fonte principal de verdade;
- worker e fila persistente;
- Caddy como entrada HTTP;
- Docker Compose como distribuição principal;
- nenhuma regra financeira exclusiva no cliente;
- autorização obrigatória no backend;
- integrações externas por adaptadores.

O cliente pode manter estado de interface e caches explicitamente autorizados. Dados financeiros locais no dispositivo não se tornam fonte autoritativa e exigem ADR próprio antes de persistência offline produtiva.

### PWA e cache

Os contratos de segurança validados anteriormente são preservados:

- respostas e mutações sob `/api/` não podem ser armazenadas pelo service worker;
- tokens, health checks, saldos, movimentações, anexos e dados financeiros ficam fora do cache de shell;
- falha da API não impede a navegação para estados locais de diagnóstico;
- instalação PWA continua dependente do suporte do navegador e de contexto seguro;
- manifesto, bootstrap e service worker são mantidos pelo projeto;
- CanvasKit/WASM é empacotado localmente;
- arquivos de entrada e runtime recebem política conservadora de cache;
- somente assets comprovadamente imutáveis podem receber cache longo.

A política é validada por testes, inspeção do artefato e headers. O comportamento gerado pelo SDK Flutter não é presumido seguro sem auditoria.

### Qualidade

Os gates do cliente Flutter incluem:

- `dart format --output=none --set-exit-if-changed`;
- `flutter analyze`;
- testes unitários e de widget;
- testes de roteamento, health check e acessibilidade;
- `flutter build web --release --no-web-resources-cdn --pwa-strategy=none`;
- auditoria de dependências e licenças;
- testes Node do JavaScript próprio do PWA;
- smoke do artefato estático em Docker Compose;
- validação do artefato extraído da imagem;
- inspeção desktop e mobile;
- navegação por teclado, foco, semântica, contraste e ausência de overflow;
- bloqueio estrutural contra reintrodução de `apps/web` ou targets React.

Testes de plataforma adicionais serão incluídos quando Android, iOS ou desktop entrarem no escopo de distribuição.

## Contratos preservados

A implementação Flutter preserva:

- rotas `/`, `/componentes` e `/sistema`;
- shell responsivo;
- sidebar desktop e navegação móvel;
- estados de loading, vazio, erro e indisponibilidade;
- formulário demonstrativo com validação;
- health check com timeout e distinção entre operacional, degradado e indisponível;
- manifesto e instalação PWA;
- cache restrito ao shell;
- exclusão de `/api/` da política de cache;
- fallback de navegação sem transformar asset inexistente em HTML;
- runtime estático não privilegiado;
- acessibilidade e contraste já validados.

## Emenda de 2026-07-21

O plano original previa coexistência transitória e uma Fase D separada para remover React depois da validação do runtime Flutter. O mantenedor decidiu antecipar a consolidação durante a PR #37 porque:

- ainda não existem módulos financeiros produtivos dependentes do frontend antigo;
- manter dois clientes aumenta custo de CI, dependências e risco de divergência;
- o Flutter já cobre os contratos de shell necessários para continuar a evolução;
- rollback por tecnologia não é necessário nesta fase de fundação;
- Git preserva todo o histórico do shell anterior caso seja necessário consultar uma referência.

Com a emenda:

- `apps/web` é removido;
- React, React DOM, Vite, TypeScript, ESLint e lockfile npm deixam o repositório;
- o Dockerfile Web possui somente build e runtime Flutter;
- o Compose não seleciona target de frontend;
- os workflows não instalam nem auditam dependências npm do cliente;
- os runbooks tratam Flutter como único runtime;
- o quality gate rejeita a reintrodução acidental da árvore legada e de seus tokens operacionais.

## Alternativas consideradas

### Manter React para Web e Flutter apenas para mobile

Rejeitada. Criaria dois clientes, dois Design Systems, duplicação de testes e risco de regras divergentes.

### Manter React como rollback durante toda a fundação

Rejeitada pela emenda. Git já preserva a referência histórica e não há operação produtiva que justifique carregar permanentemente dependências, build e gates duplicados.

### Usar Flutter somente para Android

Rejeitada. Não aproveitaria a base compartilhada nem o padrão operacional já usado nos demais produtos.

## Consequências positivas

- uma única base de interface para múltiplas plataformas;
- alinhamento técnico com outros produtos Zemsoft;
- menor duplicação entre Web, PWA e aplicativos futuros;
- redução de dependências, superfície de ataque e tempo de CI;
- compartilhamento de componentes, navegação e testes;
- backend e domínio permanecem independentes da tecnologia do cliente.

## Consequências negativas e riscos

- não existe fallback executável para o shell anterior;
- CI e Docker exigem toolchain Flutter maior;
- tamanho inicial do artefato Web pode ser superior a um shell JavaScript mínimo;
- acessibilidade Web precisa de validação específica no Flutter;
- cache do runtime Flutter e arquivos WASM exige cuidado operacional;
- bibliotecas de plataforma podem variar entre Web, Android, iOS e desktop;
- persistência offline financeira continua sendo uma decisão separada.

O risco de ausência de rollback por tecnologia é aceito porque o produto está em fundação, sem dados financeiros reais ou usuários produtivos. Reversões de código continuam possíveis pelo histórico Git.

## Validação

A decisão está implementada quando:

- a base Flutter compila para Web;
- os contratos preservados possuem testes;
- o Compose serve exclusivamente o artefato Flutter;
- `/api/` permanece fora de caches de shell;
- desktop e mobile são inspecionados;
- Quality e Container Quality passam no HEAD final;
- `apps/web` e targets React não estão rastreados;
- nenhuma funcionalidade financeira foi perdida ou duplicada.

## Referências

- Issue #24
- Issue #36
- PR #21
- PR #37
- ADR-0001 — Aplicação local com interface PWA
- ADR-0007 — Shell Web, Design System mínimo e cache seguro
- `docs/runbooks/FLUTTER_CLIENT_MIGRATION.md`
