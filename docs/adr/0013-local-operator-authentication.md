# ADR-0013 — Autenticação local de operador e sessões opacas

- Status: Accepted
- Data: 2026-08-05
- Decisores: mantenedores

## Contexto

O MeuFinanceiro é autohospedado e ainda não possui usuários, sessões ou autorização HTTP. A integração bancária já pode ser composta no runtime, mas continua sem endpoints porque uma proteção baseada em segredo estático, IP, header improvisado ou flag de ambiente não oferece identidade, revogação ou auditoria suficiente.

A primeira fronteira necessária é um operador administrador da instalação. O produto ainda não possui o modelo funcional completo de residências e membros, portanto este ADR limita a decisão a uma instalação por banco PostgreSQL e um primeiro administrador criado localmente.

## Decisão

- O primeiro operador é criado somente por CLI local dentro do container da API.
- A CLI recebe apenas o login como argumento; senha e confirmação são lidas por `getpass` em terminal interativo.
- Senhas são persistidas exclusivamente como Argon2id usando o perfil do ADR-0005.
- Login usa um identificador ASCII local normalizado; e-mail não é exigido.
- A autenticação HTTP usa tokens bearer opacos de alta entropia.
- O token é retornado somente na criação da sessão; apenas seu SHA-256 é persistido.
- Sessões possuem expiração absoluta e revogação explícita. Não há refresh token neste recorte.
- Respostas de credencial inválida não distinguem login inexistente, senha incorreta, operador desabilitado ou bloqueio temporário.
- Tentativas falhas conhecidas produzem bloqueio temporário limitado; login inexistente executa verificação Argon2id dummy para reduzir enumeração por tempo.
- Health e status demo permanecem públicos.
- Endpoints administrativos bancários somente poderão ser adicionados após dependerem desse principal autenticado.

O schema `identity` não usa RLS nesta fase. A autenticação precisa localizar a instalação e o operador antes de existir um contexto autenticado, e o contrato atual é deliberadamente um banco por instalação. A futura introdução de múltiplas residências e membros exigirá autorização nos casos de uso e políticas próprias.

## Alternativas consideradas

### JWT stateless

Rejeitado neste estágio. Revogação, rotação, invalidação por desativação e redução da superfície de claims seriam mais complexas sem benefício para uma instalação local.

### Segredo administrativo em variável de ambiente

Rejeitado. Não representa uma pessoa, não permite sessões independentes ou logout e tende a ser copiado para scripts, logs e suporte.

### OAuth/OIDC ou provedor externo

Adiado. Criaria dependência externa para a instalação inicial e ampliaria substancialmente configuração, disponibilidade e threat model.

### Cookie de sessão

Adiado até o cliente Flutter implementar login e a política CSRF/SameSite/TLS ser definida. O primeiro contrato usa `Authorization: Bearer` e não persiste token no cliente.

## Consequências positivas

- endpoints sensíveis podem depender de uma identidade revogável;
- nenhum token em plaintext precisa permanecer no banco;
- instalações continuam independentes de serviços externos;
- Argon2id e redaction existentes são reutilizados;
- a futura autorização por residência pode evoluir sobre um principal explícito.

## Consequências negativas e riscos

- o usuário deve executar um bootstrap local antes do primeiro login;
- perda da senha ainda não possui recuperação automatizada;
- bearer token exige transporte seguro fora do loopback;
- uma instalação por banco é uma limitação explícita;
- sessões em banco adicionam uma consulta por requisição autenticada.

## Validação

- migration e grants testados em PostgreSQL real;
- bootstrap único e concorrência;
- hash Argon2id sem senha persistida;
- token bruto ausente do banco e de representações;
- expiração, revogação, desativação e bloqueio;
- equivalência de erro para tentativas inválidas;
- endpoints de criar, consultar e encerrar sessão;
- health e demo públicos;
- quality e container gates integrais.

## Referências

- ADR-0005 — Configuração segura, criptografia e gerenciamento de chaves.
- ADR-0006 — Persistência e fila de tarefas no PostgreSQL.
- ADR-0012 — Persistência, segurança e feature flag da integração bancária.
