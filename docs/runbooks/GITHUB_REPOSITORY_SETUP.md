# Runbook — Configuração administrativa do GitHub

Este runbook descreve as configurações que não são representadas por arquivos versionados. Deve ser executado por um administrador do repositório.

## 1. Configurações gerais

Acesse `Settings > General`.

### Pull Requests

Configurar:

- habilitar **Allow squash merging**;
- manter **Allow merge commits** para releases;
- desabilitar **Allow rebase merging**;
- habilitar **Automatically delete head branches**;
- manter auto-merge desabilitado até os quality gates da issue #5 estarem estáveis;
- habilitar atualização da branch pela interface quando disponível.

Convenções:

- `feature/*`, `fix/*`, `docs/*` e `chore/*`: squash merge;
- `release/*`: merge commit permitido;
- `hotfix/*`: método definido conforme o caso, preservando reconciliação com `develop`.

## 2. Ruleset de `main`

Acesse `Settings > Rules > Rulesets` e crie um ruleset para a branch `main`.

### Aplicação

- Target branches: `main`.
- Enforcement status: Active.
- Não criar bypass permanente para colaboradores.
- Administradores também devem seguir o fluxo, salvo recuperação emergencial documentada.

### Regras

Habilitar:

- Restrict deletions.
- Block force pushes.
- Require a pull request before merging.
- Required approvals: 1.
- Dismiss stale pull request approvals when new commits are pushed.
- Require conversation resolution before merging.
- Require review from Code Owners.

Não habilitar checks obrigatórios até a conclusão da issue #5. Depois disso, adicionar somente checks estáveis e com nomes versionados.

Não exigir histórico linear, porque `release/*` pode usar merge commit.

## 3. Ruleset de `develop`

Crie outro ruleset para `develop`.

Habilitar:

- Restrict deletions.
- Block force pushes.
- Require a pull request before merging.
- Required approvals: 1.
- Dismiss stale approvals.
- Require conversation resolution.
- Require review from Code Owners.

Após a issue #5:

- adicionar quality gates obrigatórios;
- avaliar exigir branch atualizada antes do merge;
- não exigir a opção se ela causar execuções redundantes ou impedir merge seguro por limitações da CI.

## 4. Labels

Acesse `Issues > Labels` e crie a taxonomia abaixo.

### Tipo

| Label | Cor sugerida | Descrição |
|---|---|---|
| `type:epic` | `5319E7` | Fase ou capacidade ampla composta por child issues |
| `type:task` | `1D76DB` | Implementação refinada |
| `type:bug` | `D73A4A` | Comportamento incorreto ou regressão |
| `type:spike` | `FBCA04` | Investigação ou prova de conceito descartável |
| `type:decision` | `A371F7` | Decisão arquitetural, jurídica ou operacional |
| `type:docs` | `0075CA` | Documentação sem mudança funcional |

### Área

| Label | Cor sugerida |
|---|---|
| `area:frontend` | `C5DEF5` |
| `area:backend` | `BFDADC` |
| `area:data` | `D4C5F9` |
| `area:infra` | `F9D0C4` |
| `area:security` | `B60205` |
| `area:integrations` | `FAD8C7` |
| `area:docs` | `DDEEFF` |

### Prioridade

| Label | Cor sugerida | Significado |
|---|---|---|
| `priority:P0` | `B60205` | Crítico: segurança, perda/corrupção de dados ou bloqueio grave |
| `priority:P1` | `D93F0B` | Alto impacto ou bloqueante da fase |
| `priority:P2` | `FBCA04` | Trabalho normal planejado |
| `priority:P3` | `0E8A16` | Melhoria sem urgência |

### Estado e contribuição

| Label | Cor sugerida |
|---|---|
| `status:needs-refinement` | `EDEDED` |
| `status:ready` | `0E8A16` |
| `status:blocked` | `B60205` |
| `contribution:good-first-issue` | `7057FF` |
| `contribution:help-wanted` | `008672` |

Não criar labels adicionais sem uso repetido comprovado.

## 5. Aplicação inicial das labels

Aplicar:

| Issue | Labels mínimas |
|---|---|
| #1 | `type:epic`, `area:infra`, `priority:P1` |
| #2 | `type:task`, `area:infra`, `priority:P1` |
| #3 | `type:decision`, `area:docs`, `priority:P1` |
| #4 | `type:task`, `area:infra`, `priority:P1`, `status:blocked` |
| #5 | `type:task`, `area:infra`, `priority:P1`, `status:blocked` |
| #6 | `type:task`, `area:security`, `priority:P1`, `status:blocked` |
| #7 | `type:task`, `area:data`, `area:backend`, `priority:P1`, `status:blocked` |
| #8 | `type:task`, `area:frontend`, `priority:P2`, `status:blocked` |
| #9 | `type:task`, `area:data`, `priority:P2`, `status:blocked` |
| #10 | `type:docs`, `area:docs`, `priority:P2`, `status:blocked` |
| #11 | `type:spike`, `area:integrations`, `priority:P1`, `status:ready` |

Após merge desta PR:

- #2 pode permanecer `status:ready` enquanto as configurações administrativas forem aplicadas;
- #3 permanece em decisão;
- #4–#10 permanecem bloqueadas conforme suas dependências;
- #11 pode avançar em paralelo sem alterar o backend principal.

## 6. Milestone

Acesse `Issues > Milestones` e crie:

```text
Título: Fase 0 — Fundação
Descrição: Governança, licença, ambiente, segurança, persistência, PWA, demonstração, documentação e spike Pluggy.
Data: sem prazo artificial enquanto o plano inicial não for calibrado.
```

Associe as issues #2 a #11.

A epic #1 pode ou não pertencer ao milestone; a recomendação é associá-la para acompanhar o progresso consolidado.

## 7. GitHub Project

Crie um Project no nível da conta `zemsoft-br` ou do repositório, conforme disponibilidade.

Nome:

```text
MeuFinanceiro — Roadmap
```

Campos:

- Status;
- Prioridade;
- Área;
- Fase;
- Responsável;
- Estimativa opcional somente após o time calibrar o processo.

Valores de Status:

```text
Backlog
Refinamento
Pronta
Em andamento
Em revisão
Bloqueada
Concluída
```

Views recomendadas:

1. **Roadmap:** agrupada por Fase.
2. **Execução:** board por Status.
3. **Contribuições:** filtra `status:ready` e itens sem responsável.
4. **Bloqueadas:** filtra Status = Bloqueada.

Automação mínima:

- item adicionado entra em Backlog;
- issue fechada vai para Concluída;
- PR vinculada aberta move para Em revisão quando possível;
- evitar automações complexas antes de observar o fluxo real.

## 8. Security

Acesse `Settings > Security`.

Habilitar quando disponível:

- Private vulnerability reporting;
- Dependabot alerts;
- Dependabot security updates;
- secret scanning;
- push protection para segredos.

O arquivo `.github/dependabot.yml` controla verificações versionadas, mas alertas e push protection dependem das configurações administrativas.

## 9. Verificação

Após concluir:

1. Tente editar `main` diretamente com uma mudança descartável e confirme o bloqueio sem efetivar a alteração.
2. Abra uma PR de teste para `develop`.
3. Confirme solicitação de revisão por CODEOWNERS.
4. Confirme bloqueio com conversa não resolvida.
5. Confirme invalidação da aprovação após novo commit.
6. Confirme exclusão automática da branch após merge.
7. Confirme labels, milestone e Project nas issues #1–#11.
8. Registre na issue #2 uma evidência sanitizada e a data da validação.

## 10. Alterações futuras

Qualquer mudança em rulesets, taxonomia ou fluxo deve atualizar este runbook e `docs/GOVERNANCE.md` na mesma Pull Request.
