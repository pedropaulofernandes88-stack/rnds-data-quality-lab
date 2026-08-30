# Metodologia acadêmica e critérios de evidência

## Escopo e posição epistemológica

Este repositório é um laboratório de engenharia de dados, não um estudo clínico nem um conector de produção. Ele avalia propriedades mensuráveis de uma cadeia de dados **inteiramente sintética** e, separadamente, a leitura opcional de indicadores públicos agregados. Não contém, solicita ou infere dados de pacientes; não possui credenciais, ambiente, certificação, homologação ou acesso à Rede Nacional de Dados em Saúde (RNDS). Portanto, seus resultados não demonstram desempenho da RNDS, de estabelecimentos de saúde, de profissionais ou de cuidado clínico.

O alinhamento técnico é conceitual: a documentação oficial informa que a RNDS usa FHIR e descreve, entre outros, RAC, REL, RIA, RIRA e o Registro de Prescrição de Medicamentos (RPM). Neste laboratório, `MedicationRequest` FHIR R4 é mapeado apenas de forma demonstrativa ao RPM. O Guia de Implementação RNDS publicado é marcado como **Informative**, devendo ser tratado como referência de modelagem e não como certificado de conformidade. As especificações de perfil, terminologia, autenticação e homologação da RNDS permanecem responsabilidade de uma integração formal fora deste laboratório.

Fontes de autoridade:

- Ministério da Saúde, [RNDS](https://www.gov.br/saude/pt-br/composicao/seidigi/rnds) e [estrutura do projeto](https://www.gov.br/saude/pt-br/composicao/seidigi/rnds/estrutura-do-projeto).
- Ministério da Saúde, [Guia de Implementação RNDS FHIR R4](https://rnds-fhir.saude.gov.br/) e [guia de integração](https://rnds-guia.saude.gov.br/docs/introducao/).
- Ministério da Saúde, [modelo informacional do RPM](https://rnds-guia.saude.gov.br/docs/rpm/mi-rpm/) e [objetivo do RPM](https://rnds-guia.saude.gov.br/docs/rpm/objetivo-rpm/).
- HL7, [FHIR R4](https://hl7.org/fhir/R4/), [MedicationRequest](https://hl7.org/fhir/R4/medicationrequest.html) e [Provenance](https://hl7.org/fhir/R4/provenance.html).

## Pergunta e objetivos

**Pergunta primária.** Em coleções FHIR R4 sintéticas, com defeitos conhecidos e rastreáveis, em que medida um pipeline versionado consegue preservar a proveniência, identificar violações estruturais/semânticas e produzir agregados reprodutíveis sem expor dados identificáveis?

**Objetivo primário.** Medir a qualidade de detecção e a estabilidade operacional do pipeline contra um *ground truth* criado pelo próprio gerador sintético.

**Objetivos secundários.**

1. Medir completude, validade, consistência referencial, pontualidade e unicidade por tipo de recurso e por domínio sintético (RAC, REL, RIA, RIRA, RPM).
2. Comparar métricas entre cortes temporal, geográfico e de entidade sintéticos sem usar esses cortes como evidência sobre pessoas ou locais reais.
3. Verificar idempotência, linhagem e reprodutibilidade de artefatos e agregados.
4. Avaliar se salvaguardas de privacidade (ausência de identificadores e supressão de células pequenas) se mantêm após transformações.

Não há desfecho de diagnóstico, prognóstico, tratamento ou efetividade clínica. Caso uma versão futura inclua um modelo preditivo individual, seu protocolo deverá ser separado e relatar desenvolvimento/validação segundo [TRIPOD](https://doi.org/10.1136/bmj.g7594); esta versão não aplica TRIPOD como evidência de validade clínica.

## Desenho e unidade de análise

O desenho é um experimento computacional controlado de engenharia de dados: geração determinística, injeção de falhas conhecida, execução do pipeline e inspeção de resultados. Os cenários inválidos são rotulados em `Bundle.meta.tag` com sistema controlado do laboratório. O comando `evaluate-validator` usa esses rótulos para uma avaliação de classificação no nível do Bundle; o comando `academic-report` descreve eventos já aceitos no lakehouse. As unidades de análise são:

| Nível | Unidade | Uso analítico |
| --- | --- | --- |
| Recurso | Um recurso FHIR sintético | regras de formato, campos obrigatórios, terminologia e referências |
| Relação | Uma referência entre recursos no mesmo conjunto | integridade referencial e coerência temporal |
| Execução | Um `run_id` com parâmetros, versão e hash | reprodutibilidade, idempotência e cobertura de falhas |
| Agregado | Uma célula mensal/domínio/UF sintética | métricas operacionais e supressão de células pequenas |

O estudo não faz amostragem de indivíduos reais. Quando indicadores públicos agregados forem baixados opcionalmente, a unidade passa a ser a linha publicada pelo órgão de origem; eles entram somente em um *mart* separado, com fonte, data de atualização e checksum. Não serão unidos a recursos sintéticos para inferência causal, clínica ou individual.

## Gerador de processos de dados (DGP) sintético

O DGP usa uma semente explícita, versão do gerador e configurações serializadas. Cada execução produz identificadores pseudorrandômicos não derivados de pessoas, nomes, documentos, endereços, telefones, e-mails, CPF, CNS, CNES ou dados de prontuário reais. Todo recurso recebe marca sintética e uma cadeia `Provenance` para que o dado seja inequivocamente não clínico.

1. Sorteiam-se entidades abstratas: paciente sintético, organização sintética, competência mensal e UF sintética (códigos de categoria, não estabelecimentos reais).
2. Criam-se recursos FHIR R4 de domínio: `Encounter`/`Condition` para RAC, `Observation` para REL, `Immunization` para RIA, `ServiceRequest` para RIRA e `MedicationRequest` para RPM. O último contém medicamento, via, dose, frequência, quantidade e janela de vigência **sintéticos**. Referências apontam apenas para IDs do mesmo conjunto.
3. São impostas dependências plausíveis de engenharia: evento clínico antecede observação; `effective` não sucede indevidamente `issued`; recursos referenciados existem; campos codificados têm `system` e `code` quando a regra os exige.
4. Há três cenários inválidos, pequenos e determinísticos, com uma tag de *ground truth* por Bundle: `observation-temporal-reference` (ordem temporal inválida em `Observation` e referência inexistente em `ServiceRequest`), `rpm-validity-window` (fim de vigência anterior à autoria em `MedicationRequest`) e `service-request-occurrence` (ocorrência anterior à autoria). A quarentena registra regras observadas, sem payload. `--invalid-every` escolhe periodicamente um desses cenários pela semente; `evaluate-validator` os solicita nominalmente.
5. O pipeline separa bronze (payload e hash), quarentena (problemas) e silver/gold (projeções e agregados). Recursos inválidos não entram em agregados de produção da demonstração.

O DGP não pretende reproduzir prevalências, incidências, fluxos assistenciais ou distribuição geográfica brasileira. Ele foi desenhado para teste de propriedades de dados e deve ser ampliado por cenários, nunca ajustado para simular ou representar população real sem protocolo específico.

## Desfechos e métricas

Para o benchmark do validador, seja (B) o conjunto de Bundles, (y_b\in\{0,1\}) a classe de *ground truth* e \(\hat y_b\) a decisão `Bundle rejeitado`. A classe negativa é `valid`; as três classes positivas são os cenários descritos acima. O relatório também verifica se o conjunto de códigos esperado para cada cenário está contido nas regras retornadas pelo validador.

| Propriedade | Definição | Estimador |
| --- | --- | --- |
| Sensibilidade do Bundle | Bundles positivos rejeitados | TP / (TP + FN) |
| Especificidade do Bundle | Bundles `valid` aceitos | TN / (TN + FP) |
| Precisão do Bundle | rejeições que pertencem a cenário positivo | TP / (TP + FP) |
| Cobertura de regra esperada | Bundles de cenário que contêm todos os códigos locais esperados | detecções / Bundles elegíveis |
| Completude | elementos não ausentes entre os aplicáveis | presentes / aplicáveis |
| Validade | elementos conformes à regra | conformes / avaliáveis |
| Integridade referencial | referências resolvíveis | referências resolvidas / referências avaliadas |
| Pontualidade | eventos no limite de latência configurado | pontuais / eventos datados |
| Idempotência | repetição não altera resultado canônico | igualdade de hashes e contagens |
| Privacidade operacional | ocorrências bloqueadas | contagem de padrões proibidos; deve ser zero |

`academic-report` implementa IC bilateral de 95% por *bootstrap* percentil não paramétrico para a **mediana** de `wait_days` e `turnaround_hours`: 2.000 reamostragens por padrão, percentis 2,5/97,5 e sementes explícitas (a segunda métrica usa `seed + 1`). A unidade é cada evento aceito dessas duas tabelas sintéticas; não há estratificação, modelo causal, comparação entre UFs ou inferência populacional. Valores ausentes são excluídos e `n` é reportado. O relatório é determinístico para a mesma entrada, semente e versão de NumPy, e falha se a Bronze tiver recurso não sintético. A base metodológica é Efron (1979), [doi:10.1214/aos/1176344552](https://doi.org/10.1214/aos/1176344552).

`evaluate-validator` implementa matriz TP/FN/FP/TN no nível do Bundle, por cenário e globalmente. Para sensibilidade, especificidade, precisão e cobertura de códigos esperados, usa IC bilateral de Wilson de 95%; não usa o bootstrap. A incerteza desses ICs é a da amostragem finita do experimento sintético controlado, não variabilidade de uma população brasileira ou de uma RNDS real.

Não serão feitas comparações de significância entre UFs, instituições ou populações reais. Se cenários sintéticos rotulados e o cálculo estatístico forem executados, diferenças entre eles poderão ser reportadas como diferença absoluta, razão quando definida, IC por *bootstrap* e tamanho do denominador.

## Estratégia de validação

As validações de generalização são de engenharia, não validações externas clínicas.

| Corte | Separação exigida | Pergunta que responde |
| --- | --- | --- |
| Temporal | competências sintéticas posteriores não participam do ajuste de regras | regras e agregados permanecem estáveis diante de nova janela? |
| Geográfico | categorias de UF/região sintéticas distintas em avaliação | a parametrização independe da categoria territorial sintética? |
| Entidade | organizações e pacientes sintéticos sem sobreposição entre desenvolvimento e avaliação | a validação não depende de IDs previamente vistos? |
| Perturbação | combinações e severidades de erro não vistas | a cobertura persiste sob defeitos compostos? |

Os testes de contrato distinguem: (a) sintaxe FHIR, (b) restrições do contrato local, (c) coerência entre recursos e (d) restrições de privacidade do laboratório. A validação local não substitui validação de perfil, terminologia ou credenciamento RNDS. O papel de `Provenance` é registrar origem e transformação de artefatos, coerente com a especificação [HL7 FHIR Provenance](https://hl7.org/fhir/R4/provenance.html).

## Ameaças à validade e mitigação

| Ameaça | Consequência | Mitigação e limite residual |
| --- | --- | --- |
| Realismo limitado do DGP | métricas podem ser otimistas | falhas conhecidas e declaração explícita de não representatividade; cenários adversariais são uma extensão protocolar, não uma cobertura já presumida |
| Acoplamento gerador-validador | regras podem refletir o mesmo pressuposto | manter contratos e gerador versionados, incluir *fixtures* manuais e mutações independentes |
| Dependência entre recursos | IC de mediana por evento pode ser estreito | relatório explicita unidade por evento; *bootstrap* em bloco por paciente sintético é extensão futura, não resultado atual |
| Mudança de versão FHIR/IG | conclusões deixam de valer | registrar URL, versão, data de acesso e hash de contratos; reexecutar matriz após atualização |
| Agregação e células pequenas | leitura instável ou revelação indireta | limiar de supressão, sem exportação linha a linha e sem cruzamento com fontes externas |
| Indicadores públicos atualizados | não reprodutibilidade da fonte | manifesto de origem, data, licença, checksum e cópia local opcional, sem confundir atualização com erro |
| Confusão com integração oficial | alegação indevida de conformidade | avisos permanentes: sem acesso, certificação, homologação ou envio à RNDS |

Diretrizes STROBE são usadas como referência de transparência de descrição do desenho, dados, vieses e limitações, não como selo de estudo observacional clínico. Veja [STROBE](https://doi.org/10.1371/journal.pmed.0040296) e sua [explicação](https://doi.org/10.1371/journal.pmed.0040297). Para trabalhos futuros com dados rotineiramente coletados e autorizados, deve-se considerar [RECORD](https://doi.org/10.1371/journal.pmed.1001885), além de aprovação ética e bases legais aplicáveis.

## Reprodutibilidade, governança e FAIR

Cada execução deve registrar: versão do código e dos contratos, Python e dependências bloqueadas, semente, parâmetros, UTC, hash de entrada, hash de saída, contagens bronze/quarentena/silver/gold, estratégia de lote e origem dos agregados públicos. Para `academic-report`, registrar também `n`, reamostragens, nível de confiança, sementes e versão de NumPy; para `evaluate-validator`, registrar semente, amostras por classe, classes e matriz de confusão. As execuções devem ser reproduzíveis em clone limpo por comando documentado e testadas em integração contínua, sem rede para o núcleo sintético. O template [de evidência de validação](evidence/latest-validation.md) distingue campos observados de campos ainda não medidos.

O repositório persegue FAIR de forma proporcional ao escopo: metadados ricos e identificadores de versão (Findable), arquivos e licenças explícitos (Accessible), FHIR/JSON/contratos versionados (Interoperable) e licença, proveniência, semente e instruções de reexecução (Reusable). FAIR não significa que dados devem ser abertos; tampouco substitui proteção de dados. Referências: [FAIR Guiding Principles](https://www.gofair.foundation/fair-principles) e Wilkinson *et al.* (2016), [doi:10.1038/sdata.2016.18](https://doi.org/10.1038/sdata.2016.18).

O desenho segue minimização por opção arquitetural: nenhum dado pessoal é necessário. Caso o escopo mude para dados pessoais, dados de saúde são sensíveis segundo a [LGPD, Lei nº 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm), exigindo reavaliação jurídica, ética, técnica e organizacional antes de qualquer ingestão.

## Critérios de aceitação acadêmica

Uma entrega só é considerada metodologicamente completa se: (1) DGP, semente e perturbações efetivamente usadas forem recuperáveis; (2) cada métrica publicada trouxer numerador, denominador, unidade e método de IC quando houver; (3) resultados sintéticos e indicadores públicos permanecerem separados; (4) cada afirmação estiver restrita ao experimento executado; (5) testes de repetição e de privacidade passarem; e (6) limitações e mudanças de versão forem publicadas junto ao resultado.
