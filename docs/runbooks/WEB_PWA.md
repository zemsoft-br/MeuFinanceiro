# Shell Web/PWA atual e transição Flutter

Este runbook descreve o shell Web/PWA atualmente integrado e seus contratos operacionais.

> **Estado transitório:** `apps/web` ainda usa React/Vite porque a PR #21 foi integrada antes da decisão do ADR-0008. Flutter é o cliente canônico. Nenhuma funcionalidade financeira nova deve ser implementada no shell React.

A sequência de substituição está em [FLUTTER_CLIENT_MIGRATION.md](FLUTTER_CLIENT_MIGRATION.md).

## Endereços locais

Com o ambiente iniciado por `./infra/scripts/dev-up.sh` ou `./infra/scripts/dev-up.ps1`:

- aplicação: `http://127.0.0.1:8080`;
- componentes: `http://127.0.0.1:8080/componentes`;
- diagnóstico: `http://127.0.0.1:8080/sistema`;
- documentação da API: `http://127.0.0.1:8080/api/v1/docs`.

Essas rotas são contratos de paridade da migração Flutter.

## Desenvolvimento do shell transitório

Dentro de `apps/web`:

```bash
npm ci
npm run dev
```

O servidor Vite usa a porta `5173`. A integração completa com `/api/v1` deve ser validada pelo Docker Compose, pois o Caddy é responsável pela entrada HTTP unificada.

Esses comandos permanecem disponíveis apenas para manutenção e comparação durante a migração. Não adicione módulos de negócio ao frontend antigo.

## Validação atual

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

A implementação Flutter deverá reproduzir esses contratos com `dart format`, `flutter analyze`, testes Flutter, build Web release e o mesmo smoke operacional antes da remoção do React.

## Instalação atual

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

A migração Flutter deve preservar instruções manuais quando o navegador não oferecer evento programático.

## Política de cache obrigatória

O cache é exclusivamente de shell:

- HTML estático da aplicação;
- manifesto;
- service worker;
- scripts e estilos compilados;
- fontes e imagens da própria interface;
- ícones da PWA.

O service worker não pode interceptar ou armazenar respostas sob `/api/`, incluindo:

- tokens;
- respostas de health check;
- cadastros;
- lançamentos;
- saldos;
- anexos;
- qualquer futuro dado financeiro retornado pela API.

Não altere essa regra sem issue própria, análise de segurança e novo ADR.

## Cache do shell React atual

O nome atual é definido em `apps/web/public/sw.js`:

```text
meufinanceiro-shell-v1
```

Ao alterar a lista de precache ou a estratégia de cache durante a fase transitória, incremente a versão. O evento `activate` remove caches anteriores com o prefixo `meufinanceiro-shell-`.

## Cache alvo do Flutter

A migração deve revisar os artefatos reais gerados pelo Flutter e definir headers para:

- `index.html`;
- `flutter_service_worker.js` ou equivalente;
- manifesto;
- `version.json`;
- `main.dart.js`;
- arquivos WASM;
- assets com e sem nome versionado.

Requisitos:

- `main.dart.js`, arquivos de bootstrap e WASM não podem ficar presos indefinidamente em cache antigo;
- somente assets comprovadamente imutáveis recebem cache longo;
- `/api/` permanece fora do cache de shell;
- upgrade entre versões deve ser testado;
- nenhuma fonte, script ou ícone depende de CDN obrigatória.

## Diagnóstico atual

No DevTools do navegador:

1. abra **Application**;
2. verifique **Manifest** e os ícones;
3. verifique **Service Workers**;
4. em **Cache Storage**, confirme apenas o cache de shell esperado;
5. em **Network**, confirme que requisições `/api/` não têm origem `ServiceWorker`;
6. confirme os headers de `index.html`, JavaScript principal e arquivos WASM existentes.

Para remover o estado local de teste, use **Clear site data** no DevTools. Isso não remove o banco PostgreSQL do Docker Compose.

## Critério para encerrar este runbook transitório

Este documento poderá ser substituído por um runbook Flutter definitivo somente quando:

- as três rotas estiverem portadas;
- PWA e cache estiverem validados;
- quality e container gates passarem;
- a remoção do React estiver concluída;
- o runtime ativo servir exclusivamente o artefato Flutter Web.
