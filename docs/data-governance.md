# Governança de dados

## Escopo permitido

O repositório aceita exclusivamente indicadores públicos agregados e dados
inequivocamente sintéticos. Dados clínicos reais, imagens, textos livres,
identificadores, tokens, certificados, endpoints de produção e payloads da
RNDS são proibidos em código, issues, logs, artefatos de CI e documentação.

Cada conjunto de dados deve ter um registro de proveniência com fonte, licença,
versão, checksum, granularidade, data de extração, responsável e limitações.
Dados sintéticos são rotulados `SYNTHETIC — NOT FOR CLINICAL USE OR
PRODUCTION`.

## LGPD e finalidade

Dados de saúde são pessoais sensíveis. Este laboratório evita seu tratamento;
ele não cria base legal para acessar dados individuais e não se apresenta como
órgão de pesquisa, controlador ou operador de bases assistenciais. A eventual
pesquisa institucional com dados pessoais exige finalidade definida, base legal
adequada, ambiente controlado, medidas proporcionais de segurança, avaliação
ética quando aplicável e regras do controlador. Resultados não podem revelar
dados pessoais.

Referências: [LGPD, arts. 11, 13 e 46](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm)
e [RNDS](https://www.gov.br/saude/pt-br/composicao/seidigi/rnds).

## Publicação e retenção

Interfaces públicas expõem somente métricas agregadas revisadas. Células com
menos de cinco ocorrências recebem supressão; antes da publicação, revisar
totais, cruzamentos, filtros e risco de diferenciação. Manter somente o mínimo
necessário para reproduzir o laboratório, aplicar retenção curta a artefatos de
execução e eliminar dados sintéticos temporários ao fim do uso.

Logs devem registrar metadados técnicos, nunca conteúdo clínico ou
identificadores. Segredos ficam fora do repositório, em variáveis protegidas ou
cofre apropriado.
