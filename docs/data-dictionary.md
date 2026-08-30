# Dicionário de dados

Este dicionário descreve o DuckDB local. As linhas clínicas são inteiramente sintéticas; a única fonte externa é um conjunto de indicadores RNDS agregados por UF. IDs são técnicos e determinísticos, não identificadores de pessoas ou estabelecimentos reais.

## Controle de execução e Bronze

| Objeto | Campos principais | Significado |
| --- | --- | --- |
| `ingestion_runs` | `run_id`, `seed`, `requested_patients`, `source_sha256`, `contract_version`, contagens, `status`, timestamps | Ledger da execução. `quarantined_count` conta recursos em Bundles rejeitados; `quality_issue_count` conta regras violadas. |
| `bronze_resources` | `resource_key`, `resource_type`, `resource_id`, `model`, `patient_ref`, `uf_code`, `event_at`, `synthetic`, `payload_json`, `payload_sha256`, `first_run_id` | Recurso FHIR aceito e serializado canonicamente. A chave combina tipo, ID e hash. |
| `quality_issues` | `issue_key`, `run_id`, `resource_type`, `resource_id`, `code`, `severity`, `message_digest`, `observed_at` | Falha sem payload ou valor clínico. A mensagem é armazenada como hash. |

`payload_json` é artefato local sintético, não uma interface para dados individuais. `source_sha256` da execução é hash da lista ordenada de hashes dos recursos aceitos: detecta repetição de conteúdo, não atesta fonte externa. O par `resource_type × resource_id` é único; o mesmo ID com hash diferente falha explicitamente em vez de deixar a Silver desatualizada.

## Silver: dimensões e fatos sintéticos

| Tabela | Grão | Campos analíticos |
| --- | --- | --- |
| `dim_patient` | um Patient sintético | `patient_id`, `birth_date`, `gender`, `uf_code`, `first_run_id` |
| `dim_organization` | uma Organization sintética | `organization_id`, `uf_code`, `organization_kind`, `first_run_id` |
| `fact_encounter` | um Encounter sintético | paciente, organização, início/fim, `status`, `care_type`, UF |
| `fact_condition` | um Condition sintético | paciente, encontro, sistema/código, `recorded_at` |
| `fact_lab_result` | um Observation de laboratório sintético | paciente, encontro, código, efetivação/emissão, categoria, `turnaround_hours` |
| `fact_immunization` | uma Immunization sintética | paciente, organização, ocorrência, vacina, dose, UF |
| `fact_referral` | um ServiceRequest sintético | paciente, encontro, organização, solicitação/conclusão, status, prioridade, `wait_days`, UF |
| `fact_medication_request` | um MedicationRequest sintético | paciente, encontro, organização, autoria, status/prioridade, medicamento/via/dose/frequência, quantidade, vigência e UF |

`uf_code` nestas tabelas vem de extensão sintética definida pela semente: não é localização de residência, atendimento ou gestão real. `turnaround_hours` é emissão menos data efetiva do Observation; `wait_days` é conclusão simulada menos autoria do ServiceRequest. Ambos servem para testar cálculos e visualização, não para comparar serviços reais.

## Gold: métricas e divulgação

| View | Grão e medidas |
| --- | --- |
| `mart_quality_by_run` | execução: contagens, `acceptance_rate`, hash, versão e status; taxa = aceitos / (aceitos + quarentenados) |
| `mart_quality_issues` | execução × tipo × código × severidade: `issue_count` |
| `mart_access_monthly` | mês × UF × status × prioridade: `referrals`, média, mediana, P90 de `wait_days` |
| `mart_laboratory_monthly` | mês × UF × código: `results`, média, mediana, P90 de `turnaround_hours` |
| `mart_immunization_monthly` | mês × UF × vacina × dose: `doses` |
| `mart_condition_monthly` | mês × UF × CID-10: `conditions` |
| `mart_medication_monthly` | mês × UF × medicamento × via × prioridade: prescrições, quantidade média e dias médios de fornecimento sintéticos |
| `mart_model_volume` | modelo demonstrativo × tipo FHIR: recursos e completude de paciente, tempo e UF |
| `mart_demographic_profile` | UF × gênero × faixa etária sintéticos: `synthetic_people` |
| `mart_rnds_public_indicators` | indicador × competência × UF: versão mais recente dos valores UF, região/Brasil, atualização e hash |
| `mart_rnds_brazil_trend` | indicador × competência: total Brasil, variação absoluta e relativa contra a observação anterior |

A API suprime contagem abaixo de cinco e, quando aplicável, métricas derivadas. Views não são política suficiente de divulgação: subtotais, cruzamentos e filtros precisam de revisão antes de publicação.

## Indicadores públicos RNDS

`rnds_public_indicators` contém `indicator_code`, `indicator_name`, `competence`, `uf_code`, `uf_name`, `region_code`, `region_name`, `value_uf`, `value_region`, `value_brazil`, `updated_at`, `source_sha256` e `loaded_at`.

`updated_at` preserva o timestamp civil publicado sem inventar um fuso ausente
no CSV; `loaded_at` registra em UTC quando o arquivo foi obtido pelo laboratório.

| Código | Rótulo usado no projeto |
| --- | --- |
| `sdigi008` | Total de registros na RNDS |
| `sdigi009` | Registros de Imunobiológicos Administrados (RIA) |
| `sdigi010` | Registros de Atendimento Clínico (RAC) |
| `sdigi011` | Atestados médico/odontológicos |
| `sdigi013` | Prescrição de medicamento |
| `sdigi014` | Exames laboratoriais (REL) |
| `sdigi015` | Informações de regulação assistencial (RIRA) |

`competence` usa `AAAAMM`; o carregador aceita granularidade UF, 27 UFs, unicidade competência/UF e totais reconciliados. Os valores publicados não são taxas, prevalências, cobertura populacional, eventos únicos nem indicador de qualidade assistencial. Confirme definição e licença no [recurso oficial](https://dadosabertos.saude.gov.br/dataset/mgdi-rede-nacional-de-dados-em-saude-rnds) na data da análise.
