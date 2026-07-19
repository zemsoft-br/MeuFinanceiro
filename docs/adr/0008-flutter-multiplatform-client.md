# ADR-0008 — Flutter como cliente canônico multiplataforma

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores
- Supersede: ADR-0001 e ADR-0007 na escolha e implementação da tecnologia de interface

## Contexto

O MeuFinanceiro precisa oferecer uma única experiência em desktop e dispositivos móveis, preservar operação autohospedada e manter as regras financeiras fora do cliente.

O ADR-0001 escolheu React e TypeScript para a PWA. O ADR-0007 e a PR #21 concretizaram essa decisão com um shell responsivo, navegação acessível, health check degradável, manifesto, política conservadora de cache e runtime estático reproduzível.

Após essa validação, o mantenedor corrigiu a decisão de stack para alinhar o MeuFinanceiro aos demais produtos Zemsoft: a interface operacional deve usar Flutter. O objetivo é compartilhar uma única base entre Web/PWA e futuros alvos Android, iOS e desktop, em vez de manter um frontend React e outro cliente móvel.

A mudança não invalida os contratos funcionais comprovados pela PR #21. Ela substitui a tecnologia usada para implementá-los.

## Decisão

### Cliente canônico

1. Flutter será a tecnologia canônica do cliente.
2. Existirá uma única base de código Flutter para Web/PWA e futuros alvos Android, iOS e desktop.
3. Não será mantido um frontend React funcional em paralelo após a migração.
4. O código Flutter ficará em `apps/app`.
5. O serviço Docker e a rota pública poderão continuar chamados `web`, pois representam o artefato Web compilado, não a tecnologia-fonte.

### Arquitetura do cliente

A implementação inicial adotará:

- `go_router` para roteamento declarativo e deep links;
- Riverpod para estado, composição e injeção de dependências;
- clientes e DTOs separados dos modelos de apresentação;
- portas/adaptadores para persistência local e recursos de plataforma;
- internacionalização nativa do Flutter para `pt-BR`;
- tema e componentes próprios derivados do Design System do projeto;
- fontes, ícones e assets empacotados, sem CDN obrigatória.

Versões diretas serão fixadas no `pubspec.yaml` e inventariadas com licença antes do merge da implementação.

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

Os contratos de segurança da PR #21 são preservados:

- respostas e mutações sob `/api/` não podem ser armazenadas indiscriminadamente pelo service worker;
- tokens, health checks, saldos, movimentações, anexos e dados financeiros ficam fora do cache de shell;
- falha da API não impede a navegação para estados locais de diagnóstico;
- instalação PWA continua dependente do suporte do navegador e de contexto seguro.

O build Web Flutter deve tratar explicitamente:

- `index.html`;
- manifesto;
- service worker;
- `version.json`;
- `main.dart.js`;
- arquivos WASM usados pela aplicação;
- assets compilados e versionados.

Arquivos de entrada e runtime que podem mudar sem nome versionado devem ser servidos com revalidação ou `no-cache` conforme o contrato operacional. Somente assets efetivamente imutáveis podem receber cache longo.

A política deve ser validada por testes e inspeção de headers. Não se presume que o comportamento gerado pelo Flutter seja seguro sem auditoria.

### Qualidade

Os gates do cliente Flutter deverão incluir:

- `dart format --output=none --set-exit-if-changed`;
- `flutter analyze`;
- testes unitários;
- testes de widget;
- testes dos contratos de roteamento e health check;
- `flutter build web --release`;
- auditoria de dependências e licenças;
- smoke do artefato estático em Docker Compose;
- inspeção desktop e mobile;
- navegação por teclado, foco, semântica, contraste e ausência de overflow.

Testes de plataforma adicionais serão incluídos quando Android, iOS ou desktop entrarem no escopo de distribuição.

## Contratos preservados da PR #21

A migração deve reproduzir antes da remoção do React:

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
- proteção contra path traversal e métodos não suportados;
- acessibilidade e contraste já validados.

## Sequência de migração

1. Registrar esta decisão e o plano de migração.
2. Criar o scaffold Flutter em `apps/app` sem remover `apps/web`.
3. Portar rotas, shell, tokens, componentes, health check e PWA.
4. Atualizar quality gates para validar Flutter.
5. Atualizar Docker, Caddy e smoke tests para o build Flutter Web.
6. Validar paridade funcional, visual, acessível e operacional.
7. Remover React, Vite, Node runtime e arquivos legados do caminho ativo.
8. Atualizar inventários de dependências, runbooks e documentação final.

A coexistência durante a migração é transitória. Nenhuma funcionalidade financeira nova deve ser implementada no shell React.

## Alternativas consideradas

### Manter React para Web e Flutter apenas para mobile

Rejeitada. Criaria dois clientes, dois Design Systems, duplicação de testes e risco de regras divergentes.

### Manter React indefinidamente e postergar Flutter

Rejeitada. Aumentaria o custo de migração depois que telas funcionais fossem implementadas.

### Usar Flutter somente para Android

Rejeitada. Não aproveitaria a base compartilhada nem o padrão operacional já usado nos demais produtos.

### Remover o React imediatamente antes de portar os contratos

Rejeitada. Eliminaria uma referência executável já validada e aumentaria o risco de regressão.

## Consequências positivas

- uma única base de interface para múltiplas plataformas;
- alinhamento técnico com outros produtos Zemsoft;
- menor duplicação entre Web, PWA e aplicativos futuros;
- compartilhamento de componentes, navegação e testes;
- migração antecipada antes das funcionalidades financeiras;
- backend e domínio permanecem independentes da tecnologia do cliente.

## Consequências negativas e riscos

- o trabalho da PR #21 precisará ser portado e depois removido;
- CI e Docker exigirão toolchain Flutter maior;
- tamanho inicial do artefato Web pode aumentar;
- acessibilidade Web precisa de validação específica no Flutter;
- cache do runtime Flutter e arquivos WASM exige cuidado operacional;
- bibliotecas de plataforma podem variar entre Web, Android, iOS e desktop;
- persistência offline financeira continua sendo uma decisão separada.

## Validação

A decisão estará implementada quando:

- a base Flutter compilar para Web;
- os contratos preservados da PR #21 estiverem cobertos por testes;
- o Compose servir o artefato Flutter;
- `/api/` permanecer fora de caches de shell;
- desktop e mobile forem inspecionados;
- quality e container gates passarem;
- React não fizer parte do runtime ativo;
- nenhuma funcionalidade financeira tiver sido perdida ou duplicada.

## Referências

- Issue #24
- PR #21
- ADR-0001 — Aplicação local com interface PWA
- ADR-0007 — Shell Web, Design System mínimo e cache seguro
- `docs/runbooks/FLUTTER_CLIENT_MIGRATION.md`
