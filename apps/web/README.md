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

## Comandos

```bash
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Consulte `docs/runbooks/WEB_PWA.md` para instalação, diagnóstico e versionamento do cache.
