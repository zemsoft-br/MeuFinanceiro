# Roadmap — MeuFinanceiro

## Estratégia

O produto será construído em camadas. A colaboração externa começa somente depois que os contratos da fundação estiverem estáveis o suficiente para evitar retrabalho estrutural.

Issues devem ser pequenas, testáveis e preferencialmente independentes. Epics organizam o trabalho, mas não devem ser implementadas diretamente em uma única Pull Request.

## Fase 0 — Fundação do projeto

Objetivo: tornar o repositório seguro e previsível para colaboração.

Entregas:

- visão e limites do produto;
- arquitetura inicial;
- estratégia de branches e Pull Requests;
- templates de issue e PR;
- decisão de licença e política de marca;
- monorepo e ambiente de desenvolvimento;
- Docker Compose local;
- configuração centralizada;
- migrações e health checks;
- quality gates econômicos;
- guia de contribuição;
- modelo de ADR;
- política de segurança;
- dados de demonstração sem informações reais.

Critério de saída:

- novo colaborador consegue executar o projeto localmente;
- PR de exemplo passa pelos quality gates;
- nenhum segredo é necessário para o modo de demonstração;
- regras de contribuição estão documentadas.

## Fase 1 — Identidade, residência e núcleo financeiro

Objetivo: estabelecer os contratos de autorização e o livro financeiro.

Entregas:

- autenticação local;
- residência e membros;
- papéis simplificados;
- escopo pessoal, compartilhado e familiar;
- contas financeiras;
- tipos de conta personalizados;
- movimentações;
- transferências entre contas próprias;
- rateios;
- datas de caixa e competência;
- auditoria;
- testes determinísticos de dinheiro e autorização.

Critério de saída:

- família consegue registrar finanças manualmente sem integrações externas;
- recursos pessoais não vazam entre membros;
- transferências não duplicam receita/despesa;
- alterações relevantes possuem trilha de auditoria.

## Fase 2 — Organização, orçamento e recorrências

Objetivo: permitir planejamento e acompanhamento financeiro cotidiano.

Entregas:

- categorias em árvore;
- tags;
- carga inicial editável;
- regras de categorização;
- caixa de pendências;
- aprendizado local inicial;
- orçamentos por diferentes periodicidades;
- limites, envelopes e base zero;
- recorrências;
- pagamentos e recebimentos parciais;
- projetos, objetivos e metas;
- dashboard inicial.

Critério de saída:

- usuário compara planejado e realizado;
- movimentações sem classificação são revisáveis;
- confirmações do usuário geram sugestões futuras explicáveis.

## Fase 3 — Importação e conciliação

Objetivo: reduzir lançamento manual sem depender de Open Finance.

Entregas:

- contrato comum de importadores;
- OFX de conta e cartão;
- CSV configurável;
- pré-visualização;
- relatório de críticas;
- identificação assistida de conta;
- importação por lote;
- rollback do lote;
- deduplicação;
- conciliação entre fontes;
- preservação dos campos originais.

Critério de saída:

- importações são reversíveis;
- formatos imperfeitos geram críticas corrigíveis;
- duplicidades prováveis não entram silenciosamente.

## Fase 4 — Cartões, faturas e projeções

Objetivo: antecipar compromissos futuros.

Entregas:

- cartões e adicionais;
- fechamento e vencimento;
- limites;
- faturas;
- compras nacionais e internacionais;
- parcelamentos manuais e inferidos;
- confirmação de parcelas futuras;
- pagamento e conciliação da fatura;
- fluxo de caixa configurável;
- cenários;
- nível de confiança;
- calendário financeiro;
- alertas internos e PWA.

Critério de saída:

- usuário visualiza compromissos futuros sem duplicar a despesa e o pagamento da fatura;
- projeções indicam origem e confiança;
- primeira data de déficit é identificável.

## Fase 5 — Pluggy e Open Finance

Objetivo: integrar dados bancários como fonte opcional.

Pré-requisito:

- spike técnico aprovado para o Meu Pluggy/Conector 200.

Entregas:

- configuração segura de credenciais;
- conexão e desconexão;
- sincronização manual;
- polling opcional;
- contas e saldos;
- transações;
- cartões e faturas conforme cobertura;
- investimentos conforme cobertura;
- empréstimos conforme cobertura;
- histórico preservável após desconexão;
- conflitos Pluggy versus arquivos e dados manuais.

Critério de saída:

- falha ou indisponibilidade da Pluggy não impede o uso do sistema;
- sincronização é idempotente;
- usuário controla exclusão do histórico.

## Fase 6 — Empréstimos, patrimônio e investimentos

Objetivo: consolidar posição financeira e dívidas.

Entregas:

- empréstimos e financiamentos;
- Price e SAC;
- taxas e indexadores;
- CET, IOF, seguros e tarifas;
- amortização e portabilidade;
- conciliação de parcelas;
- patrimônio manual;
- investimentos;
- reserva de emergência;
- rentabilidade;
- patrimônio líquido;
- indicadores de dívida e poupança.

## Fase 7 — Documentos, compromissos e automações avançadas

Entregas:

- PDF textual por adaptadores;
- OCR experimental;
- QIF;
- central de compromissos;
- linha digitável e código de barras;
- cobranças desconhecidas/contestadas;
- detecção de assinaturas;
- notificações SMTP, Telegram e webhook;
- API pública estabilizada;
- webhooks de saída.

## Fase 8 — Distribuição e maturidade comunitária

Entregas:

- instalador/gerenciador local;
- atualização assistida;
- imagens oficiais `amd64` e `arm64`;
- documentação para Windows, Linux e macOS;
- processo de release e changelog;
- política de suporte;
- guia de criação de adaptadores;
- política de vulnerabilidades;
- testes de restauração;
- primeira versão estável.

## Política de abertura de issues

Uma issue pronta para desenvolvimento deve possuir:

- contexto e problema;
- objetivo observável;
- escopo incluído;
- escopo excluído;
- dependências;
- critérios de aceite;
- testes esperados;
- impacto em segurança e migração;
- arquivos ou módulos prováveis, quando conhecidos.

Issues sem contrato suficiente permanecem em refinamento e não devem ser assumidas por colaboradores.

## Política de paralelismo

Pode ser trabalhado em paralelo quando:

- não altera o mesmo contrato central;
- dependências estão concluídas;
- não exige migração conflitante;
- possui testes isolados;
- há um responsável explícito.

Não deve ser trabalhado em paralelo quando:

- define autenticação ou autorização ainda instável;
- altera o modelo monetário ou de datas;
- redefine o livro financeiro;
- muda contratos usados por várias issues abertas;
- depende de uma decisão arquitetural pendente.
