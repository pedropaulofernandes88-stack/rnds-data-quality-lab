# Evidência de validação — 2026-08-30

Este registro documenta uma execução local observada. O banco, os arquivos
baixados e os relatórios JSON permanecem em caminhos ignorados pelo Git; o
repositório versiona os comandos, contratos, código e resultados resumidos.
Não extrapole dados sintéticos para a RNDS, pessoas, serviços ou valor clínico.

## Identificação da execução

| Campo | Valor observado |
| --- | --- |
| Data/hora UTC | `2026-08-30T02:25:18Z` |
| Commit Git | `A_REGISTRAR_APOS_COMMIT_DE_IMPLEMENTACAO` |
| Versão do protocolo/contrato | protocolo documentado nesta revisão; `rnds-lab-contract/1.0.0` |
| Python / plataforma | CPython `3.11.15` e `3.12.13`; Windows 11 `10.0.26200`; Intel i7-1255U, 10 núcleos/12 processadores lógicos, 31,7 GiB RAM |
| `uv.lock` (SHA-256) | `b942ef07054a3f54dc22bb1f0dce759a88ec45f9bcab3b0aa3f1ae9b3815ac13` |
| Banco local/versão DuckDB | `data/generated/rnds_lab.duckdb` (ignorado); DuckDB `1.5.5` |
| Classificação dos dados | `SYNTHETIC` no lakehouse assistencial demonstrativo e `PUBLIC_AGGREGATE` em tabela separada; os indicadores públicos não entram em `academic-report` |

## Cenário sintético e escala

| Campo | Valor observado |
| --- | --- |
| Comandos exatos | `rnds-lab demo --patients 5000 --seed 20260829 --invalid-every 23` e `rnds-lab demo --patients 15000 --seed 30300000 --invalid-every 29` |
| Sementes | `20260829` e `30300000` |
| Pacientes solicitados / aceitos | 20.000 / 19.266 Bundles-paciente; 734 Bundles intencionalmente inválidos |
| Competências/UFs sintéticas | 12 meses de 2025; 27 UFs sintéticas |
| Domínios presentes | `RAC`, `REL`, `RIA`, `RIRA`, `RPM` |
| Perturbações usadas | `observation-temporal-reference`, `rpm-validity-window` e `service-request-occurrence`, selecionadas deterministicamente |
| Recursos aceitos / quarentenados | 173.394 / 6.606; 979 falhas de qualidade registradas sem mensagem ou payload |
| Diversidade codificada | 5 CID-10, 4 LOINC, 5 medicamentos e 5 vias sintéticas |
| Duração observada | lote inicial de 5.000: `26,259 s`, 43.047 aceitos (`1.639` recursos aceitos/s; `1.714` candidatos/s); replay de 15.000: `72,197 s`, zero inserções |
| Estratégia de carga | uma transação por execução; staging Arrow de 43.047 e 130.347 recursos Bronze, seguido de lotes Silver por tabela |
| Repetição idempotente | replay das duas sementes produziu zero novas linhas Bronze; hashes e contagens permaneceram estáveis |

O desempenho foi medido no equipamento acima, em diretório local sincronizado
pelo OneDrive, sem carga concorrente intencional. O meio físico, uso de memória
de pico e interferência do sincronizador não foram medidos. Os números são uma
observação, não garantia de capacidade ou custo em outro ambiente.

## Verificações executadas

| Verificação | Comando/artefato | Resultado |
| --- | --- | --- |
| Formatação e lint | `uv run ruff format --check .` / `uv run ruff check .` | PASS em Python 3.11 e 3.12 |
| Tipos | `uv run mypy src` | PASS, 14 módulos, em Python 3.11 e 3.12 |
| Testes e cobertura | `uv run pytest -m "not network"` | 55 PASS; cobertura total 88,76% em ambos os runtimes; limiar 85% |
| Scanner | `rnds-lab scan` sobre material distribuível | PASS; nenhum padrão proibido |
| Dependências | `pip-audit --skip-editable` | PASS; nenhuma vulnerabilidade conhecida |
| Auditoria lakehouse | `rnds-lab audit` / `artifacts/final-audit.json` | 14/14 controles PASS; zero órfãos, temporalidade invertida ou recurso Bronze não sintético |
| API e painel | Uvicorn/FastAPI e Streamlit locais | HTTP 200; API com 2 execuções, cinco modelos e sem payload; painel saudável; portas encerradas após o smoke |
| Build/instalação isolada | `uv build` + instalação do wheel em venv novo | PASS; pipeline, auditoria, relatórios acadêmicos, manifesto empacotado e contrato FHIR validados |

A primeira checagem cruzada em Python 3.12 encontrou NumPy 2.5 incompatível
com o alvo MyPy 3.11 e tipos YAML inconsistentes entre runtimes. A faixa foi
fixada em NumPy `<2.5`, `types-PyYAML` foi declarado e toda a matriz foi
reexecutada com êxito; as falhas intermediárias não foram ocultadas.

## Indicadores públicos

| Campo | Valor observado |
| --- | --- |
| Data de extração | `2026-08-30` UTC (`2026-08-29` em America/Sao_Paulo) |
| Manifesto/fontes | `data/sources.yml`; sete recursos CSV ZIP oficiais do Portal de Dados Abertos do SUS |
| Linhas | 405 agregados por UF; o segundo refresh inseriu zero linhas |
| Competências carregadas | `sdigi008/010/011/013/014`: 202606; `sdigi009`: 202112, 202212, 202312, 202412, 202512, 202606; `sdigi015`: 202312, 202412, 202512, 202606 |
| Reconciliação UF–região–Brasil | PASS nos sete indicadores e em todas as competências; 27 UFs por competência |

SHA-256 dos arquivos oficiais observados:

| Indicador | SHA-256 |
| --- | --- |
| `sdigi008` | `51061f829ea96945a9360b04459b8ae2737ed993a8d4946bcaa3ca809a801111` |
| `sdigi009` | `ac9b0a6fb2a0bf9effcff2f9d2bf89e5e975b5d7389e1416b1e040971a02172d` |
| `sdigi010` | `c30887331d145cb747e7fbef2b9c023ce5e1ccb84d5d45909e31fd111888820b` |
| `sdigi011` | `9f08c445d4d9729a5aceecc01f6ef172f75acf75ab8482d083c1c9793a0f60ad` |
| `sdigi013` | `925818fa9b9c7b87f25441dd7f33a3d133bce786a115754e6de5c78d1e07a02c` |
| `sdigi014` | `12f43e3bfce472fc51ffefb02842e4283572539d2208cb6f555b9870bb7bbda6` |
| `sdigi015` | `574c36d85ed6f177fc14fee5467b70fc4ed9eb030b13025a473bb335ec19d818` |

Os arquivos públicos e suas transformações não foram versionados. Eles não
constituem validação externa do gerador sintético.

## Métricas acadêmicas e limites

| Item | Estado/resultado |
| --- | --- |
| `academic-report` | executado com classificação `SYNTHETIC_ONLY`, NumPy `2.4.6`, 2.000 reamostragens e semente `20260829` |
| Espera regulatória sintética | `n=19.266`; mediana `6,0` dias; IC95% bootstrap percentil `[6,0; 6,0]`; P90 `10,0` |
| Turnaround laboratorial sintético | `n=19.266`; mediana `19,5` horas; IC95% bootstrap percentil `[19,0; 20,0]`; P90 `34,0`; semente `20260830` |
| `evaluate-validator` | quatro classes, semente `20260829`, 1.000 Bundles por classe, unidade Bundle |
| Matriz global | TP=3.000, TN=1.000, FP=0, FN=0 |
| Sensibilidade | `1,000`; IC95% Wilson `[0,998721; 1,000000]` |
| Especificidade | `1,000`; IC95% Wilson `[0,996173; 1,000000]` |
| Precisão | `1,000`; IC95% Wilson `[0,998721; 1,000000]` |
| Por cenário | cada cenário: TP=1.000, TN=1.000, FP=0, FN=0; cobertura dos códigos esperados 1.000/1.000 |
| Desvios/pendências do protocolo | cortes independentes temporal/geográfico/entidade, múltiplas sementes, mutações externas, bootstrap em bloco e validação externa não foram executados; permanecem extensões explícitas |

Os resultados perfeitos do benchmark são esperados em cenários produzidos e
rotulados pelo próprio gerador, podendo refletir acoplamento entre gerador e
validador. O bootstrap descreve duas métricas da simulação; os ICs de Wilson
descrevem proporções no experimento controlado. Nenhum resultado é inferência
populacional, validade clínica, desempenho assistencial ou validação da RNDS.

## Declarações obrigatórias

- Não houve conexão, consulta, envio, certificação ou homologação junto à RNDS.
- Não foram usados dados de pacientes, prontuários ou dados pessoais.
- O mapeamento `MedicationRequest` → RPM é demonstrativo e não atesta
  conformidade com perfil, terminologia, segurança ou processo institucional.
- O resultado não demonstra valor clínico, qualidade assistencial, cobertura,
  causalidade ou desempenho da RNDS.
