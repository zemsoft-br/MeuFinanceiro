# ADR-0007 — Shell Web, design system mínimo e cache seguro da PWA

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O ADR-0001 definiu React e TypeScript como cliente canônico, mas a interface provisória não estabelecia navegação, componentes, acessibilidade ou política concreta de cache. A fundação precisa permitir que módulos futuros sejam adicionados sem duplicar padrões e sem introduzir armazenamento offline acidental de dados financeiros.

Nesta fase existem apenas três rotas estáticas e nenhuma autenticação. Adicionar uma biblioteca de roteamento ou um framework completo de componentes aumentaria dependências e superfície de atualização antes de haver necessidade funcional comprovada.

## Decisão

O shell Web será uma aplicação React responsiva com:

- navegação cliente mínima baseada na History API para as rotas estáticas da fundação;
- layout único para desktop e dispositivos móveis;
- tokens CSS para cor, tipografia, espaçamento, raio, sombra e foco;
- primitivas próprias e pequenas para botão, badge, campos e estados comuns;
- formulários acessíveis com validação explícita e mensagens associadas aos controles;
- integração degradável com `/api/v1/health/ready` usando `cache: no-store`;
- manifesto PWA e ícones `192x192` e `512x512`;
- service worker próprio, versionado, restrito a assets da interface.

O service worker deve ignorar toda requisição que:

- não seja `GET`;
- seja de outra origem;
- tenha caminho iniciado por `/api/`;
- não seja navegação ou um asset de interface reconhecido.

Navegações usam estratégia network-first com fallback para o shell estático. Scripts, estilos, fontes e imagens usam cache-first dentro de um cache identificado por versão. Uma nova versão deve alterar o nome do cache e remover versões anteriores no evento `activate`.

## Alternativas consideradas

### React Router

Adiado. A fundação possui poucas rotas estáticas e não exige parâmetros, loaders ou rotas aninhadas. A adoção poderá ocorrer quando o domínio justificar o custo adicional.

### Biblioteca de componentes

Adiada. Os componentes necessários nesta fase são pequenos e servem principalmente para definir contratos visuais e acessíveis. Não há identidade visual definitiva.

### Plugin PWA do Vite

Não adotado nesta fase. Um service worker explícito torna a exclusão de `/api/` auditável sem depender de geração indireta ou configuração adicional.

### Cache offline de respostas da API

Rejeitado. Dados financeiros, tokens e respostas operacionais exigem uma política própria de classificação, criptografia, expiração e revogação que ainda não foi especificada.

## Consequências positivas

- navegação e comportamento visual consistentes em desktop e celular;
- dependências diretas permanecem reduzidas;
- política de cache legível, testável e conservadora;
- falha da API não impede acesso à interface e à documentação visual;
- componentes básicos podem ser evoluídos ou substituídos sem alterar contratos do backend.

## Consequências negativas e riscos

- o roteador mínimo não cobre rotas dinâmicas ou aninhadas;
- manutenção manual do service worker exige incrementar sua versão quando a estratégia mudar;
- a aparência é uma fundação funcional, não a identidade visual definitiva;
- instalação PWA e o evento `beforeinstallprompt` variam por navegador.

## Validação

- lint, typecheck, testes e build Vite;
- testes dos componentes básicos com renderização estática;
- teste estrutural do manifesto e da exclusão de `/api/` no service worker;
- smoke test do Compose para shell, rota cliente, manifesto e service worker;
- inspeção manual em viewport desktop e móvel antes do merge.

## Referências

- ADR-0001 — Aplicação local com interface PWA
- Issue #8 — Criar shell Web/PWA e design system inicial
