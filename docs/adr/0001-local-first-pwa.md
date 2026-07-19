# ADR-0001 — Aplicação local com interface PWA

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O produto deve ser autohospedado, simples de instalar, utilizável em computador e celular e capaz de operar sem internet nas funções não integradas.

As alternativas principais eram aplicação desktop nativa, aplicação móvel nativa ou aplicação web local.

## Decisão

O cliente canônico será uma PWA em React e TypeScript, servida localmente e conectada a uma API FastAPI. A distribuição principal será Docker Compose. Um instalador/gerenciador poderá automatizar a operação dos containers, mas não criará um segundo cliente funcional.

Tailscale será a recomendação inicial para acesso remoto.

## Alternativas consideradas

### Aplicativo desktop como cliente principal

Rejeitado na fundação por aumentar o número de superfícies, empacotamento e atualização sem benefício suficiente ao domínio.

### Flutter nativo ou multiplataforma

Rejeitado no escopo inicial porque exigiria manter outro cliente e contratos de sincronização mais complexos.

### SaaS centralizado

Rejeitado por conflitar com o objetivo de autohospedagem e controle dos dados.

## Consequências positivas

- uma interface para desktop e dispositivos móveis;
- instalação PWA sem loja;
- backend e banco permanecem locais;
- menor custo de manutenção;
- instalador pode evoluir sem duplicar regras de negócio.

## Consequências negativas e riscos

- o host precisa permanecer ligado;
- capacidades PWA variam por navegador e sistema;
- notificações móveis podem depender de internet e suporte do navegador;
- acesso remoto exige configuração de rede segura.

## Validação

A fundação deve comprovar execução local, instalação PWA e acesso pela rede/Tailscale antes da primeira versão pública.
