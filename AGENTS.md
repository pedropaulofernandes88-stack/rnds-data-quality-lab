# Instruções do projeto

- Preserve o idioma português nos documentos e mensagens públicas do projeto.
- Use exclusivamente dados públicos agregados ou dados inequivocamente sintéticos.
- Nunca adicione CPF, CNS, identificadores, imagens, textos clínicos, certificados,
  tokens, URLs privadas ou payloads de produção.
- A RNDS é uma referência de interoperabilidade e uma fonte de indicadores públicos
  agregados. Não alegue integração, homologação, certificação ou acesso assistencial.
- Prefira mudanças pequenas, tipadas, testáveis e reproduzíveis.
- Use `apply_patch` nas edições manuais, `uv` para o ambiente e `ruff`, `mypy` e
  `pytest` para validação.
- Todo novo fluxo de dados precisa registrar origem, licença, versão, checksum,
  granularidade, limitações e data de extração.
- O dashboard e a API pública só podem expor dados agregados.

