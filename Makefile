.DEFAULT_GOAL := help

UV ?= uv

.PHONY: help install format lint typecheck scan test audit check demo

help: ## Exibe os comandos disponíveis.
	@$(UV) run python -c "print('install  sincroniza dependências do uv.lock'); print('check    executa formatação, lint, tipos, scanner e testes offline'); print('demo     executa o demonstrador reproduzível no PowerShell')"

install: ## Sincroniza exatamente as dependências bloqueadas.
	$(UV) lock --check
	$(UV) sync --all-groups --frozen

format: ## Verifica a formatação sem alterar arquivos.
	$(UV) run ruff format --check .

lint: ## Executa regras estáticas.
	$(UV) run ruff check .

typecheck: ## Executa checagem de tipos estrita.
	$(UV) run mypy src

scan: ## Procura PII, segredos e endpoints proibidos.
	$(UV) run rnds-lab scan README.md AGENTS.md CONTRIBUTING.md SECURITY.md LICENSE pyproject.toml src docs contracts data/sources.yml scripts .github

test: ## Executa testes sem os marcados como dependentes de rede.
	$(UV) run pytest -m "not network"

audit: ## Audita dependências contra vulnerabilidades conhecidas.
	$(UV) run pip-audit --skip-editable --progress-spinner=off

check: format lint typecheck scan test ## Executa todas as verificações locais sem rede de dados.

demo: ## Executa a demonstração sintética reproduzível no PowerShell.
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1
