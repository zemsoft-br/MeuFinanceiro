# Contrato dos dados demonstrativos

- Issue: #22
- Residência: `Residência Ipê`
- Finalidade: demonstração, testes visuais, testes integrados e documentação
- Proibição: dados reais de mantenedores, clientes ou instituições

## 1. Princípios

1. A fixture é central e versionada.
2. Todos os módulos referenciam os mesmos identificadores.
3. Totais são derivados, não digitados em múltiplos lugares.
4. Datas derivam de relógio injetável.
5. Dados demonstrativos nunca se misturam com dados reais.
6. Modo demonstração deve ser visualmente explícito.
7. Reset é determinístico e reproduzível.
8. Segredos, tokens e credenciais são placeholders inválidos.
9. Marcas e instituições devem ser fictícias ou licenciadas para uso.
10. O dataset deve provar invariantes, erros e estados vazios.

## 2. Relógio de referência

A fixture define:

```text
fixture_reference_date = 2026-11-01
timezone = America/Sao_Paulo
currency = BRL
```

Datas relativas são derivadas dessa referência.

Testes não usam `now()` diretamente.

Exemplos:

- hoje: `reference_date`;
- vencimento em 3 dias: `reference_date + 3 dias`;
- risco de caixa: data explícita derivada;
- último mês: competência anterior calculada.

## 3. Identificadores estáveis

Usar UUIDs ou IDs determinísticos documentados para:

- residência;
- usuários;
- associações;
- contas;
- cartões;
- categorias;
- movimentos;
- recorrências;
- metas;
- projetos;
- lotes;
- contratos;
- ativos;
- alertas.

Nunca relacionar fixtures por texto visível.

## 4. Pessoas

Criar pessoas inteiramente fictícias, por exemplo:

- Ana Ribeiro — Administradora;
- Bruno Ribeiro — Membro;
- Clara Ribeiro — Visualizadora;
- Perfil Demonstração — proprietário técnico do modo isolado, quando necessário.

Nenhum nome deve corresponder ao mantenedor como padrão público.

## 5. Contas e saldo consolidado

Composição canônica:

| Conta | Tipo | Saldo |
|---|---|---:|
| Banco Exemplo | Corrente | R$ 8.240,10 |
| Cooperativa Modelo | Poupança | R$ 5.150,00 |
| Carteira Teste | Carteira digital | R$ 1.580,40 |
| Dinheiro | Espécie | R$ 450,00 |
| **Total** |  | **R$ 15.420,50** |

O total deve ser recalculado a partir das contas.

Limites e cheque especial não entram no saldo consolidado.

## 6. Cartões

Referências:

- Cartão Black fictício;
- limite total: R$ 10.000,00;
- fatura atual: R$ 1.200,30;
- fatura futura projetada: R$ 4.250,00.

As competências devem ser diferentes e explícitas.

A composição da fatura deve fechar com compras, parcelas, créditos, estornos e tarifas.

## 7. Orçamento

Receitas planejadas de referência: R$ 18.500,00.

Categoria Alimentação:

- planejado: R$ 800,00;
- realizado: R$ 950,00;
- excesso: R$ 150,00;
- utilização: 118,75%.

O realizado deve ser derivado de movimentos da competência.

## 8. Fluxo de caixa

Projeção de 30 dias:

- saldo inicial: R$ 15.420,50;
- entradas: R$ 8.500,00;
- saídas: R$ 12.150,00;
- saldo final: R$ 11.770,50.

Equação:

```text
15.420,50 + 8.500,00 − 12.150,00 = 11.770,50
```

Eventos devem explicar o total, incluindo fatura, aluguel, recorrências, metas e projetos.

## 9. Metas

Destinação virtual:

| Meta | Valor destinado |
|---|---:|
| Reserva de Emergência | R$ 6.000,00 |
| Viagem Europa | R$ 2.500,00 |
| **Total destinado** | **R$ 8.500,00** |

Saldo não destinado:

```text
R$ 15.420,50 − R$ 8.500,00 = R$ 6.920,50
```

A fixture deve impedir dupla destinação da mesma unidade monetária, salvo cenário explícito de sobrealocação.

## 10. Recorrências

Valores canônicos devem ter contexto:

- salário recorrente: R$ 8.500,00;
- aluguel: R$ 3.500,00;
- StreamPlay, assinatura fictícia: R$ 34,90.

Valores alternativos só podem existir quando representarem:

- outro membro;
- outra competência;
- reajuste;
- evento estimado;
- cenário.

A tela deve rotular o contexto.

## 11. Empréstimos

Diferenciar valor contratado de saldo devedor.

| Contrato | Valor contratado | Saldo devedor |
|---|---:|---:|
| Veículo | R$ 48.000,00 | R$ 38.420,00 |
| Pessoal | R$ 12.000,00 | R$ 12.000,00 |
| Familiar | R$ 5.000,00 | R$ 5.000,00 |
| Consignado | valor documentado no contrato | R$ 7.030,00 |
| **Total** |  | **R$ 62.450,00** |

Parcelas e cronogramas devem fechar com o saldo conforme o sistema de amortização adotado.

## 12. Patrimônio

Referência inicial:

- patrimônio bruto: R$ 1.250.000,00;
- passivos: R$ 62.450,00;
- patrimônio líquido: R$ 1.187.550,00.

A composição dos ativos deve fechar exatamente em R$ 1.250.000,00.

A participação de caixa e contas deve ser derivada dos R$ 15.420,50, salvo saldo adicional em conta de investimento explicitamente separado.

Carteira de investimentos:

- custo: R$ 450.000,00;
- valor atual: R$ 523.450,80;
- resultado: R$ 73.450,80;
- resultado percentual derivado: aproximadamente 16,3224%.

Percentuais de gráficos são calculados a partir dos valores.

## 13. Dados operacionais

A fixture deve incluir:

- uma transferência entre contas próprias;
- uma compra de cartão e o pagamento da fatura;
- uma liquidação parcial;
- uma movimentação rateada;
- um registro manual e uma observação externa duplicada;
- uma recorrência gerada;
- uma assinatura sugerida não confirmada;
- uma meta em risco;
- um projeto acima do planejado;
- um lote OFX;
- um CSV com erros;
- uma sincronização Pluggy parcial;
- um contrato com parcela vencida;
- um ativo desatualizado;
- um backup verificado;
- um teste de restauração vencido;
- uma sessão suspeita.

## 14. Estados vazios e erros

Fixtures auxiliares devem permitir:

- instalação nova;
- residência sem conta;
- conta sem movimento;
- período sem dados;
- API indisponível;
- permissão negada;
- integração desconectada;
- importação com erro;
- backup inválido;
- modo demonstração.

Esses estados não devem exigir editar manualmente o dataset principal.

## 15. Implementação futura

A issue de modo demonstração deverá definir:

- formato do seed;
- estratégia de reset;
- isolamento por banco ou residência;
- proteção contra alteração acidental;
- uso em testes;
- licença dos assets;
- tamanho do dataset;
- geração de documentos fictícios;
- CI visual.

Até essa issue, os valores deste documento são contrato documental, não persistência implementada.
