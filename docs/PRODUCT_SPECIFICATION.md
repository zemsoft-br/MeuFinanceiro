# Especificação do Produto — MeuFinanceiro

## 1. Visão

O MeuFinanceiro é um gestor financeiro pessoal e familiar, open-source e autohospedado, destinado exclusivamente ao contexto brasileiro.

O sistema deve permitir que uma residência organize contas pessoais e compartilhadas, orçamentos, cartões, compromissos, empréstimos, investimentos, patrimônio e projeções de caixa sem depender de um serviço SaaS centralizado.

## 2. Limites do produto

- Atende somente pessoas físicas.
- Não executa, agenda ou inicia transações financeiras.
- Não depende de Open Finance para funcionar.
- Não envia dados financeiros para a Zemsoft.
- Não oferece contabilidade empresarial ou fiscal.
- Não substitui orientação financeira profissional.

## 3. Público-alvo

- Casais e famílias que compartilham parte das finanças.
- Pessoas que desejam manter dados financeiros sob seu próprio controle.
- Usuários capazes de seguir um instalador ou tutorial de Docker.
- Comunidade open-source interessada em contribuir com o produto.

## 4. Princípios

1. **Local-first:** o banco local é a fonte principal de verdade.
2. **Privacidade por padrão:** telemetria desativada e integrações opcionais.
3. **Importação reversível:** lotes importados podem ser auditados e desfeitos.
4. **Explicabilidade:** automações informam a regra, origem e confiança da decisão.
5. **Sem duplicidade contábil:** caixa, competência, cartão e transferências são modelados separadamente.
6. **Extensibilidade por adaptadores:** provedores externos não contaminam o domínio.
7. **Colaboração orientada a contratos:** issues devem possuir escopo, dependências, critérios de aceite e testes.

## 5. Modelo familiar

A entidade superior é a `Residência` (`household`).

Papéis iniciais:

- **Administrador:** membros, segurança, integrações, backup e configurações globais.
- **Membro:** gerencia recursos aos quais possui acesso.
- **Visualizador:** consulta recursos compartilhados, quando habilitado.

Escopos de visibilidade:

- **Pessoal:** somente o proprietário.
- **Compartilhado:** membros explicitamente selecionados.
- **Familiar:** todos os membros da residência.

## 6. Capacidades funcionais

### 6.1 Contas e saldos

- Conta corrente, poupança, dinheiro, carteira digital, investimento, benefício e tipos personalizados.
- Saldo inicial em contas manuais.
- Contas arquiváveis.
- Comparação entre saldo calculado e saldo informado pela instituição.
- Divergências sempre apresentadas para conciliação.
- Transferências entre contas próprias sem contabilização como receita ou despesa.
- Cheque especial e limites configuráveis.

### 6.2 Livro financeiro

Toda movimentação deve possuir, quando aplicável:

- origem;
- conta;
- proprietário e escopo;
- valor e moeda;
- data da transação;
- competência;
- vencimento;
- previsão;
- liquidação;
- importação;
- categoria;
- tags;
- projeto ou objetivo;
- estado;
- confiança;
- vínculo de conciliação;
- vínculo ao lote/importador de origem.

Origens previstas:

- manual;
- Pluggy;
- OFX;
- CSV;
- PDF;
- QIF;
- recorrência;
- projeção;
- empréstimo;
- investimento.

Estados previstos:

- previsto;
- confirmado;
- parcialmente liquidado;
- liquidado;
- vencido;
- cancelado;
- ignorado;
- em conciliação.

### 6.3 Caixa e competência

O sistema registra as duas perspectivas simultaneamente.

- Relatórios de consumo e orçamento usam competência por padrão.
- Fluxo de caixa e disponibilidade bancária usam caixa por padrão.
- O usuário pode alterar a visão e substituir regras em lançamentos específicos.
- Pagamento de fatura é liquidação/transferência para o cartão, não nova despesa.

### 6.4 Categorias, tags e aprendizado

- Árvore de categorias com profundidade livre.
- Carga inicial editável e removível.
- Categorias desativáveis sem perda histórica.
- Tags livres.
- Rateio de uma movimentação entre categorias, pessoas e projetos.
- Regras por descrição, favorecido, conta, valor e recorrência.
- Reprocessamento histórico opcional.
- Sugestão local baseada em confirmações anteriores.
- Automação condicionada a limite de confiança configurável.
- Caixa de pendências para itens sem classificação confiável.

### 6.5 Orçamentos

- Periodicidade mensal, semanal, quinzenal, anual ou personalizada.
- Limites, envelopes e orçamento base zero combináveis.
- Escopo pessoal, compartilhado ou familiar.
- Valores variáveis por período.
- Saldos acumuláveis por categoria quando configurado.
- Planejamento de receitas.
- Comparativo planejado versus realizado.

### 6.6 Projetos, objetivos e metas

- Projetos financeiros temporários, como viagem ou reforma.
- Metas com valor e data-alvo.
- Recomendação de contribuição periódica.
- Vinculação de receitas, despesas, ativos e reservas.
- Simulações sem alterar os dados reais.

### 6.7 Cartões e faturas

- Cartão principal e adicionais.
- Proprietário da compra.
- Conta pagadora opcional.
- Fechamento, vencimento e limites editáveis.
- Limite total, disponível e comprometido por parcelas futuras.
- Compras nacionais e internacionais.
- Detecção assistida de parcelamentos.
- Confirmação obrigatória antes de criar parcelas futuras inferidas.
- Distinção entre parcela bancária, confirmada, inferida e manual.
- Conciliação opcional do pagamento da fatura com a conta bancária.
- Importação por Open Finance, OFX, CSV e PDF.

Antecipações e estornos parcelados serão especificados em decisões próprias.

### 6.8 Fluxo de caixa e cenários

- Horizonte configurável.
- Receitas previstas, recorrências, cartões, empréstimos, metas e gastos planejados.
- Cenários conservador, provável e otimista.
- Valores fixos, último valor, média, intervalo ou valor manual.
- Nível de confiança por projeção.
- Identificação da primeira data de déficit e seus causadores.
- Inclusão opcional de cheque especial e outros limites.

### 6.9 Recorrências e assinaturas

- Recorrências fixas ou estimadas.
- Reajuste, término e limite de ocorrências.
- Geração antecipada ou sob demanda.
- Pagamento e recebimento parcial.
- Juros, multa, desconto e acréscimos.
- Anexos e comprovantes.
- Detecção assistida de assinaturas e gastos recorrentes.

### 6.10 Empréstimos e financiamentos

- Empréstimo pessoal, consignado, financiamento, rotativo, parcelamento de fatura e dívida informal.
- Cadastro calculado ou tabela informada pela instituição.
- Price, SAC, parcelas fixas e pagamentos irregulares.
- CET, juros, IOF, seguros e tarifas.
- Taxas prefixadas e indexadas.
- Simulação de amortização por prazo ou parcela.
- Separação entre principal, juros, tarifas e seguros.
- Dados importados podem ser complementados localmente.
- Conciliação opcional das parcelas com o extrato.

### 6.11 Importações

Formatos planejados:

1. OFX;
2. CSV;
3. PDF textual;
4. PDF/imagem com OCR experimental;
5. QIF.

Requisitos comuns:

- pré-visualização;
- identificação assistida da conta;
- correção manual;
- relatório de críticas;
- preservação dos campos originais;
- importação por lote;
- reversão integral do lote;
- deduplicação por identificadores, hash e similaridade;
- decisão assistida em conflitos entre fontes.

### 6.12 Compromissos e DDA

Enquanto não houver provedor compatível, o sistema terá uma central de compromissos:

- cadastro manual;
- linha digitável;
- código de barras;
- PDF;
- imagem;
- cobrança desconhecida ou contestada;
- confirmação antes de afetar o fluxo;
- conciliação com o pagamento identificado no extrato.

### 6.13 Patrimônio e investimentos

- Patrimônio líquido desde as primeiras versões públicas.
- Imóveis, veículos, participações e bens personalizados.
- Valor de aquisição e valor atual.
- Saldos, aportes, resgates e rentabilidade de investimentos.
- Reserva de emergência separada.
- Aportes configuráveis como transferência patrimonial.

### 6.14 Relatórios

- Dashboard com saldo atual e projetado, faturas, compromissos, orçamento, receitas, despesas, patrimônio, dívidas e pendências.
- Despesas por categoria.
- Evolução mensal.
- Planejado versus realizado.
- Fluxo de caixa.
- Cartões e faturas.
- Dívidas e amortizações.
- Patrimônio e investimentos.
- Assinaturas e recorrências.
- Comparação entre períodos.
- Taxa de poupança, comprometimento de renda, custo da dívida e meses de reserva.
- Drill-down dos gráficos até as movimentações.
- Exportação em CSV, planilha e PDF.

### 6.15 Alertas

- Orçamento próximo do limite.
- Fatura fora do padrão.
- Vencimentos.
- Saldo futuro negativo.
- Transação incomum.
- Integração expirada.
- Empréstimo próximo da quitação.

Canais planejados:

- central interna;
- notificação PWA;
- SMTP configurado pelo usuário;
- Telegram configurado pelo usuário;
- webhook genérico.

## 7. Integração Pluggy

- Integração opcional por adaptador.
- Credenciais configuradas por cada instalação.
- Uso inicial do Meu Pluggy/Conector 200 sujeito a prova de conceito.
- Sincronização manual no fluxo gratuito e polling opcional.
- Histórico local preservado após desconexão.
- Exclusão do histórico decidida pelo usuário.
- Persistência apenas do modelo normalizado necessário ao produto.
- Conta, cartão, transação, investimento e empréstimo condicionados à cobertura real do conector.
- Nenhum suporte a iniciação de pagamento.

## 8. Requisitos não funcionais

- Imagens Docker `amd64` e `arm64`.
- PWA responsiva e instalável.
- Operação local sem internet para funcionalidades não integradas.
- API documentada por OpenAPI.
- Migrações de banco versionadas.
- Operações financeiras determinísticas e testadas.
- Auditoria das mutações relevantes.
- Backups criptografados e restauráveis.
- Segredos externos ao banco sempre que possível.
- Banco PostgreSQL não exposto publicamente.
- Tailscale como recomendação de acesso remoto.
- Telemetria desativada por padrão e sem conteúdo financeiro.

## 9. Fora do escopo inicial

- Aplicativo móvel nativo.
- Multiempresa ou contabilidade empresarial.
- Emissão fiscal.
- Iniciação de pagamentos.
- Marketplace de plugins executados dentro do backend.
- Dependência de IA externa para categorização.
- Hospedagem SaaS oficial.

## 10. Critério para primeira versão pública

A primeira versão pública deve permitir que uma família instale o produto, cadastre membros e contas, importe ou registre movimentações, organize orçamento e cartões, visualize projeções, faça backup e restaure os dados sem depender da Pluggy.