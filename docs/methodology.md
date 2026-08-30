# Metodologia

Este laboratório demonstra qualidade de dados, interoperabilidade e analytics
reproduzíveis com dados FHIR R4 inequivocamente sintéticos e indicadores
públicos agregados. Não recebe, consulta ou armazena registros individuais da
RNDS e não é um produto clínico.

## Pipeline e proveniência

O fluxo é `fonte -> validação de contrato -> camada canônica -> métricas
agregadas -> visualização`. Toda fonte deve registrar origem, licença, versão,
checksum, granularidade, data de extração e limitações. A camada bruta é
imutável; registros inválidos seguem para quarentena sintética com a regra que
falhou, nunca com dados reais.

As validações se dividem em estrutura FHIR/schema, semântica de códigos,
unidades e status, integridade referencial e consistência temporal. A execução
deve produzir contagens de entrada, aceitação, rejeição, duplicidade,
completude e latência, identificadas pela versão do código e do contrato.

## Qualidade e validação analítica

Cada regra possui descrição, severidade, limiar e ação. Falhas estruturais ou
referenciais são bloqueantes; inconsistências clínicas e temporais são
quarentenadas; campos opcionais ausentes são medidos. Dados agregados para
divulgação aplicam supressão primária abaixo de cinco registros. Essa medida
não impede inferência por totais ou cruzamentos: tabelas sensíveis também
exigem supressão complementar e revisão humana.

Modelos ou análises longitudinais devem separar treino, validação e teste no
tempo, usando validação rolling-origin. Quando houver geografia pública
agregada, a validação deve deixar áreas inteiras fora da amostra e evitar
vazamento entre áreas vizinhas. Pessoas, episódios ou entidades sintéticas não
podem ocorrer simultaneamente em treino e teste. Métricas devem incluir
baseline, incerteza e análise por subgrupo com tamanho suficiente.

## Testes e reprodutibilidade

O projeto usa testes unitários para transformações e regras, integração para o
pipeline completo com fixtures sintéticas e property-based tests para
idempotência, invariantes temporais e supressão. Falhas corrigidas tornam-se
casos de regressão. CI é offline por padrão: não baixa dados, não chama APIs da
RNDS e usa fixtures pequenas versionadas. A execução registra seeds,
dependências e versões para permitir reprodução.
