## Mudança

Descreva objetivo, hipótese e impacto nas camadas/contratos.

## Evidências

- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest -m "not network"`
- [ ] scanner preventivo executado no conteúdo distribuível

## Governança

- [ ] Não há PII, dado clínico real, segredo, certificado ou endpoint de produção.
- [ ] A mudança usa apenas dados sintéticos ou públicos agregados.
- [ ] Fonte, licença, versão, granularidade, checksum e limitações foram atualizados quando aplicável.
- [ ] Mudanças analíticas declaram denominador, temporalidade e limites de inferência.
