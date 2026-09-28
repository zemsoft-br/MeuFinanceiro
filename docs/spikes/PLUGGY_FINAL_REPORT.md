# Relatório final da spike Pluggy / Meu Pluggy

Status: **conclusão técnica da issue #11 por meio da issue #61**.

Este relatório consolida provas executadas em laboratório isolado. Ele não autoriza
integração produtiva, não contém dados bancários reais e não substitui decisões
futuras de persistência, segurança, UX ou operação.

## Resultado executivo

A integração opcional com a Pluggy é tecnicamente viável para o MeuFinanceiro,
desde que seja implementada atrás da fronteira neutra `BankingProvider` e preserve
a operação integral sem provedor bancário.

A spike comprovou:

- autenticação server-side de uma Development Application;
- criação de Connect Token e uso do Pluggy Connect;
- reutilização de Items existentes em vez de duplicá-los;
- leitura de contas bancárias e conta de cartão;
- leitura de transações `POSTED` e `PENDING`;
- leitura de faturas e presença de metadados de parcelas;
- paginação por cursor em transporte simulado e contrato oficial;
- candidatos a deduplicação e atualização incremental;
- política limitada para `401/403`, `429`, `5xx`, timeout e rede;
- geração de evidências sanitizadas sem tokens, credenciais, IDs ou valores.

A spike não comprovou disponibilidade universal de investimentos, empréstimos,
webhooks, atualização manual ou renovação/desconexão real de consentimento.

## Entregas consolidadas

| Entrega | Resultado |
|---|---|
| PR #54 | laboratório isolado, Connect Widget e contrato inicial |
| PR #56 | autenticação real aceitando `apiKey` |
| PR #58 | contas, transações, cartão, faturas e parcelas |
| PR #60 | ciclo de API key, retry e rate limit |
| issue #61 | contrato final, matriz de capacidades e threat model |

## Evidência operacional observada

A prova real registrada pela PR #58 encontrou, sem persistir dados sensíveis:

- conexão com estado sanitizado saudável;
- três contas consultadas;
- conta corrente, cartão de crédito e poupança;
- 392 transações inventariadas;
- 357 transações `POSTED`;
- 35 transações `PENDING`;
- cinco faturas;
- 20 transações com metadados de parcelas;
- histórico superior a 365 dias em uma conta;
- presença de `id` e `updatedAt` nas transações observadas;
- ausência observada de `providerId` na amostra;
- zero investimentos e zero empréstimos na coleta correspondente.

Esses números descrevem somente a amostra do mantenedor. Eles não são SLA, contrato
de plano ou garantia para outras instituições.

## Matriz de capacidade

| Entidade ou operação | Contrato oficial | Observada na amostra | Decisão |
|---|---:|---:|---|
| autenticação | sim | sim | suportada |
| Connect Widget | sim | sim | suportada |
| contas bancárias | sim | sim | por conexão |
| cartão de crédito | sim | sim | por conexão |
| transações | sim | sim | suportada com paginação |
| estados pendentes | sim | sim | preservar separadamente |
| faturas | sim | sim | por conta de cartão |
| parcelas | parcial/variável | sim | não inferir agrupador ausente |
| investimentos | sim | zero registros | `NOT_OBSERVED` |
| empréstimos | sim | zero registros | `NOT_OBSERVED` |
| atualização manual | sim | não executada | futura e limitada |
| renovação de consentimento | sim | não executada | futura e explícita |
| desconexão | sim | não executada | futura e destrutiva |
| webhooks | sim | não executados | opcionais |

## Fatos, inferências e lacunas

### Fatos comprovados

- `apiKey` é o campo de autenticação observado na API real.
- API key e Connect Token possuem ciclos e escopos diferentes.
- Items duplicados para as mesmas credenciais podem ser rejeitados.
- Conta de cartão é representada como uma conta de crédito.
- Transações pendentes e confirmadas coexistem.
- Faturas podem estar vinculadas à conta de cartão.
- Metadados de parcelas não garantem um identificador único de compra.
- Identificador externo não é suficiente, isoladamente, para deduplicação eterna.
- Uma conexão saudável pode retornar coleção vazia para determinado produto.

### Inferências arquiteturais aceitas

- capacidades devem ser registradas por conexão e por conta;
- sincronização deve ser idempotente e reconciliável;
- webhooks não podem ser a única fonte de consistência;
- atualização manual precisa ser single-flight e respeitar a próxima janela segura;
- exclusão do Item deve ser tratada como desconexão explícita, não como limpeza de
  dados locais;
- ausência de registros não deve desabilitar definitivamente uma capacidade.

### Lacunas deliberadas

- comportamento real de renovação de consentimento;
- comportamento real de desconexão e revogação;
- atualização manual em Development/Production conforme plano;
- entrega, duplicidade e perda de webhooks;
- investimentos e empréstimos com registros reais;
- cursores reais em amostra com mais de uma página;
- variações de schema entre instituições;
- limites específicos do plano futuro da instalação.

Nenhuma dessas lacunas justifica operação destrutiva durante a spike.

## Estratégia de sincronização manual

A primeira integração produtiva deve funcionar sem webhook público.

```text
usuário solicita atualização
-> autorização por residência
-> chave idempotente
-> validação de single-flight
-> validação da próxima janela permitida
-> solicitação ao provedor
-> polling limitado do estado
-> coleta das capacidades disponíveis
-> importação idempotente
-> reconciliação
-> registro de última atualização
```

Controles obrigatórios:

- somente uma execução ativa por conexão;
- deadline explícito;
- backoff entre consultas de estado;
- sem polling contínuo;
- cursor só avança após página persistida;
- falha parcial preserva capacidade e estado por entidade;
- ação do usuário interrompe retry automático;
- interface mostra última atualização e estado parcial;
- frequência não é adivinhada pelo domínio.

## Política de atualização e limites

A documentação oficial distingue o rate limit HTTP da API dos limites operacionais
do Open Finance.

O contrato deve considerar:

- rate limit HTTP por endpoint e IP;
- frequência contratada para atualização de Item;
- limites mensais por CPF/CNPJ, instituição e produto;
- produtos com atualização em cada execução;
- produtos históricos atualizados em janelas mais espaçadas;
- possíveis atrasos entre consentimento e disponibilidade de novos produtos.

Consequências:

- não prometer tempo real;
- não permitir botão de atualizar sem janela conhecida;
- evitar múltiplos Items para a mesma pessoa e instituição;
- manter `next_refresh_allowed_at` operacional;
- informar dados desatualizados sem tratá-los como erro definitivo;
- distinguir HTTP `429` de produto omitido por limite operacional.

## Consentimento, reautenticação e desconexão

### Reautenticação

Quando a conexão exige login, MFA ou renovação de consentimento:

- mapear para `REAUTHENTICATION_REQUIRED`;
- criar Connect Token vinculado à conexão existente;
- exigir ação explícita do usuário;
- não criar novo Item por padrão;
- não repetir credenciais automaticamente.

### Desconexão

A exclusão do Item é destrutiva para a conexão externa e pode revogar consentimento.
Uma futura interface deve:

- exigir confirmação clara;
- validar autorização do membro da residência;
- registrar auditoria;
- impedir sincronizações futuras;
- preservar registros financeiros já importados;
- oferecer política separada para desvincular ou excluir dados locais.

A spike não executou `DELETE /items/{id}`.

## Estratégia de deduplicação

A deduplicação inicial usa camadas:

1. identificador externo, quando presente;
2. provedor, conexão e conta externas;
3. estado da transação;
4. data efetiva e data de atualização;
5. valor e moeda;
6. fingerprint de campos estáveis;
7. vínculo de fatura e metadados de parcela, quando disponíveis.

Regras:

- `PENDING` que evolui para `POSTED` deve atualizar, não duplicar;
- ID alterado após mudança material exige reconciliação por fingerprint;
- transação removida pelo provedor vira tombstone/revisão;
- repetição de página é segura;
- descrição, data e valor não formam chave suficiente;
- parcelas permanecem independentes sem agrupador confiável.

## Threat model

### Credenciais e tokens

Riscos:

- vazamento de `CLIENT_SECRET`;
- API key em log;
- Connect Token persistido;
- credencial bancária recebida pelo backend indevidamente.

Controles:

- keyring/secret store;
- API key e Connect Token somente em memória;
- redaction por allowlist;
- nenhuma credencial por argumento;
- rotação operacional documentada;
- widget para entrada de credencial e MFA.

### Conexões e consentimento

Riscos:

- duplicidade de Item;
- conexão atribuída à residência errada;
- reautenticação por ator sem permissão;
- desconexão acidental ou maliciosa.

Controles:

- vínculo local imutável entre residência e conexão;
- `avoidDuplicates` e verificação de conexão existente;
- autorização por ator;
- confirmação forte para desconexão;
- auditoria sem payload bruto.

### Sincronização

Riscos:

- consumo excessivo de limites;
- execução concorrente;
- cursor trocado entre contas;
- webhook duplicado ou perdido;
- página parcialmente persistida;
- dados antigos exibidos como atuais.

Controles:

- single-flight;
- próxima janela conhecida;
- cursor opaco vinculado à conta;
- evento idempotente;
- transação local por página/lote;
- reconciliação manual independente de webhook;
- timestamp de última atualização visível.

### Dados financeiros

Riscos:

- coleta excessiva;
- logging de valores ou identificadores;
- estado pendente tratado como confirmado;
- exclusão externa apagando histórico local.

Controles:

- DTOs por allowlist;
- logs somente com contagens e códigos limitados;
- estados distintos;
- retenção e RLS definidos antes da integração;
- tombstone e revisão, nunca delete silencioso.

## Classificação de dados

| Classe | Exemplos | Destino permitido |
|---|---|---|
| segredo da instalação | Client ID, Client Secret | keyring/secret store |
| segredo efêmero | API key, Connect Token | somente memória |
| credencial bancária | senha, MFA | widget/provedor, nunca persistir |
| identificador operacional | Item, Account, Transaction, cursor | banco protegido, sem logs |
| metadado operacional | estado, capacidade, última sincronização | banco operacional |
| dado financeiro | valor, data, descrição, fatura | domínio após ADR e RLS |
| diagnóstico | código externo limitado | armazenamento restrito e temporário |
| payload bruto | resposta HTTP completa | proibido |

## Decisão sobre o contrato

O contrato `BankingProvider` passa de **proposto** para **validado para implementação
futura**, com estas condições:

1. nenhum tipo Pluggy cru entra no domínio;
2. capacidades são por conexão/conta;
3. ausência de registros não significa ausência de suporte;
4. sincronização inicial é manual, single-flight e sem webhook obrigatório;
5. credenciais usam configuração segura da instalação;
6. dados externos só são persistidos após ADR de schema, RLS e retenção;
7. desconexão permanece operação destrutiva separada;
8. pagamentos e DDA continuam proibidos no escopo atual.

## Backlog produtivo recomendado

### 1. Persistência e segurança

- ADR de credenciais, identificadores externos, RLS, retenção e auditoria;
- modelo de residência/conexão/capacidade;
- feature flag por instalação.

### 2. Interface executável

- tipos neutros em Python;
- testes contratuais do provider fake;
- sem SDK Pluggy no domínio.

### 3. Adaptador Pluggy mínimo

- autenticação;
- leitura de conexão e capacidades;
- contas e transações read-only;
- sanitização e observabilidade.

### 4. UX de conexão

- Connect Widget;
- vínculo com residência;
- reautenticação;
- última sincronização e estados parciais.

### 5. Sincronização manual

- single-flight;
- polling limitado;
- importação idempotente;
- reconciliação `PENDING`/`POSTED`/`DELETED`.

### 6. Desconexão e consentimento

- confirmação forte;
- revogação externa;
- preservação de histórico local;
- auditoria.

### 7. Webhooks opcionais

- somente após a sincronização manual estar correta;
- autenticação, idempotência, retry e reconciliação.

## Fora do escopo deste fechamento

- código Pluggy no backend principal;
- schema ou migration;
- armazenamento de identificadores reais;
- atualização ou exclusão de Item;
- renovação real de consentimento;
- webhook público;
- polling produtivo;
- sincronização automática;
- deploy, HML ou produção;
- pagamentos, DDA ou API comercial paga.

## Fontes oficiais verificadas em 27/07/2026

- https://docs.pluggy.ai/reference/auth
- https://docs.pluggy.ai/docs/item
- https://docs.pluggy.ai/docs/item-lifecycle
- https://docs.pluggy.ai/docs/updating-an-item
- https://docs.pluggy.ai/reference/items-update
- https://docs.pluggy.ai/docs/consents
- https://docs.pluggy.ai/docs/consent-management-delete-an-item
- https://docs.pluggy.ai/docs/webhooks
- https://docs.pluggy.ai/docs/rate-limits
- https://docs.pluggy.ai/docs/rate-limits-of
- https://docs.pluggy.ai/docs/transactions
- https://docs.pluggy.ai/reference/transactions-list-by-cursor

## Conclusão

A spike respondeu às perguntas necessárias para separar uma futura integração Pluggy
do domínio financeiro e evitar decisões perigosas por conveniência. O próximo passo
não é ampliar o laboratório, mas abrir o primeiro recorte produtivo de persistência e
segurança, ainda sem sincronização automática e sem alterar o funcionamento offline
do MeuFinanceiro.
