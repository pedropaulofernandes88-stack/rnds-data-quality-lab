<#
.SYNOPSIS
Executa localmente uma demonstração FHIR/RNDS inteiramente sintética.

.DESCRIPTION
O script não baixa indicadores, não chama a RNDS e não remove dados. A mesma
combinação de parâmetros é idempotente: repetir a execução preserva o mesmo
run_id e demonstra a reprodutibilidade do lakehouse local.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 100000)]
    [int]$Patients = 250,

    [int]$Seed = 42,

    [ValidateRange(0, 100000)]
    [int]$InvalidEvery = 17,

    [switch]$SkipChecks
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DemoHome = Join-Path $ProjectRoot 'artifacts\demo-workspace'
$AuditOutput = Join-Path $DemoHome 'audit-report.json'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv não foi encontrado no PATH. Instale-o em https://docs.astral.sh/uv/.'
}

Push-Location $ProjectRoot
try {
    # Impede atualização transitiva e torna a execução reproduzível a partir do uv.lock.
    & uv lock --check
    if ($LASTEXITCODE -ne 0) { throw 'O uv.lock não corresponde ao pyproject.toml.' }

    & uv sync --all-groups --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível sincronizar o ambiente bloqueado.' }

    if (-not $SkipChecks) {
        & uv run ruff format --check .
        if ($LASTEXITCODE -ne 0) { throw 'Verificação de formatação falhou.' }

        & uv run ruff check .
        if ($LASTEXITCODE -ne 0) { throw 'Lint falhou.' }

        & uv run mypy src
        if ($LASTEXITCODE -ne 0) { throw 'Checagem de tipos falhou.' }

        # Testes guardam vetores adversariais que devem acionar o scanner;
        # a varredura aqui é somente do conteúdo distribuível.
        & uv run rnds-lab scan README.md AGENTS.md CONTRIBUTING.md SECURITY.md LICENSE pyproject.toml src docs contracts data/sources.yml scripts .github
        if ($LASTEXITCODE -ne 0) { throw 'Scanner preventivo encontrou material proibido.' }

        & uv run pytest -m 'not network'
        if ($LASTEXITCODE -ne 0) { throw 'Testes offline falharam.' }
    }

    New-Item -ItemType Directory -Force -Path $DemoHome | Out-Null
    $env:RNDS_LAB_HOME = $DemoHome

    # Sem --include-public: não há download nem consulta à RNDS nesta demonstração.
    & uv run rnds-lab demo --patients $Patients --seed $Seed --invalid-every $InvalidEvery --json-output
    if ($LASTEXITCODE -ne 0) { throw 'Pipeline sintético falhou.' }

    & uv run rnds-lab audit --output $AuditOutput
    if ($LASTEXITCODE -ne 0) { throw 'Auditoria do lakehouse falhou.' }

    Write-Host "Demonstração concluída. Artefatos locais: $DemoHome" -ForegroundColor Green
}
finally {
    Remove-Item Env:RNDS_LAB_HOME -ErrorAction SilentlyContinue
    Pop-Location
}
