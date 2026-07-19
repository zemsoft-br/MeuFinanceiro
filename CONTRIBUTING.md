# Contribuindo com o MeuFinanceiro

Obrigado pelo interesse em contribuir. O MeuFinanceiro manipula dados financeiros sensíveis e regras que não podem produzir resultados ambíguos. Por isso, contribuições devem seguir contratos explícitos, testes e revisão.

## 1. Antes de começar

1. Leia `docs/PRODUCT_SPECIFICATION.md`.
2. Leia `docs/ARCHITECTURE.md`.
3. Escolha uma issue com escopo e critérios de aceite completos.
4. Confirme que ela não está atribuída a outra pessoa.
5. Comente que pretende trabalhar nela e aguarde a atribuição quando necessário.

Não inicie funcionalidades sem issue. Discussões exploratórias podem começar em issues marcadas no título como `[DISCUSSION]` ou `[SPIKE]`.

## 2. Fluxo de branches

```text
feature/*  -> develop
fix/*      -> develop
release/*  -> main
hotfix/*   -> main e retorno obrigatório para develop
docs/*     -> develop, salvo documentação exclusiva de release
```

Regras:

- mudanças diretas em `main` e `develop` não são permitidas após o bootstrap;
- toda mudança passa por Pull Request;
- uma branch deve resolver uma issue ou um conjunto explicitamente acoplado;
- branches devem ser removidas após o merge;
- use nomes curtos e descritivos, como `feature/ledger-entry-create`;
- não misture refatoração ampla com funcionalidade sem justificativa.

## 3. Pull Requests

Abra a PR como **draft** durante o desenvolvimento.

Marque como pronta somente quando:

- o escopo da issue estiver completo;
- testes locais passarem;
- documentação e migrações estiverem atualizadas;
- não houver segredos ou dados financeiros reais;
- a descrição explicar decisões e riscos.

Para economizar minutos de GitHub Actions, os workflows principais devem ser configurados para executar automaticamente quando a PR sair de draft e ficar pronta para revisão. Execução manual pode permanecer disponível para diagnóstico.

PRs de `feature/*`, `fix/*` e `docs/*` usam squash merge por padrão. Releases podem usar merge commit quando isso preservar melhor o histórico de promoção.

## 4. Commits

Use Conventional Commits:

```text
feat: add household membership model
fix: prevent duplicate transfer posting
docs: explain OFX import lifecycle
test: cover partial settlement rounding
refactor: isolate banking provider port
chore: update development tooling
```

Commits devem ser pequenos, coerentes e sem arquivos gerados desnecessários.

## 5. Definição de issue pronta

Uma issue pronta para desenvolvimento contém:

- problema e contexto;
- resultado esperado;
- escopo incluído;
- escopo excluído;
- dependências;
- critérios de aceite verificáveis;
- testes esperados;
- impacto em segurança;
- impacto em banco e migração;
- decisões arquiteturais relacionadas.

Uma issue grande deve ser dividida antes de ser atribuída.

## 6. Critérios mínimos de qualidade

Toda mudança aplicável deve incluir:

- testes unitários das regras;
- testes de integração para persistência e autorização;
- validação de migrações;
- tratamento explícito de erros;
- logs sanitizados;
- documentação de comportamento público;
- compatibilidade com `amd64` e `arm64` quando afetar imagens.

Regras financeiras precisam de testes determinísticos para:

- valores e arredondamento;
- datas e competência;
- idempotência;
- duplicidade;
- cancelamento e reversão;
- concorrência quando relevante;
- isolamento entre membros e residências.

## 7. Segurança e privacidade

Nunca inclua:

- credenciais Pluggy;
- tokens;
- senhas;
- chaves privadas;
- arquivos bancários reais;
- nomes, CPF, e-mail ou descrições financeiras reais;
- dumps de produção;
- logs não sanitizados.

Use dados fictícios e claramente identificados como demonstração.

Vulnerabilidades não devem ser publicadas em issues comuns. Consulte `SECURITY.md`.

## 8. Migrações

- Migrações devem ser reversíveis quando tecnicamente seguro.
- Nunca altere uma migração já liberada; crie uma nova.
- Inclua estratégia para dados existentes.
- Operações destrutivas exigem decisão documentada.
- Mudanças monetárias, de autorização ou auditoria exigem revisão reforçada.

## 9. Dependências

Uma nova dependência precisa justificar:

- problema que resolve;
- manutenção e maturidade;
- licença compatível;
- impacto de segurança;
- tamanho e desempenho;
- suporte a arquiteturas alvo;
- alternativa sem dependência.

## 10. Decisões arquiteturais

Mudanças estruturais devem criar ou atualizar um ADR em `docs/adr/`.

Exemplos:

- persistência monetária;
- autenticação;
- criptografia;
- fila de tarefas;
- formato de plugins/adaptadores;
- alteração do fluxo de branches;
- adoção de serviço adicional.

## 11. Revisão

O autor é responsável por responder aos comentários e manter a branch atualizada.

Revisores avaliam:

- aderência à issue;
- correção funcional;
- segurança e privacidade;
- cobertura de testes;
- clareza do domínio;
- impacto em compatibilidade e migração;
- documentação.

Aprovação não autoriza automaticamente merge de mudanças sensíveis. O mantenedor decide o momento de integração e release.

## 12. Código de conduta

Interações devem ser técnicas, respeitosas e focadas no projeto. Divergências devem ser resolvidas por evidência, testes, ADRs e critérios do produto.
