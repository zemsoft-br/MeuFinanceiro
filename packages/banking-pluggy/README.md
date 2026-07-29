# Banking Pluggy

Pacote específico que converte snapshots sanitizados da Pluggy para o contrato neutro
`BankingProvider` do MeuFinanceiro.

## Recorte atual

O adapter implementa somente:

- leitura de estado da conexão;
- leitura de capacidades observadas;
- listagem de contas;
- listagem paginada de transações.

O adapter recebe um `PluggyReadOnlyGateway` por injeção. O gateway desta issue é
apenas um protocolo tipado; não existe implementação de rede.

## Operações bloqueadas

As operações abaixo retornam `UNSUPPORTED` antes de acessar o gateway:

- criação de intenção de conexão;
- reautenticação;
- faturas;
- investimentos;
- empréstimos;
- atualização manual;
- desconexão.

## Restrições

Este pacote:

- depende apenas de `meufinanceiro-banking` e da biblioteca padrão;
- não contém cliente HTTP ou SDK externo;
- não lê ambiente ou arquivos de configuração;
- não recebe credenciais ou tokens;
- não persiste respostas ou identificadores;
- não é instalado nem registrado no runtime da API;
- não executa chamadas externas.

Uma implementação futura de transporte deverá produzir os snapshots sanitizados
exigidos pelo gateway sem expor resposta HTTP bruta ao adapter ou ao domínio.
