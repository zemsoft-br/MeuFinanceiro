# Referências visuais do Google Stitch

Este diretório disponibiliza as capturas do Google Stitch para colaboradores do MeuFinanceiro.

## Estrutura

- `contact-sheets/`: cinco folhas de contato para navegação rápida no GitHub;
- `archives/`: cinco pacotes temáticos com os 62 PNGs originais válidos;
- `index.csv`: inventário global com dimensões, tamanho e SHA-256 de cada captura;
- `SHA256SUMS`: checksums dos arquivos publicados.

## Fonte

```text
stitch_meufinanceiro_core_foundation(10).zip
sha256 = 14971a03416a47299b60d0c30f9ab83f9d52c3f48f9ee24d835ac6a29bc61ab0
```

Os pacotes preservam os PNGs válidos byte a byte. O ZIP bruto completo e os HTMLs gerados não são código-fonte do produto.

## Capturas ausentes

Dois `screen.png` da exportação tinham somente 28 bytes e não eram imagens válidas:

- `or_amentos_meufinanceiro`;
- `recorr_ncias_e_assinaturas_meufinanceiro`.

O inventário canônico mantém o HTML como referência temporária para essas duas experiências.

## Regras de uso

- material de referência de UX, layout, densidade, estados e responsividade;
- não define regras financeiras, autorização ou arquitetura;
- não comprova acessibilidade, segurança ou integração;
- não copiar HTML, Tailwind CDN, Google Fonts ou URLs remotas para o Flutter;
- elementos de terceiros visíveis nas capturas não devem ser extraídos como assets produtivos sem verificação de licença.

A implementação canônica permanece definida pelos ADRs e contratos em `docs/`.
