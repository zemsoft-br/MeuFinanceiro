# Compatibilidade de licenças da stack planejada

## Objetivo

Registrar a verificação preliminar das licenças dos componentes centrais previstos para a fundação do MeuFinanceiro.

Esta análise serve como gate de engenharia. Ela não substitui revisão jurídica e não autoriza automaticamente qualquer dependência transitiva, plugin, asset, fonte, modelo ou pacote futuro.

## Resultado preliminar

Não foi identificada incompatibilidade de licença que impeça a adoção da stack-base abaixo em um projeto distribuído sob `AGPL-3.0-only`, desde que os avisos e textos exigidos pelas licenças de terceiros sejam preservados nas distribuições aplicáveis.

| Componente | Função planejada | Licença declarada pelo projeto | Avaliação inicial |
|---|---|---|---|
| React | Interface Web/PWA | MIT | Permissiva; manter avisos aplicáveis |
| TypeScript | Linguagem/tooling frontend | Apache-2.0 | Compatível com GNU GPL v3 segundo a FSF; preservar avisos e termos Apache |
| FastAPI | API Python | MIT | Permissiva; manter avisos aplicáveis |
| SQLAlchemy | Persistência Python | MIT | Permissiva; manter avisos aplicáveis |
| Alembic | Migrações | MIT | Permissiva; manter avisos aplicáveis |
| PostgreSQL | Banco de dados | PostgreSQL License | Permissiva, semelhante a BSD/MIT segundo o projeto PostgreSQL |
| Caddy | Proxy e servidor HTTP | Apache-2.0 | Compatível com GNU GPL v3 segundo a FSF; preservar avisos e termos Apache |
| pytest | Testes Python | MIT | Permissiva; manter avisos aplicáveis |

## Fontes primárias consultadas

- React: <https://github.com/facebook/react/blob/main/LICENSE>
- TypeScript: <https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt>
- FastAPI: <https://github.com/fastapi/fastapi/blob/master/LICENSE>
- SQLAlchemy: <https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE>
- Alembic: <https://github.com/sqlalchemy/alembic/blob/main/LICENSE>
- PostgreSQL: <https://www.postgresql.org/about/licence/>
- Caddy: <https://github.com/caddyserver/caddy/blob/master/LICENSE>
- pytest: <https://github.com/pytest-dev/pytest/blob/main/LICENSE>
- Classificação e compatibilidade GNU: <https://www.gnu.org/licenses/license-list.html>
- Compatibilidade e relicenciamento GNU: <https://www.gnu.org/licenses/license-compatibility.html>

## Limites desta verificação

A tabela cobre somente os componentes centrais conhecidos em 19 de julho de 2026. Ela não cobre:

- dependências transitivas;
- imagens Docker e pacotes do sistema operacional;
- SDKs da Pluggy ou de outros provedores;
- bibliotecas de PDF, OCR ou criptografia;
- componentes visuais, ícones, fontes e imagens;
- snippets copiados de documentação ou fóruns;
- datasets, modelos de machine learning e arquivos de demonstração;
- plugins opcionais de Caddy;
- pacotes adicionados depois da Fase 0.

A licença precisa ser verificada na versão efetivamente fixada pelo lockfile. Um projeto pode mudar de licença entre versões ou incluir arquivos sob termos diferentes.

## Política para novas dependências

Antes de adicionar uma dependência, a Pull Request deve registrar:

1. nome, versão e finalidade;
2. licença declarada e fonte da verificação;
3. dependências transitivas relevantes;
4. obrigações de atribuição, notices ou disponibilização de código;
5. compatibilidade com `AGPL-3.0-only`;
6. alternativa sem a dependência;
7. eventual uso de marca, asset, fonte, modelo ou dados externos.

Licenças ou situações que exigem bloqueio e revisão específica incluem, sem se limitar a:

- licença ausente, ambígua ou personalizada;
- `GPL-2.0-only`;
- `SSPL`, `BUSL`, `Commons Clause` ou termos source-available;
- licenças com restrição de uso comercial, campo de atuação ou número de usuários;
- componentes com dual licensing cuja opção aplicável não esteja clara;
- dependências que imponham distribuição de chaves, dados privados ou material que o projeto não possa fornecer;
- assets com termos diferentes do código do pacote.

## Notices de terceiros

Antes da primeira distribuição pública executável, o projeto deve gerar e revisar um inventário de terceiros contendo, no mínimo:

- componente e versão;
- licença SPDX quando disponível;
- copyright e notice exigidos;
- origem;
- localização do texto integral da licença.

Esse inventário deverá acompanhar imagens, instaladores ou pacotes distribuídos quando exigido pelas respectivas licenças.

## Revalidação

Esta análise deve ser atualizada:

- na escolha das versões da Fase 0;
- quando uma dependência central for substituída;
- antes da primeira release pública;
- quando scanners detectarem licença nova ou alterada;
- quando houver dúvida sobre combinação, distribuição ou uso em rede.
