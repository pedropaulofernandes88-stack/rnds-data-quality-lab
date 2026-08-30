# Catálogo de regras de qualidade

As regras são executáveis e versionadas com o código. “Bloqueante” significa
que o Bundle sintético inteiro não avança à Bronze; não expressa gravidade
clínica. Mensagens e relatórios não carregam valores do payload.

## Bundle FHIR sintético

| Código | Dimensão | Regra | Ação | Evidência |
| --- | --- | --- | --- | --- |
| `structure.schema` | conformidade | Bundle atende ao subconjunto JSON Schema distribuído | quarentena do Bundle | `test_validation.py` |
| `structure.missing_resource` | completude | os nove tipos esperados estão presentes | quarentena | `test_validation.py` |
| `structure.duplicate_resource` | unicidade | tipo/ID não se repete no Bundle | quarentena | `test_validation.py` |
| `semantic.synthetic_tag` | classificação | todo recurso possui marcador `SYNTHETIC` | quarentena | `test_synthetic.py`, `test_validation.py` |
| `semantic.rnds_model_tag` | interoperabilidade | recursos RAC/REL/RIA/RIRA/RPM/Provenance possuem tag demonstrativa correspondente | quarentena | `test_validation.py` |
| `privacy.forbidden_field` | privacidade | `identifier`, `name`, `address`, `telecom`, `photo` e `text` não aparecem em nenhum nível | quarentena | `test_validation.py` |
| `semantic.observation_value` | semântica | Observation laboratorial possui `valueQuantity` | quarentena | `test_validation.py` |
| `semantic.service_request_intent` | semântica | ServiceRequest usa `intent=order` | quarentena | `test_validation.py` |
| `semantic.medication_request_*` | semântica/temporal | MedicationRequest sintético usa `status=active`, `intent=order`, medicamento codificado, dispensação estruturada e vigência coerente | quarentena | `test_validation.py` |
| `reference.unresolved` | integridade | toda referência resolve dentro do Bundle | quarentena | `test_validation.py`, `test_pipeline.py` |
| `temporal.encounter_period` | temporalidade | fim do Encounter não antecede o início | quarentena | `test_validation.py` |
| `temporal.observation_issued` | temporalidade | emissão do resultado não antecede sua data efetiva | quarentena | `test_validation.py`, `test_pipeline.py` |
| `temporal.immunization_birth` | temporalidade | imunização não antecede nascimento sintético | quarentena | `test_validation.py` |
| `temporal.service_request_*` | temporalidade | conclusão não antecede solicitação e espera declarada reconcilia com o intervalo | quarentena | `test_validation.py` |

## Indicadores RNDS públicos

Cada arquivo `sdigi` deve satisfazer todos os controles antes de qualquer
inserção:

1. URL HTTPS absoluta terminada em `.csv.zip`, sem credenciais ou
   redirecionamento;
2. resposta e CSV descompactado abaixo dos limites configurados, ZIP não
   criptografado e com exatamente um CSV;
3. presença das colunas contratadas, sem nulos obrigatórios, competência
   `AAAAMM` e granularidade `UF`;
4. unicidade `competência × UF`, exatamente 27 UFs em cada competência e
   valores não negativos;
5. um único total regional por `competência × região` e um único total Brasil
   por competência;
6. soma das UFs igual ao total regional e Brasil, com tolerância absoluta de
   0,5 para representação numérica;
7. SHA-256, bytes, competências e instante de carga registrados; arquivo bruto
   mantido fora do Git.

Testes usam ZIP em memória e `httpx.MockTransport`; nenhuma fonte é chamada no
CI.

## Invariantes pós-carga

`rnds-lab audit` falha com código de saída diferente de zero quando encontra:

- recurso Bronze sem classificação sintética;
- fato de encontro, condição, laboratório, imunização, regulação ou prescrição sem Patient
  correspondente;
- turnaround laboratorial, espera regulatória, quantidade ou duração de prescrição negativos;
- indicador público negativo ou total UF/região acima do Brasil;
- execução marcada como concluída sem timestamp de conclusão.

Transação e rollback, idempotência, supressão de células pequenas, ausência de
payload na quarentena, limite da API e comportamento positivo/negativo da
auditoria têm testes de integração próprios.

## Ground truth e avaliação do validador

O benchmark `rnds-lab evaluate-validator` é separado da auditoria do
lakehouse. Ele avalia a decisão local `Bundle rejeitado` contra quatro classes
de Bundles sintéticos: `valid` (negativa), `observation-temporal-reference`,
`rpm-validity-window` e `service-request-occurrence` (positivas). Cada cenário
é identificado por uma tag controlada no `Bundle` e espera códigos do catálogo
local; a avaliação registra TP, FN, FP, TN no nível do Bundle, cobertura dos
códigos esperados e IC95% de Wilson para sensibilidade, especificidade e
precisão.

Esses rótulos não são terminologia RNDS nem veredito de conformidade FHIR. O
resultado não mede sensibilidade clínica, qualidade da RNDS ou desempenho de
implementações externas. Para executar e preservar a evidência:

```powershell
uv run rnds-lab evaluate-validator --output artifacts/validator-evaluation.json --samples-per-class 100 --seed 20260829
```

O comando `rnds-lab academic-report` é uma verificação analítica distinta: ele
recusa Bronze não sintética e calcula somente estatísticas agregadas de
`fact_referral.wait_days` e `fact_lab_result.turnaround_hours`, sem payload,
sem indicadores públicos e sem alterar os fatos. Seu bootstrap percentil de
mediana não avalia as regras deste catálogo nem substitui a auditoria.

## Gestão de mudança

Uma alteração de regra exige caso de regressão e avaliação de compatibilidade.
Mudanças que alterem aceitação, projeção ou interpretação devem atualizar
`contract_version`, fixtures, dicionário e exemplos. Taxas entre versões de
contrato não são diretamente comparáveis sem reprocessar a mesma entrada.
