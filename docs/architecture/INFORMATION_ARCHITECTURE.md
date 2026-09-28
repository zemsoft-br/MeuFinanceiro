# Arquitetura de informação canônica

- Issue: #22
- Dependência: ADR-0008 aceito em `develop`
- Fonte visual: `docs/design/STITCH_SCREEN_INVENTORY.csv`

## 1. Princípios

1. Existe uma única aplicação Flutter e um único shell funcional.
2. Web/PWA é o primeiro alvo operacional; futuros Android, iOS e desktop reutilizam os mesmos contratos de produto.
3. Estados vazio, erro, carregamento, indisponibilidade e demonstração não são rotas próprias.
4. Desktop e mobile usam as mesmas rotas e contratos, com composição responsiva.
5. Detalhes usam rotas parametrizadas ou painéis vinculados à rota.
6. Filtros relevantes devem ser serializáveis na URL no alvo Web, quando não forem sensíveis.
7. O cliente não mantém regras financeiras exclusivas.
8. Pluggy e arquivos convergem para Importações e Conciliação.
9. Administração, patrimônio e dívidas usam o mesmo shell e Design System.
10. A navegação deve respeitar papéis, escopos e disponibilidade de módulos.
11. Ocultar um item de menu não substitui autorização no backend.
12. `go_router`, definido no ADR-0008, é a implementação canônica de rotas e deep links.

## 2. Navegação principal

### Início

- Dashboard

### Financeiro

- Movimentações
- Contas
- Cartões e Faturas

### Planejamento

- Orçamentos
- Recorrências e Assinaturas
- Metas e Projetos
- Fluxo de Caixa

### Análise

- Relatórios
- Alertas e Notificações

### Importação

- Importações
- Conciliação
- Integração Pluggy

### Patrimônio

- Visão Patrimonial
- Bens e Direitos
- Investimentos
- Empréstimos e Financiamentos

### Administração

- Visão Geral
- Backups
- Segurança e Acessos
- Privacidade e Segredos
- Diagnóstico
- Manutenção e Auditoria

## 3. Rotas públicas

| Rota | Finalidade |
|---|---|
| `/login` | autenticação local e recuperação permitida |
| `/onboarding` | fluxo persistente de primeira configuração |
| `/modo-demonstracao` | entrada explícita no modo demonstrativo, se adotada |

## 4. Rotas autenticadas

### 4.1 Núcleo

| Rota | Experiência |
|---|---|
| `/app` | Dashboard canônico |
| `/app/movimentacoes` | livro financeiro e filtros |
| `/app/movimentacoes/:movementId` | detalhe rastreável |
| `/app/contas` | contas e saldos |
| `/app/contas/:accountId` | detalhe da conta |
| `/app/cartoes` | cartões e faturas |
| `/app/cartoes/:cardId` | cartão |
| `/app/cartoes/:cardId/faturas/:statementId` | fatura |

### 4.2 Planejamento

| Rota | Experiência |
|---|---|
| `/app/planejamento/orcamentos` | orçamento, envelopes e base zero |
| `/app/planejamento/recorrencias` | recorrências e assinaturas |
| `/app/planejamento/metas-projetos` | objetivos, metas e projetos |
| `/app/planejamento/fluxo-caixa` | visão geral |
| `/app/planejamento/fluxo-caixa/projecao` | projeção detalhada |
| `/app/planejamento/fluxo-caixa/calendario` | calendário e agenda |
| `/app/planejamento/fluxo-caixa/cenarios` | cenários |

### 4.3 Análise

| Rota | Experiência |
|---|---|
| `/app/analise/relatorios` | visão geral |
| `/app/analise/relatorios/receitas-despesas` | receitas e despesas |
| `/app/analise/relatorios/orcamento` | orçamento e planejamento |
| `/app/analise/relatorios/compromissos` | compromissos |
| `/app/analise/relatorios/personalizado` | construtor e exportação |
| `/app/alertas` | central |
| `/app/alertas/regras` | regras |
| `/app/alertas/preferencias` | preferências pessoais |
| `/app/alertas/historico` | entregas |

### 4.4 Importação e integração

| Rota | Experiência |
|---|---|
| `/app/importacoes` | central |
| `/app/importacoes/nova` | assistente |
| `/app/importacoes/lotes/:batchId` | revisão do lote |
| `/app/importacoes/regras` | regras |
| `/app/importacoes/historico` | auditoria |
| `/app/conciliacao` | caixa canônica |
| `/app/integracoes/pluggy` | visão geral do provedor |
| `/app/integracoes/pluggy/configuracao` | configuração administrativa |
| `/app/integracoes/pluggy/conectar` | assistente |
| `/app/integracoes/pluggy/conexoes/:connectionId` | conexão |
| `/app/integracoes/pluggy/conexoes/:connectionId/mapeamento` | produtos externos |
| `/app/integracoes/pluggy/saude` | diagnóstico |
| `/app/importacoes?source=pluggy` | dados recebidos, filtrados |

### 4.5 Patrimônio e dívidas

| Rota | Experiência |
|---|---|
| `/app/patrimonio` | visão consolidada |
| `/app/patrimonio/bens` | bens e direitos |
| `/app/patrimonio/investimentos` | carteira |
| `/app/patrimonio/ativos/:assetId` | detalhe do ativo |
| `/app/patrimonio/eventos` | eventos patrimoniais |
| `/app/patrimonio/evolucao` | evolução e cenários |
| `/app/patrimonio/auditoria` | documentos e avaliações |
| `/app/patrimonio/dividas` | empréstimos e financiamentos |
| `/app/patrimonio/dividas/nova` | cadastro |
| `/app/patrimonio/dividas/:contractId` | contrato |
| `/app/patrimonio/dividas/:contractId/parcelas` | parcelas |
| `/app/patrimonio/dividas/:contractId/cenarios` | amortização e quitação |
| `/app/patrimonio/dividas/:contractId/historico` | documentos e auditoria |

### 4.6 Administração

| Rota | Experiência |
|---|---|
| `/app/admin` | saúde administrativa |
| `/app/admin/backups` | backups e retenção |
| `/app/admin/backups/restaurar` | restauração |
| `/app/admin/seguranca` | usuários e sessões |
| `/app/admin/privacidade-segredos` | privacidade e segredos |
| `/app/admin/diagnostico` | saúde e pacote técnico |
| `/app/admin/manutencao` | atualização, migração e auditoria |

## 5. Contrato multiplataforma

As rotas acima são contratos canônicos de navegação e deep link.

- Web/PWA usa os caminhos literalmente na URL.
- Android, iOS e desktop reutilizam os mesmos nomes de rota e parâmetros, mesmo quando o sistema operacional não expõe a URL completa.
- Links externos ou notificações devem resolver para a mesma experiência autorizada.
- Uma plataforma sem suporte a uma capacidade apresenta estado indisponível explícito, não outro fluxo financeiro.
- Histórico do navegador, botão voltar e restauração de estado precisam ser testados no Web.

## 6. Estado de rota

Filtros devem usar query string quando forem compartilháveis e não sensíveis:

- período;
- competência;
- conta;
- cartão;
- categoria;
- situação;
- origem;
- lote;
- confiança.

Não colocar na URL:

- segredos;
- tokens;
- valores mascarados reversíveis;
- documentos;
- payloads externos;
- dados privados sem necessidade.

No Flutter, parsing, validação e serialização de parâmetros ficam centralizados na camada de roteamento. Widgets não devem interpretar parâmetros financeiros de forma divergente.

## 7. Componentes estruturais

- `AppShell`;
- `SideNavigation`;
- `TopNavigation`;
- `MobileBottomNavigation`;
- `PageHeader`;
- `Breadcrumbs`;
- `ResidenceSelector`;
- `ScopeSelector`;
- `MemberSelector`;
- `PeriodSelector`;
- `FilterBar`;
- `AdvancedFilterDrawer`;
- `Dialog`;
- `SidePanel`;
- `Drawer`;
- `BottomSheet`;
- `DenseDataTable`;
- `ResponsiveCardList`;
- estados comuns.

Esses nomes representam contratos de componente, não classes obrigatórias. Componentes específicos de domínio devem compor essas primitivas, não criar outro shell.

## 8. Critérios de aceite para rotas

Cada rota funcional deve provar:

- autorização no backend;
- deep link válido no Web e contrato equivalente nos demais alvos ativos;
- estado de carregamento;
- estado vazio;
- erro recuperável;
- API indisponível;
- permissão negada;
- navegação por teclado no Web;
- semântica acessível do Flutter exposta corretamente à plataforma;
- comportamento mobile e desktop;
- restauração de estado quando aplicável;
- ausência de regra financeira somente no cliente.

As rotas deste documento orientam a implementação com `go_router`, mas não substituem issues pequenas, testes e contratos de autorização.
