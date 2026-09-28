# ADR-0005 — Configuração segura, criptografia e gerenciamento de chaves

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O MeuFinanceiro armazenará credenciais de integrações, tokens e dados pessoais selecionados em instalações autohospedadas. Esses valores precisam de confidencialidade e integridade sem colocar a chave que os protege dentro do mesmo PostgreSQL.

A solução deve funcionar localmente, permitir rotação, falhar de forma explícita quando a configuração estiver ausente e evitar criptografia proprietária.

## Decisão

### Keyring externo

Cada instalação possui um arquivo JSON versionado fora do PostgreSQL:

```json
{"active_key_id":"k_example","keys":{"k_example":"base64url-256-bits"},"version":1}
```

O material real nunca é versionado. O ambiente contém somente `APP_KEYRING_FILE`, que aponta para o arquivo montado como secret read-only na API e no Worker.

Cada chave possui 256 bits gerados por `secrets.token_bytes`. A chave ativa cifra novos valores; chaves anteriores permanecem disponíveis apenas para decriptação até que um rewrap comprovado permita removê-las.

### Envelope criptográfico

Credenciais e tokens usam AES-256-GCM pela biblioteca `cryptography`, com:

- nonce aleatório de 96 bits por operação;
- tag de autenticação incorporada ao ciphertext;
- AAD obrigatório para vincular o valor ao contexto lógico, como residência, registro e campo;
- envelope JSON canônico com `version`, `algorithm`, `key_id`, `nonce` e `ciphertext`;
- algoritmo identificado como `A256GCM`;
- falha genérica de integridade para ciphertext, nonce, chave ou AAD incorretos.

O nonce nunca pode ser reutilizado com a mesma chave. Ele é gerado internamente e não pode ser fornecido pelo chamador.

### Rotação

Rotacionar o keyring:

1. gera nova chave aleatória;
2. define novo `active_key_id`;
3. preserva chaves anteriores;
4. grava o arquivo atomicamente;
5. exige restart dos processos para carregar o novo keyring.

O primitive `rewrap` decripta com a chave histórica e cifra novamente com a chave ativa. Remover uma chave antiga antes de reprocessar e validar todos os envelopes referenciados é proibido.

### Senhas

Hashes de senha usam Argon2id com o segundo perfil recomendado pela RFC 9106:

- memória: 64 MiB;
- iterações: 3;
- paralelismo: 4;
- salt: 128 bits;
- hash: 256 bits.

Não haverá pepper nesta fase. Uma futura adoção exigirá contrato de armazenamento, rotação e recuperação próprio.

### Redaction

Logs e diagnósticos aplicam redaction estrutural por nomes sensíveis e redaction textual para credenciais em URLs, headers de autorização e atribuições de token/senha. Exceções não podem ecoar material criptográfico, plaintext ou hashes completos.

### Permissões do arquivo

Em sistemas POSIX, `.secrets` usa modo `0700`. O keyring usa `0644` porque secrets baseados em arquivo no Docker Compose são bind mounts e a API/Worker usam UID fixo não-root. A proteção no host depende do diretório privado; dentro dos containers somente os serviços explicitamente autorizados recebem o arquivo, sempre read-only.

O arquivo não pode ser gravável por grupo ou outros. Em Windows, o script tenta restringir herança e acesso por ACL ao usuário atual.

## Alternativas consideradas

### Chave em variável de ambiente

Rejeitada porque aumenta exposição em inspeções de processo, dumps e ferramentas operacionais. O ambiente mantém apenas o caminho do arquivo.

### Chave dentro do PostgreSQL

Rejeitada porque um dump do banco conteria simultaneamente ciphertext e chave capaz de decriptá-lo.

### Fernet

Não adotado. É seguro para vários casos, mas o envelope explícito com AES-GCM oferece contrato de versão, AAD e `key_id` alinhado à rotação planejada.

### Vault, KMS ou HSM obrigatório

Não adotado na fundação por comprometer a instalação local simples e offline. Adaptadores externos podem ser adicionados futuramente sem mudar o formato dos envelopes.

### Criptografar todos os valores financeiros por campo

Rejeitado porque inviabilizaria consultas, agregações e relatórios eficientes. Disco, backups, anexos e campos sensíveis terão controles próprios.

## Consequências positivas

- chave separada do banco;
- integridade autenticada e contexto obrigatório;
- rotação sem perda silenciosa;
- primitives compartilhados entre API e Worker;
- configuração insegura bloqueia startup;
- parâmetros de senha explícitos e testáveis;
- logs possuem controle central de redaction.

## Consequências negativas e riscos

- perda do keyring torna os envelopes irrecuperáveis;
- backup precisa incluir keyring, banco e versão de forma coordenada;
- chaves antigas aumentam o impacto de exposição até o rewrap terminar;
- arquivo `0644` exige diretório pai privado no host;
- rotação requer restart e futura migração transacional dos envelopes persistidos;
- AES-GCM exige garantia estrita de nonce único por chave.

## Validação

- vetores de round-trip, AAD incorreto e adulteração;
- nonce novo para valores iguais;
- rotação preserva decriptação histórica;
- rewrap altera `key_id` sem perder plaintext;
- Argon2id verifica senha correta e rejeita senha incorreta;
- configuração ausente interrompe startup;
- redaction remove credenciais estruturais e textuais;
- CLI gera, valida e rotaciona sem imprimir material.

## Referências

- RFC 9106 — Argon2 Memory-Hard Function: <https://www.rfc-editor.org/rfc/rfc9106.html>
- `cryptography` — AEAD / AESGCM: <https://cryptography.io/en/latest/hazmat/primitives/aead/>
- `argon2-cffi` — PasswordHasher: <https://argon2-cffi.readthedocs.io/en/stable/api.html>
- Python `secrets`: <https://docs.python.org/3/library/secrets.html>
- Docker Compose secrets: <https://docs.docker.com/compose/how-tos/use-secrets/>
