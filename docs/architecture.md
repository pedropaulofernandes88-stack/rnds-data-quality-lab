# Arquitetura

O RNDS Data Quality Lab é um laboratório local e reproduzível. Combina Bundles FHIR R4 inteiramente sintéticos com indicadores públicos agregados por UF. Não consulta, recebe ou persiste registros assistenciais da RNDS; não é integração, homologação ou certificação oficial.

```text
FHIR sintético → validação → Bronze → Silver → Gold → API/painel
                    └──→ quarentena segura
RNDS pública (CSV ZIP) → download controlado → Gold
```

## Entradas e contratos

O gerador determinístico produz `Bundle` com `Patient`, `Organization`, `Encounter`, `Condition`, `Observation`, `Immunization`, `ServiceRequest`, `MedicationRequest` e `Provenance`. Todo recurso recebe a tag `SYNTHETIC`. Há mapeamentos demonstrativos para `RAC` (Encounter e Condition), `REL` (Observation), `RIA` (Immunization), `RIRA` (ServiceRequest) e `RPM` (MedicationRequest), inspirados no [guia FHIR da RNDS](https://rnds-fhir.saude.gov.br/), no [modelo informacional RPM](https://rnds-guia.saude.gov.br/docs/rpm/mi-rpm/) e no [MedicationRequest FHIR R4](https://hl7.org/fhir/R4/medicationrequest.html). Eles não substituem perfis, credenciais, terminologia ou homologação institucional.

O contrato estrutural está em `contracts/fhir_bundle.schema.json` e o de mapeamento em `contracts/rnds_mapping.yaml`. A validação acumula erros de schema, recursos obrigatórios/duplicados, tag sintética, campos proibidos, referências e ordem temporal. Um Bundle inválido é rejeitado inteiro. A quarentena registra apenas `run_id`, hash, tipo/ID técnico e regra; nunca o payload.

Os indicadores públicos vêm de `data/sources.yml`. A atualização é opt-in e exige HTTPS, limite de tamanho, ausência de redirecionamento, ZIP com um único CSV e SHA-256. Para `sdigi008`, `009`, `010`, `011`, `013`, `014` e `015`, o carregamento exige competência `AAAAMM`, granularidade UF, 27 UFs, ausência de nulos/negativos, unicidade competência/UF e reconciliação UF→região→Brasil. A origem é o [catálogo oficial de indicadores RNDS](https://dadosabertos.saude.gov.br/dataset/mgdi-rede-nacional-de-dados-em-saude-rnds).

## Camadas do lakehouse

| Camada | Persistência | Papel | Controles |
| --- | --- | --- | --- |
| Bronze | `ingestion_runs`, `bronze_resources`, `quality_issues` | Evidência técnica da execução e recurso FHIR aceito em JSON canônico | `payload_sha256`, chave tipo/ID/hash, tag sintética, transação e idempotência |
| Silver | `dim_patient`, `dim_organization`, `fact_*` | Projeção canônica de atendimento, condição, laboratório, imunização, regulação e prescrição | referências FHIR, datas, códigos e UF sintética |
| Gold | `mart_quality_*`, marts de acesso, laboratório, imunização, condições, prescrição, demografia, volume por modelo e tendências RNDS | Métricas de qualidade e análises agregadas | reconciliação pública, visão vigente por fonte e supressão na API |

Bronze não significa “dado bruto oficial”: aqui contém somente JSON sintético aprovado. Silver é relacional e não reconstrói prontuários. A carga em Bronze e as projeções Silver são escritas em lotes Arrow dentro da mesma transação; isso melhora escala sem mudar as garantias de idempotência, rollback e imutabilidade de tipo/ID. Gold expõe contagens, média, mediana e P90 de tempos sintéticos, perfis demográficos simulados e cobertura dos modelos; no caso público preserva indicador, competência, UF/região, valor publicado, atualização e SHA-256 da fonte, além da variação do total Brasil quando existe série histórica.

## Linhagem e operação

Cada execução registra `run_id`, semente, quantidade solicitada, versão do contrato, timestamps, contagens aceitas/rejeitadas, hash consolidado e status. Conteúdo repetido não duplica Bronze; um índice único em tipo/ID torna a identidade imutável e acelera a detecção de versões divergentes, enquanto o hash confirma igualdade de conteúdo. A fonte pública conserva URL, hash e momento de carga; o arquivo fica fora do Git, em `data/raw/`.

`rnds-lab demo` materializa o fluxo sintético; `rnds-lab refresh-public` baixa apenas agregados; `rnds-lab audit` verifica integridade referencial, tempos não negativos, classificação sintética, reconciliação e completude de execução. A API lê marts agregados e a rota de validação declara que não persiste nem ecoa o Bundle. O painel é local e também só lê Gold.

## Limites de segurança e desenho

Os dados sintéticos proíbem `identifier`, `name`, `address`, `telecom`, `photo` e `text`. O scanner detecta padrões de PII plausível, segredos, certificados e endpoints de produção sem mostrar o valor encontrado. Nas rotas analíticas, células abaixo de cinco recebem supressão primária. Isso não elimina inferência por totais, filtros ou diferenças; publicações externas requerem supressão complementar e revisão humana.

Uma integração real à RNDS depende de estabelecimento, ambiente, credenciais, certificado e processo institucional descritos no [passo a passo da RNDS](https://rnds-guia.saude.gov.br/docs/passo-a-passo/). Esta arquitetura deliberadamente não implementa esses elementos.
