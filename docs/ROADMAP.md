# Roadmap — MeuFinanceiro

## Estratégia

O produto será construído em camadas. Issues devem ser pequenas, testáveis e preferencialmente independentes; epics organizam o trabalho, mas não devem ser implementadas em uma única Pull Request.

O ADR-0008 define Flutter como cliente único. `apps/app` é a base canônica para Web/PWA e futuros alvos Android, iOS e desktop. Um segundo frontend exige novo ADR.

## Fase 0 — Fundação do projeto

**Objetivo:** tornar o repositório seguro e previsível para colaboração e operação local.

Entregas:

- visão, limites e especificação do produto;
- arquitetura inicial e ADRs;
- Gitflow, templates e DCO;
- licença, marca, governança e política de segurança;
- monorepo e ambiente Docker Compose;
- configuração segura, keyring e segredos por instalação;
- PostgreSQL, Alembic, health checks, worker e fila persistente;
- quality gates locais e GitHub Actions;
- dados de demonstração determinísticos, sem informações reais;
- cliente Flutter Web/PWA responsivo;
- build Web reproduzível, sem CDN obrigatória;
- manifesto e service worker próprios;
- política de cache auditada;
- runtime estático Caddy não-root;
- remoção integral de React, Vite, TypeScript e runtime Node do frontend.

Critério de saída:

- novo colaborador consegue executar o projeto localmente;
- PR de exemplo passa pelos quality gates;
- nenhum segredo é necessário para o modo de demonstração;
- Flutter é o único cliente rastreado e operacional;
- rotas, acessibilidade, health check e PWA possuem validação automatizada;
- artefato servido pelo container é inspecionado;
- nenhum dado financeiro real é necessário nos testes.

### Consolidação Flutter

1. decisão e scaffold Flutter;
2. toolchain e quality gates;
3. paridade do shell e rotas essenciais;
4. runtime Web/PWA no Compose;
5. cache, headers, smoke e restart;
6. remoção do frontend anterior e bloqueio contra reintrodução.

## Fase 1 — Identidade, residência e núcleo financeiro

**Objetivo:** estabelecer os contratos de autorização e o livro financeiro.

Pré-requisito: Fase 0 validada e integrada.

Entregas:

- autenticação local e sessões revogáveis;
- residência, membros e papéis simplificados;
- escopo pessoal, compartilhado e familiar;
- contas financeiras e tipos personalizados;
- movimentações, transferências e rateios;
- datas de caixa e competência;
- auditoria;
- testes determinísticos de dinheiro e autorização.

Critério de saída:

- uma família registra finanças manualmente sem integração externa;
- recursos pessoais não vazam entre membros;
- transferências não duplicam receita ou despesa;
- alterações relevantes possuem trilha de auditoria.

## Fase 2 — Organização, orçamento e recorrências

**Objetivo:** permitir planejamento e acompanhamento financeiro cotidiano.

Entregas:

- categorias em árvore, tags e carga inicial editável;
- regras de categorização e caixa de pendências;
- aprendizado local explicável;
- orçamentos por periodicidade;
- limites, envelopes e base zero;
- recorrências;
- pagamentos e recebimentos parciais;
- projetos, objetivos e metas;
- dashboard inicial.

Critério de saída:

- usuário compara planejado e realizado;
- movimentações sem classificação são revisáveis;
- confirmações geram sugestões futuras explicáveis.

## Fase 3 — Importação e conciliação

**Objetivo:** reduzir lançamento manual sem depender de Open Finance.

Entregas:

- contrato comum de importadores;
- OFX de conta e cartão;
- CSV configurável;
- pré-visualização e relatório de críticas;
- identificação assistida de conta;
- lotes reversíveis;
- deduplicação e conciliação;
- preservação dos campos originais.

Critério de saída:

- importações são reversíveis;
- formatos imperfeitos geram críticas corrigíveis;
- duplicidades prováveis não entram silenciosamente.

## Fase 4 — Cartões, faturas e projeções

**Objetivo:** antecipar compromissos futuros.

Entregas:

- cartões, adicionais, fechamento, vencimento e limites;
- faturas e compras nacionais/internacionais;
- parcelamentos manuais e inferidos;
- pagamento e conciliação da fatura;
- fluxo de caixa configurável;
- cenários e nível de confiança;
- calendário financeiro;
- alertas internos e PWA.

Critério de saída:

- compromissos futuros não duplicam despesa e pagamento da fatura;
- projeções indicam origem e confiança;
- primeira data de déficit é identificável.

## Fase 5 — Pluggy e Open Finance

**Objetivo:** integrar dados bancários como fonte opcional.

Pré-requisito: spike técnico aprovado para Meu Pluggy/Conector 200.

Entregas:

- configuração segura de credenciais;
- conexão, desconexão e sincronização manual;
- polling opcional;
- contas, saldos, transações e cartões conforme cobertura;
- investimentos e empréstimos conforme cobertura;
- histórico preservável após desconexão;
- conflitos entre Pluggy, arquivos e dados manuais.

Critério de saída:

- indisponibilidade da Pluggy não impede o uso;
- sincronização é idempotente;
- usuário controla exclusão do histórico.

## Fase 6 — Empréstimos, patrimônio e investimentos

**Objetivo:** consolidar posição financeira e dívidas.

Entregas:

- empréstimos e financiamentos;
- Price, SAC, taxas e indexadores;
- CET, IOF, seguros e tarifas;
- amortização, portabilidade e conciliação de parcelas;
- patrimônio manual;
- investimentos e reserva de emergência;
- rentabilidade, patrimônio líquido e indicadores.

## Fase 7 — Documentos, compromissos e automações

Entregas:

- PDF textual por adaptadores;
- OCR experimental e QIF;
- central de compromissos;
- linha digitável e código de barras;
- cobranças desconhecidas ou contestadas;
- detecção de assinaturas;
- notificações SMTP, Telegram e webhook;
- API pública estabilizada e webhooks de saída.

## Fase 8 — Distribuição e maturidade comunitária

Entregas:

- instalador/gerenciador local;
- atualização assistida;
- imagens oficiais `amd64` e `arm64`;
- documentação para Windows, Linux e macOS;
- processo de release e changelog;
- política de suporte e vulnerabilidades;
- guia de adaptadores;
- testes de restauração;
- primeira versão estável;
- avaliação de Android, iOS e desktop usando a mesma base Flutter.

## Política de abertura de issues

Uma issue pronta para desenvolvimento deve possuir:

- contexto e problema;
- objetivo observável;
- escopo incluído e excluído;
- dependências;
- critérios de aceite;
- testes esperados;
- impacto em segurança e migração;
- arquivos ou módulos prováveis, quando conhecidos.

Issues sem contrato suficiente permanecem em refinamento.

## Política de paralelismo

Pode ser trabalhado em paralelo quando:

- não altera o mesmo contrato central;
- dependências estão concluídas;
- não exige migração conflitante;
- possui testes isolados;
- há responsável explícito.

Não deve ser trabalhado em paralelo quando:

- define autenticação ou autorização ainda instável;
- altera o modelo monetário ou de datas;
- redefine o livro financeiro;
- muda contratos usados por várias issues abertas;
- depende de decisão arquitetural pendente;
- introduz uma segunda tecnologia de cliente sem ADR aprovado.
