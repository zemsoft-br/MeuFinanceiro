# ADR-0016 — Visibilidade e autorização de recursos financeiros

- Status: Accepted
- Data: 2026-08-11
- Decisores: mantenedores

## Contexto

O produto é familiar e precisa suportar recursos pessoais, compartilhados e familiares sem transformar o papel administrativo da residência em acesso irrestrito aos dados financeiros.

O ADR-0014 criou residência e membership mínimas para derivar `residence_id` da sessão. Esse recorte deliberadamente não definiu múltiplos membros, seleção de residência, RLS do household nem autorização financeira por recurso.

A primeira tabela financeira não pode nascer somente com `residence_id`: isso permitiria que qualquer membro autorizado na residência enxergasse recursos que deveriam permanecer pessoais.

## Decisão

Todo recurso financeiro canônico deve possuir:

```text
residence_id
owner_operator_id
visibility_scope
```

`visibility_scope` possui exatamente os valores:

```text
PERSONAL
SHARED
HOUSEHOLD
```

### PERSONAL

Somente `owner_operator_id` possui acesso ao conteúdo financeiro do recurso.

Papéis `owner` ou `administrator` da residência **não** concedem bypass automático.

### SHARED

O proprietário sempre possui acesso.

Demais operadores precisam estar explicitamente presentes na ACL do recurso e continuar com membership ativa na mesma residência.

Uma ACL nunca concede acesso entre residências e não substitui membership.

### HOUSEHOLD

Todo operador com membership ativa na mesma residência possui acesso ao recurso.

Operador sem membership ativa falha fechado, mesmo que tenha conhecido anteriormente o UUID do recurso.

## Capacidade de leitura e mutação

Visibilidade e capacidade operacional são conceitos separados.

O primeiro contrato de domínio responde apenas se o ator está dentro da audiência do recurso. Casos de uso de criação, alteração, arquivamento, compartilhamento e administração devem aplicar adicionalmente as permissões do papel da membership.

Isso evita cristalizar no value object uma matriz de papéis ainda incompleta. Em especial, o produto prevê um papel futuro de visualização somente leitura, enquanto o schema atual possui `owner`, `administrator` e `member`.

Até uma issue própria ampliar a matriz de papéis, nenhum código pode inferir que `administrator` ou `owner` significa acesso a conteúdo `PERSONAL` de outra pessoa.

## Proprietário

`owner_operator_id` é obrigatório em todos os três escopos.

Ele representa a responsabilidade/posse primária do recurso e não desaparece quando o recurso é compartilhado ou familiar.

Troca de proprietário é mutação sensível e deverá possuir caso de uso explícito, autorização e auditoria; não é atualização genérica de campo.

## ACL compartilhada

Recursos `SHARED` usam grants explícitos por `operator_id`.

Invariantes:

- o proprietário não precisa de grant redundante;
- grants só podem apontar para membership ativa da mesma residência;
- remover/desabilitar membership torna o grant inefetivo imediatamente;
- grant não transfere propriedade;
- grant não concede administração da residência;
- grants de recurso `PERSONAL` ou `HOUSEHOLD` são inválidos.

## RLS e defesa em profundidade

Recursos financeiros persistentes devem usar RLS PostgreSQL com, no mínimo:

```text
app.current_residence_id
app.current_operator_id
```

A política deve exigir o limite de residência e a audiência do recurso.

Conceitualmente:

```text
same_residence
AND active_membership
AND (
    PERSONAL  -> owner_operator_id = current_operator_id
    SHARED    -> owner_operator_id = current_operator_id OR explicit_active_grant
    HOUSEHOLD -> true
)
```

O serviço de aplicação continua responsável por regras de negócio e capacidade de mutação. RLS não substitui autorização do caso de uso; é a barreira fail-closed contra leitura/mutação fora do escopo caso uma consulta seja construída incorretamente.

Políticas futuras devem usar `USING` e `WITH CHECK` para impedir que uma mutação mova um registro para residência/owner/escopo não autorizado.

## Contexto confiável

`residence_id` e `operator_id` usados na autorização são derivados da sessão autenticada e da membership persistida.

Payload financeiro não pode escolher livremente o ator nem a residência efetiva.

Para recursos `SHARED`, uma lista de operadores pode ser recebida como intenção do caso de uso, mas cada operador deve ser resolvido/validado server-side como membership ativa da mesma residência antes da persistência.

## Exportações, relatórios e derivados

A mesma audiência deve valer para:

- consultas;
- relatórios;
- exportações;
- dashboards;
- notificações;
- anexos;
- diagnósticos;
- auditoria que contenha conteúdo financeiro.

Agregação não pode ser usada para contornar privacidade. Um recurso `PERSONAL` não entra em total familiar para outro membro salvo decisão futura explícita e opt-in.

## Alternativas consideradas

### Residence-scoped apenas

Rejeitada. Não representa privacidade pessoal dentro da família.

### Administrador sempre vê tudo

Rejeitada. Papel administrativo não implica consentimento para conteúdo financeiro pessoal.

### ACL para todos os escopos

Rejeitada. `PERSONAL` e `HOUSEHOLD` possuem audiência derivável e ACL redundante aumenta risco de divergência.

### Autorização apenas no FastAPI

Rejeitada. Consultas internas, relatórios, workers e futuras rotas poderiam escapar da mesma regra. RLS é obrigatório como defesa adicional.

### Colocar role da membership dentro de cada recurso

Rejeitada. Papel é característica da relação operador-residência; duplicá-lo no recurso cria duas fontes de verdade.

## Consequências positivas

- privacidade pessoal preservada dentro da residência;
- compartilhamento é explícito e revogável;
- papel administrativo não vira bypass financeiro;
- regras de audiência são provider-neutral;
- RLS pode proteger consultas, relatórios e mutações por uma mesma fronteira;
- futura introdução de viewer/read-only não exige mudar a semântica dos escopos.

## Consequências negativas e riscos

- tabelas financeiras compartilháveis exigirão owner e, para `SHARED`, tabela de grants;
- cada transação financeira no banco precisa configurar `current_operator_id` além de `current_residence_id`;
- relatórios consolidados precisam respeitar audiência antes de agregar;
- mudança de membership pode alterar imediatamente a audiência efetiva de recursos familiares/compartilhados;
- operações administrativas precisarão separar gestão de configuração de acesso ao conteúdo.

## Validação

O pacote `meufinanceiro-finance` materializa a audiência com value objects e função pura, incluindo testes para:

- acesso pessoal somente pelo proprietário;
- compartilhado somente por proprietário ou grant explícito;
- familiar somente por membership ativa na mesma residência;
- cross-residence fail-closed;
- membership inativa fail-closed;
- administrador/owner sem bypass implícito;
- grants inválidos em escopos não compartilhados;
- `repr` sem UUIDs de operadores/residência.

## Referências

- #124
- #129
- ADR-0014
- ADR-0015
- `docs/PRODUCT_SPECIFICATION.md`
- `docs/architecture/FINANCIAL_INVARIANTS.md`
