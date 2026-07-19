# Política de Segurança

## Status do projeto

O MeuFinanceiro está em desenvolvimento inicial e ainda não possui uma versão estável para dados financeiros reais.

## Relato responsável

Não publique vulnerabilidades exploráveis, credenciais, dados financeiros ou instruções de abuso em issues públicas.

Até a configuração de um canal privado oficial, relate uma vulnerabilidade diretamente aos mantenedores do repositório pelo recurso privado de advisories do GitHub, quando disponível.

Inclua:

- versão ou commit afetado;
- componente afetado;
- impacto esperado;
- passos mínimos de reprodução;
- evidência sanitizada;
- mitigação sugerida, quando conhecida.

Não inclua dados bancários reais.

## Escopo prioritário

São tratados como críticos:

- quebra de isolamento entre residências ou membros;
- bypass de autenticação ou autorização;
- exposição de credenciais, tokens ou chaves;
- execução remota de código;
- importação de arquivo capaz de acessar o host indevidamente;
- alteração silenciosa de valores financeiros;
- falha de criptografia de backups ou anexos;
- logs contendo conteúdo financeiro sensível;
- dependências comprometidas.

## Princípios de desenvolvimento seguro

- segredos nunca entram no repositório;
- PostgreSQL não é publicado por padrão;
- integrações externas são opcionais;
- arquivos importados são tratados como não confiáveis;
- operações críticas são auditáveis e idempotentes;
- dados de teste são inteiramente fictícios;
- erros apresentados ao usuário não expõem detalhes internos;
- logs são sanitizados;
- atualizações de dependências passam por revisão e testes.

## Versões suportadas

Durante a fase inicial, apenas a versão mais recente da branch de desenvolvimento é considerada para correções. Uma política formal por versões será publicada antes da primeira release estável.
