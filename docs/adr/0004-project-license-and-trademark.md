# ADR-0004 — Licença do código e política de marca

- Status: Proposed
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O projeto deve ser open-source, aceitar contribuições e permitir uso autohospedado. Ao mesmo tempo, existe a intenção de impedir que uma empresa ofereça uma versão modificada e fechada pela rede sem compartilhar suas alterações.

O nome e a identidade visual também precisam distinguir o projeto oficial de forks não mantidos pela Zemsoft.

## Proposta

Adotar:

- código-fonte: `AGPL-3.0-only`;
- documentação: `CC-BY-4.0`;
- marca, nome e logotipo: política de marca própria, não concedidos automaticamente pela licença do código.

A licença AGPL permite uso, modificação, distribuição e exploração comercial, mas exige disponibilização do código correspondente em cenários cobertos, incluindo interação com versões modificadas pela rede.

## Alternativas consideradas

### MIT

Muito simples e permissiva, mas permite forks proprietários e serviços fechados sem obrigação de publicar alterações.

### Apache-2.0

Permissiva e com tratamento explícito de patentes, porém também permite modificações e serviços fechados.

### GPL-3.0-only

Copyleft forte na distribuição, mas não cobre de forma equivalente o uso de uma versão modificada apenas como serviço de rede.

### AGPL-3.0-or-later

Permite migração automática para versões futuras da licença. Não é a proposta inicial porque os mantenedores devem revisar qualquer mudança futura antes de adotá-la.

## Consequências positivas

- protege a natureza aberta de modificações oferecidas pela rede;
- permite uso e serviços comerciais compatíveis com a licença;
- reduz apropriação fechada do trabalho comunitário;
- política de marca pode evitar confusão entre oficial e fork.

## Consequências negativas e riscos

- algumas empresas evitam dependências AGPL;
- compatibilidade de dependências precisa ser verificada;
- contribuição empresarial pode exigir análise jurídica;
- a política de marca precisa ser escrita separadamente;
- a decisão técnica não substitui parecer jurídico.

## Questões para aceite

- O mantenedor confirma que deseja copyleft de rede?
- Haverá contributor license agreement ou Developer Certificate of Origin?
- Quem será o titular inicial do copyright?
- Qual uso do nome e logotipo será permitido em forks?
- A documentação deve realmente usar CC-BY-4.0 ou acompanhar a AGPL?

## Validação

A licença só deve ser adicionada ao repositório após aceite explícito deste ADR e verificação de compatibilidade com a stack e os templates adotados.
