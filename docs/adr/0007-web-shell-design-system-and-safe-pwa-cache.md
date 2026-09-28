# ADR-0007 — Shell Web, design system mínimo e cache seguro da PWA

- Status: Superseded
- Data: 2026-07-19
- Decisores: mantenedores
- Superseded by: ADR-0008 — Flutter como cliente canônico multiplataforma

## Contexto

O ADR-0001 definiu React e TypeScript como cliente canônico, mas a interface provisória não estabelecia navegação, componentes, acessibilidade ou política concreta de cache. A fundação precisava permitir que módulos futuros fossem adicionados sem duplicar padrões e sem introduzir armazenamento offline acidental de dados financeiros.

Nesta fase existiam apenas três rotas estáticas e nenhuma autenticação. Adicionar uma biblioteca de roteamento ou um framework completo de componentes aumentaria dependências e superfície de atualização antes de haver necessidade funcional comprovada.

## Decisão histórica

O shell Web foi implementado como aplicação React responsiva com:

- navegação cliente mínima baseada na History API para as rotas estáticas da fundação;
- layout único para desktop e dispositivos móveis;
- tokens CSS para cor, tipografia, espaçamento, raio, sombra e foco;
- primitivas próprias e pequenas para botão, badge, campos e estados comuns;
- formulários acessíveis com validação explícita e mensagens associadas aos controles;
- integração degradável com `/api/v1/health/ready` usando `cache: no-store`;
- manifesto PWA e ícones `192x192` e `512x512`;
- service worker próprio, versionado, restrito a assets da interface.

O service worker ignorava toda requisição que:

- não fosse `GET`;
- fosse de outra origem;
- tivesse caminho iniciado por `/api/`;
- não fosse navegação ou um asset de interface reconhecido.

Navegações usavam estratégia network-first com fallback para o shell estático. Scripts, estilos, fontes e imagens usavam cache-first dentro de um cache identificado por versão.

O ADR-0008 substitui React por Flutter, mas preserva como requisitos obrigatórios os contratos de acessibilidade, health degradável, PWA, exclusão de `/api/` do cache, runtime estático e validação desktop/mobile.

## Alternativas consideradas historicamente

### React Router

Adiado. A fundação possuía poucas rotas estáticas e não exigia parâmetros, loaders ou rotas aninhadas.

### Biblioteca de componentes

Adiada. Os componentes necessários nessa fase eram pequenos e serviam principalmente para definir contratos visuais e acessíveis.

### Plugin PWA do Vite

Não adotado. Um service worker explícito tornava a exclusão de `/api/` auditável.

### Cache offline de respostas da API

Rejeitado. Dados financeiros, tokens e respostas operacionais exigem política própria de classificação, criptografia, expiração e revogação.

Essa rejeição continua vigente após a migração para Flutter.

## Consequências positivas históricas

- navegação e comportamento visual consistentes em desktop e celular;
- política de cache legível, testável e conservadora;
- falha da API não impede acesso à interface e à documentação visual;
- contratos executáveis para orientar a migração Flutter.

## Consequências negativas e riscos

- o shell React será transitório e precisará ser removido após a paridade Flutter;
- a política de cache precisa ser reinterpretada para os artefatos gerados pelo Flutter;
- instalação PWA varia por navegador;
- acessibilidade deve ser novamente validada na nova implementação.

## Validação histórica

- lint, typecheck, testes e build Vite;
- testes dos componentes básicos com renderização estática;
- teste estrutural do manifesto e da exclusão de `/api/` no service worker;
- smoke do Compose para shell, rota cliente, manifesto e service worker;
- inspeção manual em viewport desktop e móvel.

A PR #21 concluiu essa validação. O ADR-0008 exige que os mesmos contratos sejam reproduzidos antes da remoção do shell React.

## Referências

- ADR-0001 — Aplicação local com interface PWA
- ADR-0008 — Flutter como cliente canônico multiplataforma
- Issue #8
- Issue #24
- PR #21
