# Protocolo de pesquisa computacional

## Registro do protocolo

| Campo | Especificação |
| --- | --- |
| Título | Avaliação reprodutível de qualidade e proveniência em pipeline FHIR R4 sintético alinhado conceitualmente à RNDS |
| Versão | 1.0.0 |
| Tipo de estudo | Experimento computacional controlado de engenharia de dados |
| População | Não aplicável: recursos e entidades inteiramente sintéticos |
| Dados públicos opcionais | Indicadores agregados publicados, analisados separadamente e apenas após registro de origem/checksum |
| Desfecho clínico | Não aplicável; não se estima diagnóstico, prognóstico, risco, tratamento ou benefício clínico |
| Acesso à RNDS | Nenhum; o projeto não se conecta, consulta, envia dados, é certificado ou homologado pela RNDS |

## Justificativa e pergunta

Pipelines de interoperabilidade precisam demonstrar propriedades técnicas antes de qualquer uso com dados reais: validade estrutural, coerência entre recursos, linhagem, repetibilidade e contenção de dados indevidos. A pergunta é: **o pipeline identifica defeitos rotulados e preserva resultados agregados de maneira reprodutível em dados FHIR R4 sintéticos?**

O contexto técnico vem da RNDS como infraestrutura oficial de interoperabilidade e do FHIR como padrão de modelagem descrito pelo Ministério da Saúde. A interpretação deste laboratório é deliberadamente limitada: [estrutura oficial da RNDS](https://www.gov.br/saude/pt-br/composicao/seidigi/rnds/estrutura-do-projeto), [IG FHIR R4 da RNDS](https://rnds-fhir.saude.gov.br/) e [FHIR R4 da HL7](https://hl7.org/fhir/R4/). Nenhuma dessas referências autoriza ou é substituída por esta implementação.

## Hipóteses, evidências e decisão

| ID | Hipótese operacional | Evidência pré-especificada | Critério de decisão |
| --- | --- | --- | --- |
| H1 | O validador detecta cenários deliberadamente inseridos | `evaluate-validator`: matriz por Bundle, por cenário e global; sensibilidade, especificidade, precisão e cobertura dos códigos esperados com IC95% de Wilson | reportar escopo, semente, amostras por classe, matriz e IC; falhas não detectadas abrem issue e não são ocultadas |
| H2 | Transformações são idempotentes | hashes, contagens e agregados iguais em duas execuções com mesma entrada/parâmetros | igualdade exata; divergência é falha de reprodutibilidade |
| H3 | Agregados não recebem recursos inválidos | reconciliação bronze/quarentena/silver/gold e teste de *fixture* inválida | zero registros inválidos em `gold` |
| H4 | Salvaguardas bloqueiam conteúdo vedado e células pequenas | scanner de padrões e testes de limiar de supressão | zero padrões proibidos; nenhuma célula abaixo do limiar é exibida |
| H5 | Regras não dependem de um único corte sintético | **planejada:** métricas por corte temporal, geográfico e de entidade | diferenças e IC apenas se os cortes e cálculos forem executados; não há extrapolação para ambiente real |

As hipóteses são testes de propriedades do software, não hipóteses sobre saúde de pessoas. Não haverá *p*-valor como porta de decisão; a evidência é composta por denominadores, estimativas, IC, versões, logs e artefatos reexecutáveis.

## Dados, DGP e tamanho de cenários

O cenário basal planejado deve conter no mínimo 1.000 pacientes sintéticos e recursos correspondentes nos cinco domínios demonstrativos (RAC, REL, RIA, RIRA e RPM), distribuídos por ao menos 12 competências e categorias territoriais sintéticas. O RPM é representado exclusivamente por `MedicationRequest` sintético, seguindo atributos estruturais inspirados no [modelo informacional RPM](https://rnds-guia.saude.gov.br/docs/rpm/mi-rpm/) e no [MedicationRequest FHIR R4](https://hl7.org/fhir/R4/medicationrequest.html), sem alegação de perfil oficial ou validade terapêutica. Para o benchmark atualmente implementado, há uma classe negativa `valid` e três classes positivas rotuladas em `Bundle.meta.tag`: `observation-temporal-reference`, `rpm-validity-window` e `service-request-occurrence`. A expansão de escala mantém três classes de cenários:

1. **Basal válido:** recursos que satisfazem os contratos locais e referências internas.
2. **Falhas unitárias:** cada regra tem ao menos uma instância com falha rotulada.
3. **Falhas compostas/adversariais:** múltiplas falhas no mesmo recurso e referências em cadeia quebradas.

O tamanho é uma escolha de precisão e cobertura de engenharia, não cálculo de poder clínico. Para cada métrica, o relatório exibirá o denominador efetivo e não apresentará porcentagens isoladas. A implementação corrente fixa semente e parâmetros, registra um rótulo de cenário por Bundle e avalia os três cenários nomeados; ela não afirma cobertura de todas as regras do catálogo, mutações independentes ou classes adversariais amplas. Uma alteração no DGP, contratos ou limiares incrementa a versão do cenário e exige reexecução completa.

## Plano de execução

1. Criar ambiente a partir de dependências bloqueadas e registrar versão de runtime.
2. Gerar conjuntos sintéticos por semente e salvar manifesto com hashes antes da validação.
3. Executar validação estrutural, de contrato, referencial, temporal e de privacidade.
4. Persistir problemas em quarentena; manter `rule_id`, severidade, recurso e hash, sem ecoar payload sensível. O *ground truth* é recuperável pela tag do Bundle e é usado pelo benchmark sem ser confundido com dado clínico.
5. Transformar somente itens elegíveis para modelo silver e *marts* gold agregados.
6. Reexecutar com mesma semente para teste de idempotência; executar cortes mantidos para validação temporal/geográfica/entidade.
7. Executar `academic-report` para medianas de espera de encaminhamento e turnaround laboratorial no lakehouse `SYNTHETIC_ONLY`, com bootstrap percentil bilateral de 95% (2.000 reamostragens por padrão). Executar `evaluate-validator` para as quatro classes de Bundles e IC95% de Wilson das proporções no nível do Bundle. Repetir com bloco por paciente sintético ou estratificação somente se essas extensões forem implementadas e registradas.
8. Executar testes unitários, de integração, de propriedade e de segurança; registrar versões, duração e resultados.
9. Inspecionar manualmente uma amostra de erros por regra para confirmar que a descrição não revela conteúdo proibido.

O `academic-report` usa gerador aleatório independente, semente publicada e reamostragem por evento para a mediana, com sementes distintas para as duas métricas. Efron introduziu o *bootstrap* como método de estimação de acurácia em [Annals of Statistics (1979)](https://doi.org/10.1214/aos/1176344552); aqui ele expressa variação da simulação e da reamostragem, não variabilidade amostral de uma população brasileira. O `evaluate-validator` usa o intervalo de Wilson bilateral de 95% para proporções binomiais da matriz de confusão; esse intervalo descreve apenas a amostragem finita dos Bundles sintéticos gerados.

## Análise e apresentação

### Análise primária

`evaluate-validator` produz TP, FP, FN e TN no nível do Bundle para cada cenário contra a mesma classe `valid` e para a combinação global; reporta sensibilidade, especificidade e precisão com IC95% de Wilson, além da cobertura dos códigos locais esperados. `academic-report` produz `n`, média, mediana, P90 e IC percentil bootstrap da mediana para `wait_days` e `turnaround_hours`, sem indicadores públicos. A tabela de evidência deve incluir versão, semente, denominador, unidade, método de IC e status de execução. Métricas sem denominador adequado serão `NA`, com justificativa, e nunca convertidas em zero.

### Análises de robustez

- Variação de semente: no mínimo três sementes independentes para cenários estáveis.
- Corte temporal: separar competências posteriores da configuração das regras.
- Corte geográfico: reter categorias territoriais sintéticas.
- Corte de entidade: reter IDs de organização/paciente sintéticos inteiros, sem vazamento entre cortes.
- Perturbação: aumentar taxa de falhas e combinações para verificar comportamento de quarentena.
- Privacidade: inserir padrões proibidos exclusivamente em *fixtures* de teste controlado e confirmar bloqueio/redação.

Gráficos e API exibem apenas agregados. Células com contagem abaixo do limiar configurado são suprimidas antes da resposta. Indicadores públicos agregados, caso presentes, terão painel separado e nunca servirão como validação externa do DGP.

### Desvios e mudanças

Qualquer desvio deste protocolo deve registrar data, justificativa, impacto, versão de código/contrato e se ocorreu antes ou após inspecionar resultados. Análises exploratórias devem ser marcadas como exploratórias. Não se permite alterar regras ou gerador apenas para elevar uma métrica sem registrar a mudança e repetir os cenários afetados.

## Validade, viés e generalização

O principal risco é o otimismo causado por conhecer a origem dos defeitos. A implementação atual usa *ground truth* controlado de três cenários e uma classe `valid`, portanto as métricas podem ser perfeitas nesse próprio gerador e ainda não generalizar. Mutações independentes, cortes não vistos e classes adversariais amplas são extensões planejadas que devem ser marcadas como não executadas até terem evidência. Ainda assim, resultados não são generalizáveis para dados reais, sistemas reais, municípios, serviços ou RNDS. Sem dados individuais e sem desfechos clínicos, não há inferência clínica, causal ou epidemiológica.

Há também risco de dependência intrapaciente sintético, deriva de versão e falsa sensação de conformidade. As mitigações previstas são, respectivamente, *bootstrap* em bloco se executado; manifesto/hashes/reexecução; e avisos explícitos de que validação local não substitui perfil RNDS, terminologia, segurança, credenciamento ou homologação. A página oficial do IG declara status **Informative**: [RNDS FHIR](https://rnds-fhir.saude.gov.br/).

STROBE orienta a transparência de desenho, participantes/unidades, variáveis, viés, tamanho, métodos estatísticos e limitações, sem transformar este experimento em estudo observacional: [STROBE original](https://doi.org/10.1371/journal.pmed.0040296). TRIPOD será aplicável apenas se um modelo de predição individual for introduzido: [TRIPOD original](https://doi.org/10.1136/bmj.g7594).

## Ética, privacidade e disseminação

O protocolo é restrito a dados sintéticos e agregados públicos. Não há recrutamento, intervenção, contato humano, dados pessoais, dados sensíveis ou ligação de bases. Por isso, este protocolo não presume aprovação ética para um projeto futuro que mude esse escopo. Antes de incluir qualquer dado pessoal, o estudo deve pausar para revisão institucional/ética e avaliação de conformidade; dados de saúde são dados pessoais sensíveis na [LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm).

A disseminação inclui código, testes, contratos, manifestos e métricas agregadas, sob licença declarada. Segue-se FAIR de maneira proporcional, com identificadores de versão, metadados de origem, formatos interoperáveis e instruções de reuso; FAIR não exige abertura de dado pessoal. Referências: [GO FAIR](https://www.gofair.foundation/fair-principles) e [Wilkinson *et al.* (2016)](https://doi.org/10.1038/sdata.2016.18).

## Relato mínimo por execução

Cada relatório de execução deve publicar: objetivo, versão do protocolo; hash de commit; versões de dependências; hash de contratos; origem e checksum de quaisquer indicadores públicos; DGP, semente e parâmetros; fluxo bronze→quarentena→silver→gold; métricas com denominadores, unidade e método de IC; resultados dos testes; desvios; limitações; e a declaração de que não houve acesso à RNDS ou dados de pacientes. Para o benchmark, publicar as quatro classes, a decisão `Bundle rejeitado`, a matriz de confusão e os cenários efetivamente avaliados.
