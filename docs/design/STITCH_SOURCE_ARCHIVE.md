# Manifesto da exportação-fonte do Google Stitch

- Issue: #22
- Estado: arquivo bruto mantido fora do histórico Git
- Finalidade: rastreabilidade da auditoria visual e funcional

## Exportação auditada

```text
filename = stitch_meufinanceiro_core_foundation(10).zip
size_bytes = 14863523
archive_entries = 201
expanded_bytes_reported_by_zip = 16598769
sha256 = 14971a03416a47299b60d0c30f9ab83f9d52c3f48f9ee24d835ac6a29bc61ab0
```

A auditoria em `STITCH_AUDIT.md` e o inventário em `STITCH_SCREEN_INVENTORY.csv` foram produzidos a partir dessa exportação.

## Política de armazenamento

O ZIP bruto não é versionado diretamente no repositório porque contém:

- HTML gerado pelo Stitch;
- capturas PNG e outros arquivos binários;
- referências a assets externos;
- dependências de CDN;
- material que ainda precisa de revisão de origem e licença antes de publicação pública;
- volume desnecessário para o histórico Git comum.

O arquivo original deve ser preservado em armazenamento privado do projeto, com o nome e hash acima.

Opções adequadas incluem:

- pasta privada do projeto no OneDrive ou Google Drive;
- armazenamento interno de artefatos;
- release privada ou outro repositório de artefatos com controle de acesso.

Não utilizar Git LFS ou release pública antes da revisão de licenças e da remoção de assets externos não autorizados.

## Verificação

Para confirmar que uma cópia é a mesma exportação auditada:

```bash
sha256sum 'stitch_meufinanceiro_core_foundation(10).zip'
```

Resultado esperado:

```text
14971a03416a47299b60d0c30f9ab83f9d52c3f48f9ee24d835ac6a29bc61ab0
```

No PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 '.\stitch_meufinanceiro_core_foundation(10).zip'
```

## Conteúdo versionado no repositório

O repositório preserva apenas os artefatos derivados necessários para implementação:

- auditoria estrutural;
- inventário canônico de telas;
- arquitetura de informação;
- contratos financeiros;
- dados demonstrativos reconciliados;
- decisões arquiteturais.

Esses documentos são a autoridade de implementação. O ZIP permanece referência histórica e visual, não código-fonte.

## Publicação futura

Uma publicação pública poderá ser considerada somente após:

1. remover dependências de CDN e referências remotas desnecessárias;
2. verificar licenças de imagens, fontes e ícones;
3. remover qualquer dado ou identificador inadequado;
4. produzir um pacote sanitizado;
5. registrar novo hash e versão;
6. aprovar explicitamente sua distribuição.
