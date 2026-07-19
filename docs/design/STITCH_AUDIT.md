# Auditoria dos protótipos Google Stitch

- Data da auditoria: 2026-07-19
- Fonte: exportação `stitch_meufinanceiro_core_foundation(10).zip`
- Issue: #22
- Estado: referência aprovada para planejamento; não é código-fonte

## 1. Objetivo

Transformar os protótipos do Google Stitch em uma referência controlada para implementação, sem reproduzir:

- telas duplicadas;
- rotas paralelas;
- shells concorrentes;
- três sistemas visuais independentes;
- dados fictícios contraditórios;
- dependências de CDN incompatíveis com operação local;
- regras financeiras apenas aparentes;
- afirmações de segurança não comprovadas.

Esta auditoria complementa `docs/PRODUCT_SPECIFICATION.md`, `docs/ARCHITECTURE.md` e `docs/ROADMAP.md`. Em caso de conflito, ADRs aceitos e contratos executáveis do repositório prevalecem.

## 2. Evidências

A exportação contém:

- 68 diretórios;
- 65 telas HTML;
- 3 documentos de Design System;
- 62 capturas PNG utilizáveis;
- 2 capturas inválidas;
- 1 tela sem captura;
- 1 duplicata HTML exata.

Limitações observadas nos 65 HTMLs:

- 65 carregam Tailwind por CDN;
- 65 dependem de Google Fonts;
- 47 dependem de imagens em domínio externo;
- 54 não possuem atributos `aria-*`;
- 61 não possuem elemento `<form>`;
- a maioria das interações é apenas visual;
- gráficos, filtros, SidePanels, permissões e cálculos não são funcionais.

## 3. Decisão de uso

Os artefatos do Stitch são referências para:

- cobertura funcional;
- hierarquia visual;
- densidade de informação;
- estados de tela;
- comportamento responsivo;
- terminologia de interface;
- exemplos de drill-down.

Eles não podem ser usados como:

- código-fonte Flutter, Dart, React ou HTML produtivo;
- fonte automática de rotas;
- implementação de regra financeira;
- prova de acessibilidade;
- prova de segurança;
- prova de processamento local;
- prova de integração;
- fonte de dados demonstrativos.

Nenhum HTML ou asset externo deve ser copiado diretamente para `apps/app` ou para o shell React transitório.

## 4. Classificação dos artefatos

O inventário completo está em `STITCH_SCREEN_INVENTORY.csv`.

Categorias utilizadas:

- `CANÔNICA`: principal referência visual de uma experiência;
- `CANÔNICA HTML`: HTML utilizável quando a captura é inválida;
- `CANÔNICA COM REBRANDING`: referência funcional que precisa adotar o shell e a marca MeuFinanceiro;
- `CANÔNICA COM SHELL UNIFICADO`: referência de módulo criada com outro shell;
- `REFERÊNCIA DE ESTADO`: estado condicional, não rota;
- `REFERÊNCIA RESPONSIVA`: referência mobile, não aplicação separada;
- `FONTE DE TOKENS SEMÂNTICOS`: fonte parcial, não outro Design System;
- `DESCARTAR`: duplicata ou versão anterior.

## 5. Consolidações obrigatórias

### 5.1 Login

- Referência: `login_meufinanceiro`.
- Descartar `meufinanceiro_app`, duplicata HTML exata.

### 5.2 Onboarding

Uma única rota `/onboarding` com etapas condicionais.

As telas individuais de boas-vindas, administrador, residência e conclusão são referências de etapas, não rotas independentes.

### 5.3 Dashboard

Uma única rota `/app`.

Referências:

- `dashboard_meufinanceiro_consolidado`: composição principal;
- `dashboard_meufinanceiro`: widgets do estado com dados;
- `dashboard_estado_inicial_meufinanceiro`: estado vazio.

### 5.4 Metas e projetos

Usar `projetos_objetivos_e_metas_meufinanceiro_2`.

A versão `_1` pode fornecer ideias pontuais, mas não deve gerar tela ou rota paralela.

### 5.5 Mobile

As referências mobile de Importações e Administração representam breakpoints e prioridades de composição. Não devem criar outro frontend, outro domínio ou rotas próprias.

### 5.6 Pluggy

A caixa Pluggy é filtro/origem da caixa canônica de Importações e Conciliação. Não é outro ledger.

### 5.7 Administração, empréstimos e patrimônio

Esses módulos devem usar o mesmo `AppShell`, navegação, tokens, tipografia, componentes e autorização do núcleo familiar.

## 6. Design System

Base visual recomendada: `serene_finance_1`.

Motivos:

- Inter como referência tipográfica principal;
- valores tabulares compatíveis com JetBrains Mono ou números tabulares;
- densidade adequada a tabelas financeiras;
- escala de espaçamento baseada em 4 px;
- proximidade com as telas centrais do produto.

`serene_finance_2` e `serene_finance_core` fornecem somente semântica especializada de dívidas, parcelas, investimentos, maturidade e valorização. Não são temas independentes.

Identidades que devem ser removidas:

- FinanCorp;
- Premium Plan;
- Investidor Premium;
- Loan Management;
- Serene Finance como marca visível de módulo.

No Flutter, tokens serão implementados por tema e componentes próprios. Fontes, ícones e assets precisam ser empacotados e licenciados; a referência a Inter ou JetBrains Mono não autoriza carregamento por CDN.

## 7. Dependências externas

A aplicação deve funcionar sem:

- `cdn.tailwindcss.com`;
- `fonts.googleapis.com`;
- `fonts.gstatic.com`;
- imagens remotas do protótipo.

Requisitos:

- estilos e componentes reconstruídos em Flutter;
- fontes e ícones controlados pela instalação;
- assets versionados e licenciados;
- nenhuma chamada externa não documentada;
- políticas de cache compatíveis com o ADR-0008;
- integrações externas explicitamente opcionais.

## 8. Acessibilidade

A implementação Flutter deve possuir:

- árvore semântica coerente e exposta à plataforma;
- landmarks ou regiões navegáveis equivalentes no Web;
- tabs com papéis, seleção e relação de painel acessíveis;
- Dialogs e overlays com foco contido e retorno de foco;
- campos com labels, instruções e erros associados;
- tabelas ou grades com cabeçalhos e leitura coerente;
- progressos com valor acessível;
- botões de ícone com nome;
- gráficos com legenda e resumo textual;
- estados que não dependem apenas de cor;
- navegação completa por teclado no Web;
- contraste WCAG AA;
- suporte a escalonamento de texto;
- testes automatizados e inspeção manual.

A aparência do protótipo e a existência de um widget `Semantics` não comprovam conformidade por si sós.

## 9. Responsividade

Existe uma única base Flutter.

Padrão:

- desktop: tabelas densas, filtros amplos e SidePanels;
- tablet: redução de colunas, drawers e reorganização;
- mobile: cards, listas, bottom sheets e ações prioritárias.

Operações volumosas podem recomendar desktop, mas não devem criar outro produto.

Os mesmos contratos devem funcionar no Flutter Web/PWA e ser reutilizáveis pelos futuros alvos Android, iOS e desktop.

## 10. Mocks e inconsistências

Foram encontrados:

- personagens diferentes;
- marcas externas ao produto;
- datas entre 2023 e 2025;
- salário de R$ 7.500,00 e R$ 8.500,00 sem contexto;
- aluguel de R$ 2.800,00 e R$ 3.500,00;
- Spotify de R$ 34,90 e R$ 55,90;
- contratos cuja soma não fecha com o saldo devedor total;
- composição patrimonial incompleta;
- percentuais de gráfico digitados manualmente e incompatíveis com os valores.

A fixture canônica está especificada em `docs/architecture/DEMO_DATA_CONTRACT.md`.

## 11. Resultado

Os protótipos cobrem suficientemente o produto para encerrar a prototipação ampla.

A partir desta decisão:

1. novas telas só devem ser prototipadas quando uma issue funcional identificar lacuna concreta;
2. rotas e componentes são definidos pelo repositório e implementados em Flutter;
3. regras financeiras vivem no domínio/backend e são protegidas por testes;
4. dados de demonstração vêm de fixture central;
5. Stitch permanece referência visual versionada, não autoridade arquitetural;
6. o shell React transitório não recebe funcionalidades financeiras e será removido após a paridade Flutter.
