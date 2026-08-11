# Invariantes financeiras e contratos entre módulos

- Issue: #22
- Autoridade: domínio backend, persistência e testes
- Estado: contrato prévio às funcionalidades financeiras

## 1. Objetivo

Definir regras que não podem variar entre telas, relatórios, importadores, integrações ou módulos.

Essas regras devem ser protegidas em:

- entidades e value objects;
- serviços de domínio e casos de uso;
- constraints e índices quando aplicável;
- transações;
- migrações;
- testes unitários;
- testes de integração;
- testes de autorização;
- testes de idempotência.

## 2. Dinheiro

A representação monetária canônica foi aceita no ADR-0015.

- Nunca usar `float` como autoridade financeira.
- O backend usa `Decimal` finito e o contrato futuro de persistência é `NUMERIC(24,8)` com moeda separada.
- Moeda é código ASCII uppercase de três letras.
- APIs financeiras serializam amount como string decimal fixed-point, nunca JSON number/float autoritativo.
- Até oito casas decimais são preservadas sem arredondamento implícito.
- Arredondamento exige escala e modo explícitos no caso de uso.
- Soma, subtração e comparação ordenada exigem a mesma moeda.
- Conversão de moeda exige taxa, data, fonte e arredondamento rastreáveis.
- Totais derivados não são aceitos como entrada autoritativa quando podem ser recalculados.

O value object inicial está em `meufinanceiro-finance`. Regras de minor units e câmbio permanecem casos de uso separados.

## 3. Tempo financeiro

Conceitos distintos:

- data do evento;
- competência;
- vencimento;
- liquidação;
- importação;
- instante de auditoria;
- data de referência de saldo ou avaliação.

Datas sem horário usam `date`. Instantes técnicos usam UTC. Apresentação usa o fuso da residência.

Testes usam relógio injetável.

## 4. Livro financeiro único

`Movement` ou nome equivalente é a fonte canônica de eventos financeiros realizados e liquidações.

Nenhum módulo pode:

- copiar uma movimentação para outro ledger;
- manter saldo autoritativo concorrente;
- registrar o mesmo efeito financeiro em tabelas independentes;
- alterar saldo sem evento rastreável.

Módulos podem manter:

- projeções;
- observações externas;
- agregados recalculáveis;
- snapshots;
- vínculos classificatórios;
- auditoria.

Esses registros não substituem a movimentação canônica.

## 5. Saldos

Saldo calculado é derivado de:

- saldo de abertura explícito;
- movimentos efetivos;
- reversões e ajustes explícitos.

Saldo informado por instituição é observação externa com data de referência.

Divergências:

- não são corrigidas silenciosamente;
- geram revisão;
- podem produzir ajuste explícito e auditado;
- preservam a observação original.

## 6. Transferências

Transferência entre contas da mesma residência:

- reduz uma conta;
- aumenta outra;
- não é receita;
- não é despesa;
- não altera o resultado consolidado;
- pode incluir tarifa separada;
- deve ser atômica no domínio;
- deve ser idempotente.

As duas pontas devem estar ligadas pelo mesmo identificador de transferência.

## 7. Rateios

Um rateio:

- pertence a uma única movimentação;
- distribui exatamente o valor alocável;
- não cria movimentos financeiros desconectados;
- pode distribuir categoria, membro, projeto e escopo conforme regras;
- deve fechar após arredondamento.

A soma das alocações deve ser igual ao valor da movimentação, salvo componente explicitamente não alocado.

## 8. Cartões e faturas

- A compra é a despesa.
- A compra possui competência e pode possuir moeda original.
- A fatura agrega compras, créditos, estornos, tarifas e ajustes.
- O pagamento da fatura é liquidação que reduz caixa.
- O pagamento não é nova despesa.
- Parcelas futuras não duplicam a compra original.
- Estorno referencia o evento revertido.
- Pagamento parcial preserva saldo restante.
- Cartão adicional não muda o titular econômico da compra sem decisão explícita.

Relatórios devem evitar dupla contagem entre compra e pagamento.

## 9. Orçamentos

Conceitos:

- planejado;
- comprometido;
- realizado;
- disponível;
- projetado.

Regras:

- planejado não é movimento;
- comprometido não inclui novamente a parcela já realizada;
- realizado vem do livro por competência;
- disponível orçamentário não é saldo bancário;
- projetado é estimativa e registra fonte;
- envelopes são alocações virtuais;
- transporte de envelope não cria transferência bancária;
- receita planejada não é receita realizada;
- base zero não força movimento para equilibrar.

## 10. Recorrências e assinaturas

- regra recorrente é modelo;
- ocorrência é instância;
- ocorrência projetada não é movimento;
- ocorrência gerada possui vínculo estável;
- repetição da geração é idempotente;
- regra pausada não gera novas ocorrências;
- alteração preserva versões ou histórico;
- assinatura sugerida exige confirmação;
- variação de valor não é fraude automaticamente.

## 11. Metas e projetos

### 11.1 Destinações

- destinação virtual classifica parte de saldo existente;
- não cria caixa;
- não aumenta patrimônio;
- não pode alocar a mesma unidade monetária integralmente a duas metas sem sobrealocação explícita;
- contribuição planejada só afeta projeção;
- contribuição real referencia movimento ou transferência.

### 11.2 Projetos

- orçamento do projeto é consolidação classificatória;
- despesa do projeto continua sendo a mesma movimentação;
- remover vínculo não apaga movimento;
- pagamento de fatura não duplica despesa do projeto;
- fases e marcos não são tarefas corporativas genéricas.

## 12. Projeções e cenários

- projeção não altera dados reais;
- cada evento projetado possui origem e confiança;
- cenário existe em namespace isolado;
- evento simulado não vira movimento sem caso de uso explícito;
- comparação deve indicar período e premissas;
- transferência interna não altera saldo consolidado projetado;
- compra e pagamento de fatura têm efeitos distintos em consumo e caixa.

## 13. Importações e conciliação

### 13.1 Estados

Arquivo, lote, registro importado, observação externa e movimento são conceitos distintos.

Registro importado:

- não é movimento automaticamente;
- preserva payload original sanitizado ou referência;
- possui fonte, lote e identificadores externos;
- pode ser ignorado, vinculado, conciliado ou confirmado.

### 13.2 Deduplicação

A deduplicação considera:

- fonte;
- identificador externo;
- FITID;
- conta;
- cartão;
- data;
- competência;
- valor;
- descrição;
- parcela;
- lote anterior;
- movimento já vinculado.

Correspondência incerta não pode excluir ou unir silenciosamente.

### 13.3 Conciliação

Conciliação vincula; não copia.

Um vínculo deve registrar:

- registros participantes;
- decisão;
- responsável;
- confiança;
- regra;
- data;
- reversão.

Rollback de lote deve respeitar dependências.

## 14. Pluggy e fontes externas

- Pluggy é fonte opcional;
- dados entram pelo mesmo pipeline de observação, importação e conciliação;
- sincronização possui idempotency key/cursor;
- atualização do mesmo registro externo não cria novo movimento;
- dado Pluggy não prevalece automaticamente sobre manual ou arquivo;
- desconexão preserva dados confirmados e auditoria;
- nenhuma iniciação de pagamento.

## 15. Empréstimos

Recebimento:

- aumenta caixa;
- aumenta passivo;
- não é receita.

Pagamento:

- principal reduz caixa e passivo;
- juros, tarifas, seguros, impostos e multas são custos financeiros;
- parcela integral não é contabilizada novamente como despesa;
- pagamento parcial preserva composição e saldo;
- cronograma utilizado é versionado;
- renegociação não apaga contrato anterior.

Simulações não alteram cronograma real.

## 16. Patrimônio e investimentos

- patrimônio líquido = ativos − passivos;
- contas são reutilizadas, não copiadas;
- limite de crédito não é ativo;
- bem e dívida são entidades separadas;
- aporte pelo principal é transferência patrimonial;
- resgate pelo principal não é receita;
- rendimento realizado é separado do principal;
- valorização altera avaliação, não caixa;
- cotação preserva fonte e data;
- saldo de corretora e posições não podem ser somados duas vezes;
- destinação de meta não cria ativo.

## 17. Correções, cancelamentos e reversões

Eventos confirmados não devem ser alterados destrutivamente sem trilha.

Preferir:

- estorno;
- reversão;
- nova versão;
- ajuste explícito;
- cancelamento;
- arquivamento.

Auditoria registra:

- autor;
- instante;
- motivo;
- estado anterior;
- estado posterior;
- correlação;
- origem.

## 18. Autorização

A audiência financeira canônica foi aceita no ADR-0016.

Todo recurso financeiro pertence a uma residência e possui:

```text
residence_id
owner_operator_id
visibility_scope
```

Escopos:

- `PERSONAL`: somente o proprietário ativo na mesma residência;
- `SHARED`: proprietário + memberships ativas explicitamente concedidas;
- `HOUSEHOLD`: todas as memberships ativas da residência.

Regras obrigatórias:

- membership inativa falha fechado;
- cross-residence falha fechado;
- `owner`/`administrator` da residência não concede bypass para conteúdo `PERSONAL` alheio;
- grants não substituem membership ativa e só existem para `SHARED`;
- capacidade de mutação por papel é separada da audiência do recurso;
- relatórios, exportações e agregados aplicam a audiência antes de consolidar dados;
- payload não escolhe livremente residência nem ator efetivo;
- persistência financeira futura usa RLS com `app.current_residence_id` e `app.current_operator_id` como defesa em profundidade;
- `USING` e `WITH CHECK` devem impedir leitura e mudança de escopo fora da audiência.

Autorização é aplicada:

- na consulta;
- na mutação;
- em exportações;
- em relatórios;
- em notificações;
- em diagnósticos;
- em auditoria;
- em anexos.

O contrato puro inicial está em `meufinanceiro-finance`. A matriz completa de permissões por papel da membership permanece decisão separada da visibilidade.

## 19. Testes mínimos por regra

Para cada operação financeira relevante:

1. caminho nominal;
2. valor zero e limites;
3. arredondamento;
4. moeda;
5. datas;
6. concorrência;
7. repetição idempotente;
8. reversão;
9. autorização;
10. auditoria;
11. falha no meio da transação;
12. ausência de dupla contabilização.

## 20. Decisões ainda necessárias

Resolvido antes do núcleo financeiro:

- representação monetária e arredondamento: ADR-0015 / #125;
- visibilidade e audiência financeira: ADR-0016 / #129.

Ainda pendentes:

- semântica exata de `Movement`;
- estratégia de imutabilidade;
- modelo de saldo de abertura;
- matriz de capacidade por papel da membership;
- convenções de IDs financeiros;
- versionamento de agregados;
- retenção de observações externas;
- armazenamento de anexos.

A estratégia de RLS de recursos financeiros está definida pelo ADR-0016; a implementação concreta começa junto ao primeiro schema financeiro.

Essas decisões devem entrar em issues pequenas e ADRs próprios.
