# Governança do MeuFinanceiro

## 1. Objetivo

Este documento define como o projeto decide prioridades, distribui trabalho, revisa mudanças e mantém uma linha publicável segura.

O GitHub é a fonte oficial para planejamento e execução:

```text
Roadmap -> Epic -> Issue refinada -> Branch -> Pull Request -> Revisão -> Merge
```

Decisões relevantes não devem depender de conversas privadas.

## 2. Papéis

### Mantenedor

Responsável por:

- visão e prioridades do produto;
- refinamento e aprovação de issues;
- decisões arquiteturais;
- segurança e resposta a vulnerabilidades;
- revisão e merge de Pull Requests;
- releases;
- concessão e remoção de permissões no repositório.

### Colaborador

Pessoa que trabalha em uma issue atribuída, mantém a Pull Request atualizada e responde pela qualidade do escopo entregue.

### Revisor

Pessoa autorizada a avaliar aderência à issue, testes, segurança, arquitetura, migrações e documentação. Revisão não concede automaticamente autorização de merge.

## 3. Planejamento por issues

### Epics

Epics organizam fases ou capacidades amplas. Elas:

- possuem child issues explícitas;
- não são implementadas por uma única Pull Request;
- registram dependências e critérios de saída da fase;
- permanecem sob responsabilidade dos mantenedores.

### Issues prontas

Uma issue somente recebe o estado `status:ready` quando contém:

- contexto e problema;
- objetivo observável;
- escopo incluído e excluído;
- dependências;
- critérios de aceite verificáveis;
- testes esperados;
- impacto em segurança e privacidade;
- impacto em banco e migrações;
- decisões arquiteturais relacionadas.

Issues incompletas usam `status:needs-refinement` e não devem ser assumidas.

## 4. Ciclo de vida da issue

Estados do GitHub Project:

```text
Backlog
Refinamento
Pronta
Em andamento
Em revisão
Bloqueada
Concluída
```

Labels de estado são usadas apenas quando agregam valor fora do Project:

```text
status:needs-refinement
status:ready
status:blocked
```

Fluxo esperado:

1. A necessidade entra no Backlog.
2. O mantenedor refina e registra dependências.
3. A issue passa para Pronta.
4. Um colaborador solicita atribuição.
5. Após atribuição, a issue passa para Em andamento.
6. A abertura da PR move o trabalho para Em revisão.
7. Bloqueios são registrados na issue e no Project.
8. O merge fecha a issue e conclui o item.

## 5. Atribuição de trabalho

Para assumir uma issue:

1. Verifique se ela está pronta e sem responsável.
2. Comente objetivamente que pretende implementá-la.
3. Aguarde a atribuição do mantenedor antes de iniciar mudanças substanciais.
4. Abra uma PR draft cedo para tornar o progresso visível.

Uma pessoa deve manter poucas issues simultâneas. O padrão inicial é uma issue funcional por colaborador, salvo acordo explícito.

### Inatividade

- Após 7 dias corridos sem commit, comentário ou atualização relevante, o mantenedor pode solicitar status.
- Sem resposta nos 3 dias seguintes, a issue pode ser desatribuída.
- O trabalho existente permanece creditado e pode ser reaproveitado.
- Ausências previamente comunicadas não são tratadas como abandono.

## 6. Taxonomia de labels

### Tipo

```text
type:epic
type:task
type:bug
type:spike
type:decision
type:docs
```

### Área

```text
area:frontend
area:backend
area:data
area:infra
area:security
area:integrations
area:docs
```

### Prioridade

```text
priority:P0
priority:P1
priority:P2
priority:P3
```

Significado:

- `P0`: vulnerabilidade crítica, perda/corrupção de dados ou bloqueio grave.
- `P1`: requisito bloqueante da fase ou erro de alto impacto.
- `P2`: trabalho normal planejado.
- `P3`: melhoria sem urgência ou oportunidade futura.

### Contribuição

```text
contribution:good-first-issue
contribution:help-wanted
```

`good-first-issue` somente é aplicado quando a tarefa é pequena, isolada, documentada e não altera contratos centrais.

## 7. Branches

```text
feature/*  -> develop
fix/*      -> develop
docs/*     -> develop
release/*  -> main
hotfix/*   -> main e retorno obrigatório para develop
```

`main` representa a linha publicável. `develop` integra a próxima entrega.

Regras:

- push direto em `main` e `develop` é bloqueado;
- force push e exclusão são bloqueados;
- toda integração passa por Pull Request;
- branches comuns usam squash merge;
- releases podem usar merge commit;
- hotfix integrado em `main` deve retornar para `develop` imediatamente.

## 8. Pull Requests e revisão

Pull Requests começam como draft.

Uma PR fica pronta para revisão somente quando:

- resolve o escopo acordado;
- testes locais passam;
- migrações e documentação foram atualizadas;
- não contém segredos ou dados financeiros reais;
- riscos e decisões estão descritos;
- conflitos conhecidos foram resolvidos.

Requisitos iniciais:

- uma aprovação de revisor elegível;
- todas as conversas resolvidas;
- aprovação invalidada após mudanças relevantes;
- checks obrigatórios aprovados quando a CI estiver implantada;
- revisão por CODEOWNERS nos caminhos sensíveis.

O autor não realiza o próprio merge, salvo exceção emergencial documentada.

## 9. Decisões arquiteturais

Mudanças estruturais usam ADR em `docs/adr/`.

Quando não houver consenso:

1. registrar alternativas e evidências;
2. executar spike quando necessário;
3. documentar consequências;
4. o mantenedor responsável toma a decisão final;
5. a decisão pode ser substituída por novo ADR diante de evidência posterior.

## 10. Releases

- mudanças entram primeiro em `develop`;
- uma branch `release/*` estabiliza a versão;
- somente correções de release entram nessa branch;
- a promoção para `main` gera tag e changelog;
- a release é reconciliada com `develop`;
- mudanças incompatíveis exigem notas de migração e restauração.

## 11. Segurança

Vulnerabilidades não são discutidas em issues públicas. O fluxo privado está descrito em `SECURITY.md`.

Mudanças em autenticação, autorização, criptografia, ledger, importação de arquivos, backup e segredos exigem revisão do mantenedor indicado em `CODEOWNERS`.

## 12. Alterações desta governança

Mudanças neste documento exigem:

- issue do tipo decisão ou tarefa de governança;
- Pull Request separada;
- revisão do mantenedor;
- atualização de ADR quando a mudança contradizer decisão arquitetural vigente.
