# Casos de uso analíticos

O portfólio demonstra perguntas técnicas que podem ser respondidas com segurança no escopo do laboratório. Não produz decisão clínica, ranking de unidades, vigilância individual ou avaliação causal de políticas.

## 1. Observabilidade da qualidade de interoperabilidade

**Pergunta.** Que regras rejeitam Bundles sintéticos e em que etapa?

**Dados e medida.** `mart_quality_by_run` informa aceitação por execução; `mart_quality_issues` agrupa tipo, código e severidade. A taxa é `accepted_count / (accepted_count + quarantined_count)`. Sempre exiba denominador, versão do contrato e conjunto de regras: uma mudança de validação pode mudar a taxa sem mudança na entrada.

**Hipótese testável.** Injeção periódica de falhas aumenta `temporal.observation_issued` e `reference.unresolved` e reduz aceitação. É teste de detecção, não evidência sobre sistemas reais.

**Validação.** Execute sementes distintas, repita cenário para confirmar determinismo e confira os códigos esperados na quarentena. Não trate o resultado como sensibilidade/especificidade clínica: as falhas foram construídas pelo gerador.

## 2. SLOs operacionais sintéticos: laboratório e regulação

**Pergunta.** Qual distribuição temporal simulada de resultado laboratorial e espera para encaminhamento por UF?

**Dados e medida.** `mart_laboratory_monthly` reporta média, mediana e P90 de `turnaround_hours`; `mart_access_monthly` faz o mesmo para `wait_days`; `mart_immunization_monthly` permite contagens por dose e vacina. Mediana e P90 devem ser lidos juntos: média é sensível a caudas, P90 explicita a cauda.

**Hipótese testável.** A variação de semente gera distribuições e UFs sintéticas diferentes, preservando tempos não negativos e ordem temporal válida nos Bundles aceitos.

**Validação.** Conferir integridade de paciente, período e cálculos com `rnds-lab audit`; aplicar supressão a células pequenas antes de divulgação. Não interpretar diferenças entre UFs sintéticas como desigualdade territorial ou gargalo real.

## 3. Monitoramento de indicadores públicos de interoperabilidade

**Pergunta.** Como evoluem totais publicados por indicador e UF em determinada competência?

**Dados e medida.** `mart_rnds_public_indicators` preserva indicador, competência `AAAAMM`, UF, região, Brasil, atualização e hash. O painel pode mostrar valor publicado, data de extração e variação descritiva entre competências, `(valor_t - valor_t-1) / valor_t-1`, apenas com denominador positivo e definição estável.

**Hipótese descritiva.** É possível verificar diferença e variação de totais publicados. Não é possível concluir que uma UF tem melhor qualidade, maior acesso, mais atendimentos ou maior necessidade: o total depende de escopo, integração, envio, atualização e definição do indicador.

**Validação.** Conferir 27 UFs, unicidade competência/UF e reconciliação com região/Brasil; registrar URL e SHA-256. Não some indicadores como se fossem pessoas ou episódios únicos; confirme revisões e definição na [página institucional da RNDS](https://www.gov.br/saude/pt-br/composicao/seidigi/rnds).

## 4. União conceitual, não inferencial

Os rótulos demonstrativos RAC, REL, RIA, RIRA e RPM mostram que tipos de evento FHIR exigem contratos, referências e métricas diferentes. No RPM, `MedicationRequest` serve exclusivamente para exercitar atributos estruturados de prescrição sintética; não representa medicamento dispensado, adesão, tratamento ou benefício clínico. Esses rótulos não autorizam join entre Bronze sintético e indicadores públicos para estimar efeito, cobertura ou performance: as linhas têm populações, mecanismos de geração e propósitos distintos.

Uma comparação válida é de engenharia: quais controles protegem Bundle e quais controles protegem CSV agregado. Uma comparação inválida é alegar que a distribuição do gerador explica totais da RNDS, ou que alteração de indicador público foi causada por regra ou fluxo sintético.

## Checklist antes de comunicar resultado

- Declarar classificação: `SYNTHETIC` ou `PUBLIC_AGGREGATE`.
- Informar período, unidade de análise, denominador e fonte/hash.
- Separar observação, hipótese e inferência.
- Não usar ausência de dado como zero; registrar incerteza ou não comparabilidade.
- Aplicar supressão e revisar risco de diferenciação em células pequenas.
- Evitar linguagem causal sem contrafactual, temporalidade, controle de confundimento e análise de sensibilidade.
