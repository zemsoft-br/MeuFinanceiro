# ADR-0003 — GitFlow simplificado e colaboração orientada a issues

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O projeto terá colaboradores com diferentes níveis de familiaridade com o domínio financeiro. Trabalho paralelo sem contratos claros pode gerar migrações conflitantes, duplicação de regras e mudanças incompatíveis no núcleo.

O uso de GitHub Actions também deve considerar o limite compartilhado de minutos da organização.

## Decisão

Será utilizado um GitFlow simplificado:

- `main`: releases e estado publicável;
- `develop`: integração contínua das próximas entregas;
- `feature/*`, `fix/*` e `docs/*`: Pull Requests para `develop`;
- `release/*`: estabilização e Pull Request para `main`;
- `hotfix/*`: correção em `main` com retorno obrigatório para `develop`.

Toda implementação deve partir de uma issue refinada. Epics organizam o roadmap, mas são divididas em child issues pequenas antes da atribuição.

Pull Requests começam como draft. Os quality gates automáticos principais devem executar quando a PR for marcada como pronta para revisão, preservando minutos durante commits intermediários.

## Alternativas consideradas

### Trunk-based development

Não adotado inicialmente porque a base ainda será formada e os colaboradores precisarão de contratos e revisão mais controlados.

### GitHub Flow apenas com `main`

Não adotado inicialmente porque o projeto precisa separar integração de trabalho da linha publicável.

### Planejamento fora do GitHub

Rejeitado porque reduziria transparência e dificultaria participação comunitária.

## Consequências positivas

- roadmap e execução permanecem públicos;
- colaboradores encontram tarefas prontas e delimitadas;
- `main` não recebe funcionalidades incompletas;
- qualidade e revisão são verificáveis;
- menor desperdício de GitHub Actions durante desenvolvimento em draft.

## Consequências negativas e riscos

- maior disciplina de manutenção de branches;
- `develop` pode acumular mudanças se releases forem raras;
- issues precisam ser refinadas antes de atraírem contribuições;
- hotfixes exigem sincronização cuidadosa.

## Validação

A Fase 0 deve incluir uma PR de exemplo, quality gates e documentação suficiente para um colaborador novo executar o fluxo sem instrução privada.
