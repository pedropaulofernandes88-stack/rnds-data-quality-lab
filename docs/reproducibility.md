# Reprodutibilidade e validação

O objetivo de reprodução é obter o mesmo lote sintético, as mesmas regras e as mesmas métricas a partir de uma versão do código e de uma semente — não reproduzir informação clínica real. A execução padrão não requer rede.

## Caminho mínimo

```powershell
uv sync --all-groups
uv run rnds-lab demo --patients 250 --seed 42 --invalid-every 17
uv run rnds-lab audit
uv run rnds-lab scan
```

`uv.lock` fixa o conjunto resolvido de dependências. `demo` recebe semente inteira e cria `run_id` determinístico quando não informado. Repetir os mesmos parâmetros produz os mesmos Bundles e o mesmo hash lógico de entrada; timestamps de execução mudam. O armazenamento é idempotente para recursos com mesmo tipo, ID e hash: uma segunda carga não insere novo Bronze.

Para testar rejeição, `--invalid-every 17` seleciona deterministamente, pela semente, um dos três cenários rotulados: `observation-temporal-reference`, `rpm-validity-window` ou `service-request-occurrence`. A tag de *ground truth* fica no `Bundle`, sem conteúdo clínico; a quarentena contém apenas metadados e hashes. O gerador não afirma cobrir isoladamente cada regra do catálogo nem simular falhas reais. Para lote sem falha injetada, use `--invalid-every 0`.

## Relatórios acadêmicos reproduzíveis

Após uma carga sintética, o comando abaixo grava um JSON `SYNTHETIC_ONLY`. Ele não inclui o *mart* público e interrompe se houver recurso Bronze marcado como não sintético. Para a mesma base, semente, parâmetros e versão de NumPy, as medianas e os ICs devem se repetir.

```powershell
uv run rnds-lab academic-report --output artifacts/academic-report.json --resamples 2000 --seed 20260829
```

O relatório calcula a mediana, média, P90 e `n` de `wait_days` e
`turnaround_hours`; o IC bilateral de 95% é bootstrap percentil da mediana. Ele
descreve somente a simulação e a reamostragem, não população, efeito clínico,
qualidade assistencial ou RNDS.

O benchmark abaixo é independente do banco: gera `valid` e os três cenários
positivos rotulados, com o mesmo número de Bundles por classe. A decisão positiva
é a rejeição do Bundle pelo validador. O JSON inclui matriz TP/FN/FP/TN,
sensibilidade, especificidade, precisão, cobertura de códigos esperados e IC95%
de Wilson.

```powershell
uv run rnds-lab evaluate-validator --output artifacts/validator-evaluation.json --samples-per-class 100 --seed 20260829
```

Esta não é uma validação de perfis oficiais, de uma RNDS real, de outras
implementações FHIR ou de qualquer desfecho clínico. O benchmark mede apenas os
três cenários criados pelo próprio laboratório e a classe válida correspondente.

## Dados públicos opcionais

```powershell
uv run rnds-lab refresh-public
```

Esse passo requer rede e baixa CSV ZIP agregados para `data/raw/`, ignorado pelo Git. O resultado pode mudar entre datas porque a publicação pode ser atualizada. A reprodução auditável deve registrar data, URL, SHA-256, competências e versão do código. O pipeline registra SHA-256 no banco e rejeita resposta fora dos limites de URL, tamanho, arquivo, schema, cobertura ou reconciliação.

Não versionar cópias transformadas dos dados públicos sem revisar os termos da fonte. Este comando não acessa a RNDS assistencial. O acesso institucional à RNDS segue processo próprio de ambientes e credenciais, descrito na documentação oficial de [ambientes](https://rnds-guia.saude.gov.br/docs/rnds/ambientes/).

## Testes e evidências

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run pip-audit
```

Os testes usam fixtures pequenas e transporte HTTP simulado; não devem baixar fonte nem usar credenciais. A suíte cobre determinismo, ausência de campos sensíveis, contrato FHIR, referências, temporalidade, limites de download, manifestos, scanner e supressão. A auditoria verifica que Bronze é sintético, fatos apontam para pacientes existentes, tempos são não negativos, totais públicos permanecem em limites e execuções concluídas têm timestamp.

Antes de comparar mudanças, registre commit Git, Python, `uv.lock`, parâmetros, `run_id`, hashes, versão do contrato, data/hora e relatório de auditoria. Para regressão, execute o mesmo comando duas vezes em banco novo e confirme hashes e contagens de conteúdo; não compare timestamps. Mudança em contrato, geração ou transformação deve ter fixture de regressão e atualização explícita da versão do contrato.

Para carga de escala, aumente `--patients` gradualmente em banco local descartável, registre duração, recursos/s e memória observada, e repita o mesmo lote para confirmar zero novas linhas Bronze. A escrita Arrow em lote reduz a sobrecarga de inserções por linha, mas não é uma garantia de capacidade: o limite depende de máquina, DuckDB, disco, parâmetros e versão. Não publique números de desempenho sem ambiente, comando e evidência versionados; use o [template de evidência](evidence/latest-validation.md).

## Interpretação responsável

O pipeline valida propriedades de engenharia, não validade clínica. Alta aceitação mede aderência das entradas sintéticas ao contrato deste projeto; não mede completude ou qualidade da RNDS. P90 de espera e liberação é propriedade da simulação. Indicadores públicos podem ser reproduzidos como totais publicados, mas não permitem inferir prontuários, desempenho causal de estados ou cobertura assistencial sem denominadores, definições, períodos e desenho adequados.
