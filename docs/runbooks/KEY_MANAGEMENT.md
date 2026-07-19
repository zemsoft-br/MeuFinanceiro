# Gerenciamento do keyring local

## Escopo

Este runbook opera a chave mestra utilizada para cifrar credenciais e tokens. Ele não substitui o backup completo da instalação e nunca deve ser executado com dados reais sem backup validado.

Caminho padrão:

```text
.secrets/keyring.json
```

O arquivo não pertence ao PostgreSQL, não entra em imagens e não pode ser versionado.

## Inicialização

Os scripts `dev-up` inicializam automaticamente uma instalação nova. Para operação explícita:

```bash
python3 infra/scripts/manage-secrets.py init
```

O comando falha quando o arquivo já existe. Não existe sobrescrita silenciosa.

## Validação

```bash
python3 infra/scripts/manage-secrets.py validate
```

A saída contém somente versão, identificador ativo e quantidade de chaves. Material Base64, plaintext e ciphertext não são exibidos.

## Rotação

Antes da rotação:

1. pare mutações que criem ou alterem envelopes;
2. faça backup coordenado do PostgreSQL e do keyring;
3. valide que o backup pode ser restaurado;
4. registre o `active_key_id` atual.

Execute:

```bash
python3 infra/scripts/manage-secrets.py rotate
```

Depois:

1. reinicie API e Worker;
2. confirme health checks;
3. verifique que envelopes antigos ainda decriptam;
4. novos envelopes devem usar o novo `active_key_id`;
5. execute o rewrap transacional quando a persistência existir;
6. somente remova chave antiga após inventário provar zero referências e um backup adicional ter sido validado.

A CLI desta fase preserva todas as chaves antigas e não oferece remoção.

## Restore

O banco e o keyring precisam pertencer ao mesmo ponto de recuperação. Restaurar apenas um deles pode produzir envelopes indecriptáveis ou referência a chaves inexistentes.

Procedimento mínimo:

1. pare os serviços;
2. restaure `.secrets/keyring.json` no caminho configurado;
3. restaure o PostgreSQL correspondente;
4. execute `manage-secrets.py validate`;
5. inicie os serviços;
6. valide health checks e uma amostra controlada de envelopes.

## Permissões

Linux, macOS e WSL:

```bash
chmod 700 .secrets
chmod 644 .secrets/keyring.json
```

O arquivo é legível porque o Compose o monta em processos não-root com UID fixo. O diretório `0700` impede descoberta e abertura pelo restante dos usuários do host. O arquivo nunca pode ser gravável por grupo ou outros.

No Windows, `dev-up.ps1` tenta remover herança e conceder controle ao usuário atual. Revise a ACL manualmente em hosts compartilhados.

## Incidente de perda ou exposição

### Perda sem backup

Não existe recuperação criptográfica. Credenciais e tokens cifrados se tornam irrecuperáveis e precisam ser reconectados ou recriados.

### Suspeita de exposição

1. preserve evidências sem copiar material para issues ou logs;
2. rotacione o keyring;
3. reinicie serviços;
4. revogue tokens e credenciais nos provedores;
5. reprocesse envelopes para a chave nova;
6. valide backups e investigue o vetor de acesso;
7. trate a remoção da chave comprometida como migração separada.

Nunca envie keyring, `.env`, dumps, tokens ou ciphertext associado a dados reais em issues públicas.
