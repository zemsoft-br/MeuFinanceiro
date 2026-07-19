# ADR-0001 — Aplicação local com interface PWA

- Status: Superseded
- Data: 2026-07-19
- Decisores: mantenedores
- Superseded by: ADR-0008 — Flutter como cliente canônico multiplataforma

## Contexto

O produto deve ser autohospedado, simples de instalar, utilizável em computador e celular e capaz de operar sem internet nas funções não integradas.

As alternativas principais eram aplicação desktop nativa, aplicação móvel nativa ou aplicação web local.

## Decisão histórica

O cliente canônico seria uma PWA em React e TypeScript, servida localmente e conectada a uma API FastAPI. A distribuição principal seria Docker Compose. Um instalador/gerenciador poderia automatizar a operação dos containers, mas não criaria um segundo cliente funcional.

Tailscale seria a recomendação inicial para acesso remoto.

A escolha de React foi substituída pelo ADR-0008. Permanecem válidos os objetivos de autohospedagem, interface única, PWA, FastAPI, Docker Compose e acesso remoto seguro.

## Alternativas consideradas

### Aplicativo desktop como cliente principal

Rejeitado na fundação por aumentar o número de superfícies, empacotamento e atualização sem benefício suficiente ao domínio.

### Flutter nativo ou multiplataforma

Rejeitado no escopo inicial porque exigiria manter outro cliente e contratos de sincronização mais complexos.

Essa avaliação foi revista no ADR-0008: Flutter passa a ser a única base de cliente, e não um segundo cliente concorrente.

### SaaS centralizado

Rejeitado por conflitar com o objetivo de autohospedagem e controle dos dados.

## Consequências positivas históricas

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

A fundação deveria comprovar execução local, instalação PWA e acesso pela rede/Tailscale antes da primeira versão pública.

Esses contratos continuam aplicáveis sob o ADR-0008.
