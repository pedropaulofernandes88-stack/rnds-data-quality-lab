# Como contribuir

Contribuições devem preservar o caráter reproduzível, sintético e não clínico
do laboratório. Não adicione dados individuais, PII, textos clínicos, imagens,
payloads de produção, endpoints privados, tokens, certificados ou credenciais.
Use apenas dados públicos agregados ou inequivocamente sintéticos; registre
origem, licença, versão, checksum, granularidade, limitações e data de extração.

Antes de abrir um pull request, execute offline:

```powershell
uv run ruff check src tests
uv run mypy src
uv run pytest
```

Adicione testes unitários para regras novas, integração para fluxos completos e
property-based tests quando houver invariantes úteis. Fixtures devem ser
pequenas, sintéticas e claramente rotuladas. Para mudanças de schema, inclua
caso de compatibilidade ou falha explícita.

Não adicione exceções amplas ao scanner. A allowlist de documentação é literal e
somente pode conter placeholders reservados e seguros, preferencialmente com o
domínio `.invalid`; toda entrada nova deve explicar por que não é dado real nem
segredo. Dashboards e APIs públicas só podem expor agregados sujeitos a revisão
contra inferência por células pequenas e totais.

Este projeto não é homologado, certificado nem integrado à RNDS. Ele não deve
ser usado para decisão clínica, tratamento assistencial ou acesso a produção.
