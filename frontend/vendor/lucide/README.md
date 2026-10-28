# Lucide 0.468.0

SVGs originais de https://github.com/lucide-icons/lucide/tree/0.468.0/icons.
A licença completa está em `LICENSE`, incluindo atribuição Feather/MIT e Lucide/ISC.

`sprite.svg` contém apenas os 27 ícones utilizados pela interface, com aliases
`icon-*`. Somente o wrapper SVG foi convertido em `symbol`; a geometria é a original.
`manifest.json` registra nomes de origem e SHA-256 dos SVGs baixados. Os cinco SVGs
em `icons/` também atendem às máscaras CSS dos indicadores de status.

A interface usa `svg/use` e máscaras locais; não depende de CDN, fontes, JavaScript
da biblioteca ou build Node. Para atualizar, fixe uma versão oficial, preserve a
licença, reimporte os SVGs correspondentes e atualize o manifest e os testes de assets.
