# Web

Shell React + TypeScript responsivo e instalável da fundação.

## Rotas

- `/`: página inicial de demonstração, sem dados financeiros reais;
- `/componentes`: documentação viva dos tokens, componentes, formulários e estados comuns;
- `/sistema`: health check da API, política offline e instalação PWA.

## Contratos

- chamadas HTTP permanecem sob `/api/v1`;
- readiness usa `cache: no-store` e falhas não bloqueiam a navegação;
- o service worker ignora explicitamente toda URL sob `/api/`;
- navegação por teclado, foco visível e mensagens de validação são requisitos obrigatórios;
- regras financeiras não devem existir exclusivamente no cliente.

## Runtime Docker

A imagem Web usa build multi-stage. O primeiro estágio executa `npm ci` e gera os assets compilados; o runtime contém apenas `dist/` e um servidor HTTP baseado em APIs nativas do Node.js. Rotas de navegação recebem fallback para `index.html`, enquanto assets inexistentes permanecem `404`.

Esse contrato é necessário para que o service worker encontre scripts e estilos sob `/assets/` e para que o comportamento offline do shell seja igual ao build validado pelo CI.

## Comandos

```bash
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Consulte `docs/runbooks/WEB_PWA.md` para instalação, diagnóstico e versionamento do cache.
