# Fontes de dados

Este laboratório trabalha exclusivamente com indicadores públicos agregados e
eventos FHIR inteiramente sintéticos. Ele não acessa a RNDS, não é homologado
nem certificado pelo Ministério da Saúde e não deve receber dados assistenciais,
identificadores de pessoas, certificados ou tokens.

O manifesto em `sources.yml` é a fonte de verdade para procedência, licença,
granularidade, frequência e limitações. Antes de qualquer publicação, confira a
licença vigente no portal de origem: os portais de Dados Abertos do SUS
consultados declaram Creative Commons Atribuição-SemDerivações 3.0, o que pode
restringir a redistribuição de dados transformados.

## Atualização reproduzível

1. Execute a atualização de dados somente de forma manual ou agendada, nunca
   como parte dos testes de pull request.
2. Registre URL final, data/hora UTC, versão/competência, licença e SHA-256 do
   arquivo obtido.
3. Use `download_csv_zip` somente para URLs HTTPS de CSV compactado, com teto
   explícito de bytes e timeout. O downloader grava em arquivo temporário e só
   substitui o destino após concluir a transferência.
4. Agregue notificações antes de qualquer saída pública; não inclua microdados
   em Git, imagens de documentos clínicos ou identificadores pessoais.
5. Em CI, use apenas fixtures sintéticas em memória. Testes de rede devem ser
   marcados como opcionais e executados fora do fluxo normal.

Para séries de dengue, preserve o ano e o checksum do arquivo de origem: o
próprio portal informa que bases recentes podem ser revisadas e que as séries
históricas usam congelamentos anuais. Para taxas, use o código municipal como
texto e documente a versão do denominador do IBGE.

## Indicadores RNDS

Os códigos `sdigi008`, `sdigi009`, `sdigi010`, `sdigi011`, `sdigi013`,
`sdigi014` e `sdigi015` representam indicadores públicos agregados listados no
manifesto. Eles servem para contexto de cobertura e adoção. Não permitem
inferência sobre pacientes, atendimentos individuais ou desempenho clínico.
