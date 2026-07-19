# ADR-0004 — Licença, contribuições e política de marca

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O projeto deve ser open-source, aceitar contribuições e permitir uso autohospedado. Ao mesmo tempo, existe a intenção de impedir que uma empresa ofereça uma versão modificada e fechada pela rede sem compartilhar suas alterações.

O nome e a identidade visual também precisam distinguir o projeto oficial de forks não mantidos pela Zemsoft.

## Decisão

Adotar:

- código-fonte, scripts, configurações executáveis e testes: `AGPL-3.0-only`;
- documentação original dentro de `docs/`: `CC-BY-4.0`, salvo indicação específica diferente;
- contribuições: Developer Certificate of Origin 1.1 (`DCO-1.1`), confirmado por `Signed-off-by` em cada commit;
- copyright: Zemsoft e contribuidores, com cada colaborador preservando os direitos sobre a própria contribuição salvo acordo escrito diferente;
- marca, nome, logotipo e identidade visual: política própria em `TRADEMARKS.md`, sem concessão automática pelas licenças do código ou da documentação;
- ausência de CLA nesta fase.

A licença AGPL permite uso, modificação, distribuição e exploração comercial, mas exige disponibilização do código correspondente em cenários cobertos, incluindo interação com versões modificadas pela rede.

O DCO confirma a procedência e o direito de contribuição sem transferir automaticamente o copyright ao mantenedor.

## Alternativas consideradas

### MIT

Muito simples e permissiva, mas permite forks proprietários e serviços fechados sem obrigação de publicar alterações.

### Apache-2.0

Permissiva e com tratamento explícito de patentes, porém também permite modificações e serviços fechados.

### GPL-3.0-only

Copyleft forte na distribuição, mas não cobre de forma equivalente o uso de uma versão modificada apenas como serviço de rede.

### AGPL-3.0-or-later

Permite migração automática para versões futuras da licença. Não foi adotada porque os mantenedores devem revisar uma futura versão antes de alterar os termos aplicáveis ao projeto.

### Contributor License Agreement

Não adotado nesta fase por adicionar burocracia e conceder direitos adicionais ao mantenedor sem necessidade operacional atual. A adoção futura exigirá novo ADR e não poderá retroagir silenciosamente sobre contribuições anteriores.

### Documentação sob AGPL

Não adotada porque a CC BY 4.0 oferece um contrato mais apropriado para reutilização e adaptação de material documental, preservando atribuição.

## Consequências positivas

- protege a natureza aberta de modificações oferecidas pela rede;
- permite uso e serviços comerciais compatíveis com a licença;
- reduz apropriação fechada do trabalho comunitário;
- preserva a autoria dos colaboradores;
- mantém baixo atrito de contribuição por meio do DCO;
- política de marca reduz confusão entre projeto oficial, forks e serviços independentes;
- documentação pode ser reutilizada com atribuição clara.

## Consequências negativas e riscos

- algumas empresas evitam dependências AGPL;
- compatibilidade de novas dependências precisa ser verificada antes da adoção;
- contribuições sem `Signed-off-by` precisarão ser corrigidas antes do merge;
- contribuição empresarial pode exigir autorização do empregador e análise jurídica própria;
- a política de marca precisa ser aplicada de maneira consistente e proporcional;
- esta decisão técnica não substitui parecer jurídico.

## Aplicação

Arquivos normativos:

- `LICENSE`: texto integral da GNU Affero General Public License versão 3;
- `DCO`: Developer Certificate of Origin 1.1;
- `COPYRIGHT.md`: titularidade e escopo das licenças;
- `docs/LICENSE.md`: aplicação da CC BY 4.0 à documentação;
- `TRADEMARKS.md`: usos permitidos e restrições de marca;
- `CONTRIBUTING.md`: processo de sign-off;
- `.github/PULL_REQUEST_TEMPLATE.md`: confirmação operacional do DCO.

O projeto usará o identificador SPDX `AGPL-3.0-only` para o código. Arquivos com termos diferentes devem declarar a exceção explicitamente e somente podem ser adicionados após verificação de compatibilidade.

## Validação

- o mantenedor confirmou explicitamente a combinação `AGPL-3.0-only + DCO + CC-BY-4.0 + política de marca`;
- o texto integral da AGPL foi incluído sem alteração de seus termos;
- o DCO 1.1 foi incluído integralmente;
- a política não afirma registro de marca inexistente;
- dependências futuras permanecem sujeitas à verificação de licença prevista no processo de contribuição.
