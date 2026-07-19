# Shell Web/PWA

Este runbook descreve desenvolvimento, validação, instalação e limites offline da interface do MeuFinanceiro.

## Endereços locais

Com o ambiente iniciado por `./infra/scripts/dev-up.sh` ou `./infra/scripts/dev-up.ps1`:

- aplicação: `http://127.0.0.1:8080`;
- componentes: `http://127.0.0.1:8080/componentes`;
- diagnóstico: `http://127.0.0.1:8080/sistema`;
- documentação da API: `http://127.0.0.1:8080/api/v1/docs`.

## Desenvolvimento isolado

Dentro de `apps/web`:

```bash
npm ci
npm run dev
```

O servidor Vite usa a porta `5173`. A integração completa com `/api/v1` deve ser validada pelo Docker Compose, pois o Caddy é responsável pela entrada HTTP unificada.

## Validação

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

A suíte inclui:

- normalização de rotas;
- parsing defensivo do health check;
- validação-base de formulários;
- renderização estática dos componentes básicos;
- contrato do manifesto;
- exclusão explícita de `/api/` no service worker.

A integração completa é validada por:

```bash
bash tests/smoke/compose-smoke.sh
```

## Instalação

### Chrome, Edge e navegadores Chromium

1. Abra a aplicação pelo endereço HTTP local suportado ou por HTTPS no acesso remoto configurado.
2. Abra a página **Sistema**.
3. Use o botão **Instalar aplicativo** quando ele estiver disponível.
4. Alternativamente, use a ação **Instalar MeuFinanceiro** no menu do navegador.

`localhost` e `127.0.0.1` são contextos seguros aceitos pelos navegadores. Para outro dispositivo na rede ou via Tailscale, a instalação do service worker pode exigir HTTPS conforme a política do navegador.

### Safari no iPhone ou iPad

1. Abra a aplicação no Safari.
2. Use **Compartilhar**.
3. Escolha **Adicionar à Tela de Início**.

O evento de instalação programática não é uniforme no Safari; por isso a interface também apresenta instruções textuais.

## Política de cache

O cache atual é exclusivamente de shell:

- HTML estático da aplicação;
- manifesto;
- service worker;
- scripts e estilos compilados;
- fontes e imagens da própria interface;
- ícones da PWA.

O service worker não intercepta URLs sob `/api/`. Portanto, não armazena:

- tokens;
- respostas de health check;
- cadastros;
- lançamentos;
- saldos;
- anexos;
- qualquer futuro dado financeiro retornado pela API.

Não altere essa regra sem uma issue própria, análise de segurança e novo ADR.

## Versionamento do cache

O nome atual é definido em `apps/web/public/sw.js`:

```text
meufinanceiro-shell-v1
```

Ao alterar a lista de precache ou a estratégia de cache, incremente a versão. O evento `activate` remove caches anteriores com o prefixo `meufinanceiro-shell-`.

## Diagnóstico

No DevTools do navegador:

1. abra **Application**;
2. verifique **Manifest** e os ícones;
3. verifique **Service Workers**;
4. em **Cache Storage**, confirme apenas o cache `meufinanceiro-shell-*`;
5. em **Network**, confirme que requisições `/api/` não têm origem `ServiceWorker`.

Para remover o estado local de teste, use **Clear site data** no DevTools. Isso não remove o banco PostgreSQL do Docker Compose.
