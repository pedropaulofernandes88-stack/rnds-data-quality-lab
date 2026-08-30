# Modelo de ameaças e privacidade

O ativo mais crítico é a confiança de que o laboratório não contenha dados
pessoais, segredos ou material assistencial. Este documento é um modelo
educacional; não substitui uma avaliação institucional de impacto ou segurança.

| Ameaça | Impacto | Controle | Evidência |
| --- | --- | --- | --- |
| Commit acidental de PII ou segredo | Exposição e risco LGPD | scanner local/CI, revisão e fixtures sintéticas | `tests/test_security.py` |
| Log ou artefato de CI com payload | Persistência e cópia indevida | logs sem conteúdo, artefatos mínimos e CI offline | workflow e revisão de artefatos |
| Reidentificação de agregado pequeno | Exposição indireta | supressão primária, complementar e revisão humana | regra de divulgação e testes |
| Token, certificado ou endpoint exposto | Acesso não autorizado | cofre, rotação, `.env` ignorado e secret scanning | `SECURITY.md` |
| Dependência comprometida | Execução maliciosa | lockfile, auditoria, SBOM e versões pinadas | relatório de CI/release |
| Uso além da finalidade | Tratamento inadequado | escopo sintético/público, documentação e revisão | governança e CONTRIBUTING |

O scanner detecta CPF e CNS plausíveis, e-mail, telefone brasileiro, atribuição
de segredo, JWT, cabeçalho PEM e endpoints de produção. Seus achados trazem
somente categoria, regra, arquivo, linha e coluna — nunca o valor encontrado.
A allowlist é literal, mínima, pública e destinada exclusivamente a
placeholders `.invalid`; qualquer inclusão exige revisão. O scanner reduz
acidentes, mas não prova anonimização nem substitui DLP ou revisão humana.

Em caso de suspeita de exposição, interromper publicação e automações,
revogar/rotacionar credenciais, preservar evidências sem republicar o dado,
avaliar escopo e comunicar os responsáveis. Incidentes com risco ou dano
relevante podem requerer comunicação pelo controlador à ANPD e aos titulares em
até três dias úteis, conforme o regulamento aplicável.

Referência: [ANPD — Comunicação de Incidente de Segurança](https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/comunicado-de-incidente-de-seguranca-cis).
