# ADR-0011 — Fixtures demonstrativas determinísticas e relógio de referência

- Status: Proposed
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O modo demonstração será utilizado por colaboradores, revisores, documentação e testes. Os protótipos apresentam pessoas, datas e valores contraditórios. Duplicar mocks em widgets ou serviços produziria telas matematicamente incompatíveis e testes dependentes do relógio real.

A issue #9 exige dados inteiramente fictícios e reproduzíveis.

## Decisão

1. Existirá uma fixture central da `Residência Ipê`.
2. Nenhum dado real do mantenedor, cliente ou instituição será usado.
3. Entidades terão identificadores estáveis.
4. Totais e percentuais serão derivados.
5. A fixture possuirá data e fuso de referência.
6. Serviços, backend e testes Flutter usarão relógio injetável.
7. Estados vazios e erros serão variantes explícitas, não edições manuais do dataset.
8. Modo demonstração será isolado de residências reais.
9. Reset será determinístico.
10. Assets e documentos fictícios terão origem e licença verificáveis.

O contrato inicial está em `docs/architecture/DEMO_DATA_CONTRACT.md`.

## Alternativas consideradas

### Mocks locais em cada tela

Rejeitada por divergência matemática e manutenção duplicada.

### Datas relativas ao relógio do dispositivo

Rejeitada por testes instáveis, competências variáveis e diferenças entre Web, mobile e desktop.

### Cópia de dados reais anonimizados

Rejeitada. Dados financeiros reais podem permanecer reidentificáveis e não são necessários.

### Gerar valores aleatórios em cada execução

Rejeitada como padrão. Pode existir teste generativo separado, mas a demonstração precisa ser reproduzível.

## Consequências positivas

- telas coerentes;
- testes determinísticos;
- documentação reproduzível;
- regressão visual confiável;
- nenhuma dependência de dados pessoais;
- facilitação de reset e suporte;
- mesmos resultados em Flutter Web, mobile, desktop e backend.

## Consequências negativas e riscos

- fixture central pode crescer;
- mudanças exigem revisão de snapshots e documentação;
- documentos fictícios precisam de manutenção;
- isolamento do modo demonstração deve ser comprovado;
- serialização entre API e Dart deve preservar valores e datas.

## Validação

A issue #9 deverá provar:

- seed idempotente;
- reset;
- relógio injetável;
- isolamento;
- saldos reconciliados;
- faturas fechadas;
- transferências neutras;
- metas sem dupla destinação;
- passivos e patrimônio conciliados;
- ausência de dados reais e segredos;
- apresentação idêntica dos totais entre API e cliente Flutter.

## Referências

- ADR-0008 — Flutter como cliente canônico multiplataforma
- Issue #9
- `docs/architecture/DEMO_DATA_CONTRACT.md`
- `docs/design/STITCH_AUDIT.md`
- Issue #22
