# ADR-0012 — Persistência, segurança e feature flag da integração bancária

- Status: Accepted
- Data: 2026-07-28
- Decisores: mantenedores
- Issue: #64

## Contexto

A spike Pluggy validou o contrato neutro `BankingProvider`, os ciclos de
Application, API key, Connect Token, conexão e consentimento, além das fronteiras de
retry, sincronização e privacidade.

O ADR-0002 mantém o PostgreSQL local como fonte de verdade. O ADR-0005 fornece
keyring externo, envelopes AES-256-GCM com AAD, rotação e redaction. O ADR-0006
fornece PostgreSQL, Alembic, role de runtime sem `BYPASSRLS` e fila idempotente.

Ainda falta definir como uma integração bancária produtiva utiliza essas fundações
sem exigir Pluggy, internet, credenciais ou endpoint público para o funcionamento
normal do MeuFinanceiro.

## Decisão

### Integração desabilitada por padrão

A ausência de uma configuração ativa significa `disabled`. O runtime não instancia,
não autentica e não executa código do provider nesse estado.

Cada configuração de provider possui um estado explícito:

```text
disabled
configured
enabled
```

- `disabled`: nenhuma operação externa é permitida;
- `configured`: credenciais cifradas existem, mas chamadas externas permanecem
  bloqueadas;
- `enabled`: um operador da instalação ativou explicitamente o provider.

O estado efetivo nunca é inferido apenas pela presença de credenciais. Configurar e
ativar são ações distintas e auditáveis. Falha ao carregar ou decriptar credenciais
faz o provider permanecer indisponível; não degrada o funcionamento manual do
produto.

### Configuração da Application

A configuração do provider pertence à instalação, não a uma residência. Uma
instalação pode possuir no máximo uma configuração por `provider`.

`CLIENT_ID` e `CLIENT_SECRET` podem ser persistidos somente como envelopes
versionados do ADR-0005. O plaintext existe apenas durante a operação que o utiliza e
deve ser descartado em seguida.

O AAD canônico de cada campo é UTF-8 e segue:

```text
meufinanceiro:v1:installation:{installation_id}:provider:{provider}:
configuration:{configuration_id}:field:{field_name}
```

Os valores permitidos de `field_name` são uma allowlist definida pelo adaptador.
Mover um envelope entre instalação, provider, configuração ou campo deve falhar na
autenticação do AES-GCM.

A API key e o Connect Token nunca são persistidos. Senha bancária e MFA nunca são
recebidos ou armazenados pelo backend; pertencem ao widget e ao provider.

### Separação de escopos

O modelo conceitual separa:

```text
instalação
  -> configuração e credenciais cifradas do provider

residência
  -> conexão externa
  -> capacidades observadas
  -> contas e referências externas
  -> cursores
  -> execuções de sincronização
  -> observações importadas e reconciliação
```

Configuração da Application não contém `residence_id`. Todas as entidades que
representam conexão, conta, cursor, execução ou dado de uma família contêm
`residence_id` diretamente, mesmo quando também são alcançáveis por joins.

### RLS e autorização

Tabelas vinculadas à residência utilizam RLS obrigatória. A role de runtime não pode
possuir `BYPASSRLS`. O contexto da residência é definido de forma transacional pelo
backend após autenticação e autorização do ator.

Políticas futuras devem usar o `residence_id` presente na própria linha. Políticas
que dependam somente de joins indiretos são proibidas para entidades financeiras ou
identificadores externos.

A configuração global do provider é acessível apenas por fluxos administrativos da
instalação. Usuários de uma residência nunca recebem os envelopes, o ciphertext ou
os campos de configuração.

### Identificadores externos

Item ID, Account ID, Transaction ID, Bill ID e cursores são dados operacionais
sensíveis, mas precisam de igualdade, unicidade e reconciliação. Eles podem ser
persistidos em colunas protegidas pelo banco e por RLS, sem criptografia por campo.

Esses valores:

- nunca aparecem em logs, métricas, analytics ou erros de usuário;
- nunca são enviados ao cliente quando um identificador interno é suficiente;
- não podem ser usados como autorização;
- são vinculados a instalação, provider e residência;
- possuem constraints de unicidade adequadas ao recurso.

Uma conexão externa é única por instalação e provider. O mesmo identificador externo
não pode ser associado silenciosamente a duas residências. Reconexão reutiliza a
linha existente ou exige fluxo administrativo explícito.

### Payloads e diagnósticos

É proibido persistir:

- resposta HTTP bruta;
- headers de autenticação;
- request completo;
- cookies;
- stack trace com payload;
- senha bancária ou MFA;
- API key ou Connect Token;
- campos externos não utilizados por regra de domínio ou operação.

Diagnóstico persistido segue allowlist:

```text
provider_reason_code limitado
status HTTP, quando necessário
categoria de erro neutra
tentativa
janela aproximada de retry
quantidade de registros
estado da capacidade
timestamps operacionais
```

Mensagens externas livres não são persistidas. Logs utilizam identificadores locais,
contagens e códigos neutros.

### Modelo conceitual

O schema futuro `integrations` deve separar, no mínimo:

```text
provider_configurations
connections
connection_capabilities
sync_runs
sync_cursors
external_accounts
external_observations
audit_events
```

Este ADR não cria tabelas ou migrations. O modelo executável será definido em issue
posterior, preservando os nomes e invariantes descritos no contrato técnico associado.

### Retenção

A retenção segue classes distintas:

- credenciais cifradas: até substituição ou remoção administrativa explícita;
- API key, Connect Token, senha bancária e MFA: retenção zero;
- conexão e identificador externo: preservados enquanto houver histórico importado ou
  necessidade de auditoria e deduplicação;
- cursor ativo: somente a versão confirmada após persistência integral da página;
- cursores superseded: removidos após commit e auditoria sanitizada;
- execuções de sincronização: padrão de 90 dias, configurável entre 30 e 365 dias;
- eventos administrativos e de segurança: padrão de 365 dias, configurável entre 90
  e 730 dias;
- dados financeiros importados: seguem a política do domínio financeiro, não a
  retenção operacional da integração.

Desconectar impede novas operações externas, mas não apaga automaticamente o
histórico financeiro, a origem ou os vínculos necessários à reconciliação.

### Rewrap transacional

Rotação do keyring não remove chaves históricas. O rewrap dos envelopes persistidos
ocorre em job explícito e idempotente:

1. validar que a nova chave está ativa e a antiga continua disponível;
2. contar envelopes por `key_id` sem decriptar ou imprimir valores;
3. reservar lotes com lock transacional;
4. decriptar usando o AAD canônico;
5. cifrar com a chave ativa;
6. atualizar envelope e revisão na mesma transação;
7. registrar somente contagem, chave de origem, chave de destino e resultado;
8. repetir com segurança até não existir referência à chave antiga;
9. executar verificação de decriptação sem exibir plaintext;
10. remover a chave antiga apenas em operação administrativa posterior.

Falha em qualquer linha preserva o envelope anterior. Rewrap não pode ocorrer junto
de alteração semântica da credencial.

### Backup e restore

Backup recuperável exige:

- snapshot do PostgreSQL;
- keyring correspondente;
- revisão Alembic;
- manifesto com versão do envelope e lista de `key_id` referenciados, sem material de
  chave;
- procedimento de validação isolada.

Restaurar somente o banco ou somente o keyring não é considerado recuperação válida.
A validação de restore confirma integridade dos envelopes sem imprimir credenciais.

### Sincronização e fila

A fila PostgreSQL do ADR-0006 será usada para rewrap e futuras sincronizações. Cada
handler define chave de idempotência própria, limite de tentativas e efeito
reconciliável.

Desabilitar o provider impede novos enqueues externos. Tarefas já reservadas devem
revalidar o estado antes de qualquer chamada. `disabled` e
`REAUTHENTICATION_REQUIRED` não são falhas transitórias e não recebem retry cego.

## Alternativas consideradas

### Credenciais somente em variáveis de ambiente

Rejeitada como contrato principal. Dificulta configuração por instalação, rotação por
registro e administração futura pela aplicação, além de ampliar exposição em
inspeções de processo.

### Credenciais em arquivo separado por provider

Rejeitada para a integração produtiva. O keyring já protege envelopes e permanece
fora do banco; multiplicar arquivos de credencial criaria contratos adicionais de
backup, permissão e rotação.

### Criptografar todos os identificadores externos

Rejeitada. Igualdade, unicidade, paginação e reconciliação exigiriam blind indexes e
mais primitives criptográficos sem reduzir o risco principal. RLS, privilégios,
backup protegido e proibição de logs são os controles adotados.

### Armazenar payload bruto para depuração

Rejeitada por minimização de dados, privacidade, risco de logs e evolução de schema.
A integração persiste apenas campos utilizados e diagnóstico por allowlist.

### Ativar automaticamente quando credenciais existirem

Rejeitada. Configuração e autorização operacional são decisões distintas. A
integração deve permanecer fail-closed.

## Consequências positivas

- funcionamento integral sem provider ou credenciais;
- credenciais protegidas pela fundação existente;
- RLS explícita por residência;
- deduplicação possível sem payload bruto;
- rotação e restore possuem contrato verificável;
- desconexão não destrói histórico local;
- futura implementação pode avançar em migrations pequenas e revisáveis.

## Consequências negativas e riscos

- identificadores externos permanecem legíveis para quem obtiver acesso direto ao
  banco ou backup decriptado;
- restore exige coordenação entre banco e keyring;
- rewrap adiciona operação de manutenção;
- retenções configuráveis exigirão job de limpeza e auditoria;
- a configuração global da instalação exige autorização administrativa própria;
- migrations futuras precisarão validar grants e políticas RLS em PostgreSQL real.

## Validação

- testes documentais impedem persistência de tokens efêmeros e payload bruto;
- testes exigem estado `disabled` por padrão e ativação explícita;
- testes exigem AAD contextual e rewrap transacional;
- testes exigem RLS direta por `residence_id`;
- migrations futuras devem provar upgrade, downgrade, grants e isolamento entre duas
  residências;
- restore futuro deve comprovar integridade sem expor plaintext.

## Referências

- ADR-0002 — fonte local de verdade e adaptadores;
- ADR-0005 — configuração segura, criptografia e keyring;
- ADR-0006 — persistência e fila PostgreSQL;
- `docs/architecture/BANKING_PROVIDER_CONTRACT.md`;
- `docs/architecture/BANKING_INTEGRATION_PERSISTENCE_MODEL.md`;
- issue #64.