"""Interface de linha de comando do laboratório."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from rnds_data_lab import __version__
from rnds_data_lab.academic import (
    build_academic_report,
    evaluate_validator_benchmark,
    write_academic_report,
)
from rnds_data_lab.audit import audit_database, write_audit_report
from rnds_data_lab.config import Settings
from rnds_data_lab.pipeline import run_synthetic_pipeline
from rnds_data_lab.public_data import refresh_public_rnds_indicators
from rnds_data_lab.security import scan_paths
from rnds_data_lab.storage import connect, initialize_schema

app = typer.Typer(
    name="rnds-lab",
    help="Laboratório reproduzível de dados RNDS/FHIR sintéticos e públicos agregados.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
console = Console()


@app.command("version")
def version() -> None:
    """Exibe a versão instalada."""

    console.print(__version__)


@app.command("init")
def initialize() -> None:
    """Cria as camadas DuckDB vazias."""

    settings = Settings.load()
    settings.ensure_directories()
    with connect(settings.database_path) as connection:
        initialize_schema(connection)
    console.print(f"[green]Lakehouse pronto:[/] {settings.database_path}")


@app.command("demo")
def demo(
    patients: Annotated[int, typer.Option(min=1, max=100_000)] = 250,
    seed: int = 42,
    invalid_every: Annotated[int, typer.Option(min=0)] = 17,
    run_id: str | None = None,
    include_public: bool = False,
    json_output: bool = False,
) -> None:
    """Executa o pipeline sintético ponta a ponta, com falhas controladas."""

    settings = Settings.load()
    result = run_synthetic_pipeline(
        settings,
        patients=patients,
        seed=seed,
        invalid_every=invalid_every,
        run_id=run_id,
    )
    public_rows = 0
    if include_public:
        public_rows = refresh_public_rnds_indicators(settings).rows_inserted

    if json_output:
        payload = result.to_dict()
        payload["public_rows_inserted"] = public_rows
        console.print_json(json.dumps(payload, ensure_ascii=False, default=str))
        return

    table = Table(title="Execução reproduzível")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")
    table.add_row("run_id", result.run.run_id)
    table.add_row("pacientes solicitados", str(result.requested_patients))
    table.add_row("bundles válidos", str(result.valid_bundles))
    table.add_row("bundles em quarentena", str(result.quarantined_bundles))
    table.add_row("recursos aceitos", str(result.run.accepted))
    table.add_row("recursos em quarentena", str(result.run.quarantined))
    table.add_row("falhas de qualidade", str(result.run.quality_issues))
    table.add_row("novos recursos Bronze", str(result.run.inserted_bronze))
    table.add_row("agregados públicos inseridos", str(public_rows))
    console.print(table)
    console.print(f"[green]Banco:[/] {result.run.database_path}")


@app.command("refresh-public")
def refresh_public(
    codes: Annotated[list[str] | None, typer.Option("--code")] = None,
) -> None:
    """Atualiza os sete indicadores RNDS públicos, agregados por UF."""

    settings = Settings.load()
    selected = tuple(codes) if codes else None
    result = refresh_public_rnds_indicators(settings, codes=selected)
    table = Table(title="Indicadores públicos RNDS")
    table.add_column("Indicador")
    table.add_column("Linhas lidas", justify="right")
    table.add_column("Novas", justify="right")
    table.add_column("Competências")
    table.add_column("SHA-256")
    for item in result.indicators:
        table.add_row(
            item.code,
            str(item.rows_read),
            str(item.rows_inserted),
            ", ".join(item.competencies),
            item.source_sha256[:12],
        )
    console.print(table)


@app.command("audit")
def audit(
    output: Path = Path("artifacts/audit-report.json"),
) -> None:
    """Verifica integridade, temporalidade, linhagem e classificação."""

    settings = Settings.load()
    report = audit_database(settings.database_path)
    destination = write_audit_report(report, output.resolve())
    table = Table(title="Auditoria do lakehouse")
    table.add_column("Controle")
    table.add_column("Resultado")
    table.add_column("Observado", justify="right")
    for check in report.checks:
        table.add_row(
            check.name,
            "[green]PASS[/]" if check.passed else "[red]FAIL[/]",
            str(check.observed),
        )
    console.print(table)
    console.print(f"Relatório: {destination}")
    if not report.passed:
        raise typer.Exit(code=1)


@app.command("academic-report")
def academic_report(
    output: Path = Path("artifacts/academic-report.json"),
    resamples: Annotated[int, typer.Option(min=1)] = 2_000,
    seed: int = 20_260_829,
    confidence_level: Annotated[float, typer.Option(min=0.001, max=0.999)] = 0.95,
) -> None:
    """Gera estatísticas sintéticas e ICs bootstrap, sem inferência populacional."""

    settings = Settings.load()
    report = build_academic_report(
        settings.database_path,
        resamples=resamples,
        seed=seed,
        confidence_level=confidence_level,
    )
    destination = write_academic_report(report, output.resolve())
    descriptive = report["descriptive"]
    table = Table(title="Relatório acadêmico — escopo de simulação")
    table.add_column("Métrica")
    table.add_column("n", justify="right")
    table.add_column("Mediana")
    table.add_row(
        "Espera de encaminhamento (dias)",
        str(descriptive["referral_wait_days"]["n"]),
        str(descriptive["referral_wait_days"]["median"]),
    )
    table.add_row(
        "Turnaround laboratorial (horas)",
        str(descriptive["laboratory_turnaround_hours"]["n"]),
        str(descriptive["laboratory_turnaround_hours"]["median"]),
    )
    console.print(table)
    console.print(
        "[yellow]ICs descrevem a simulação; não são inferência populacional ou clínica.[/]"
    )
    console.print(f"Relatório: {destination}")


@app.command("evaluate-validator")
def evaluate_validator(
    output: Path = Path("artifacts/validator-evaluation.json"),
    seed: int = 20_260_829,
    samples_per_class: Annotated[int, typer.Option(min=1)] = 100,
) -> None:
    """Avalia o validador apenas contra ground truth sintético controlado."""

    report = evaluate_validator_benchmark(seed=seed, samples_per_class=samples_per_class)
    destination = write_academic_report(report, output.resolve())
    global_metrics = report["global"]["metrics"]
    table = Table(title="Avaliação do validador — experimento sintético")
    table.add_column("Métrica")
    table.add_column("Estimativa")
    table.add_column("IC95% Wilson")
    for metric, values in global_metrics.items():
        table.add_row(
            metric,
            f"{values['estimate']:.3f}",
            f"[{values['lower']:.3f}, {values['upper']:.3f}]",
        )
    console.print(table)
    console.print(
        "[yellow]Mede somente cenários sintéticos; não é validade clínica, da RNDS "
        "ou populacional.[/]"
    )
    console.print(f"Relatório: {destination}")


@app.command("scan")
def scan(
    paths: Annotated[list[Path] | None, typer.Argument()] = None,
) -> None:
    """Procura PII plausível, segredos e endpoints proibidos sem ecoar valores."""

    selected = paths or [Path("src"), Path("tests"), Path("docs"), Path("data")]
    existing = [path for path in selected if path.exists()]
    findings = scan_paths(existing)
    if not findings:
        console.print("[green]Nenhum padrão proibido encontrado.[/]")
        return
    table = Table(title="Achados de segurança")
    table.add_column("Tipo")
    table.add_column("Regra")
    table.add_column("Local")
    for finding in findings:
        table.add_row(
            finding.kind,
            finding.rule,
            f"{finding.path}:{finding.line}:{finding.column}",
        )
    console.print(table)
    raise typer.Exit(code=1)


@app.command("serve-api")
def serve_api(
    host: str = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65_535)] = 8000,
) -> None:
    """Inicia a API FastAPI local."""

    uvicorn.run("rnds_data_lab.api:app", host=host, port=port, reload=False)


@app.command("dashboard")
def dashboard(
    port: Annotated[int, typer.Option(min=1, max=65_535)] = 8501,
) -> None:
    """Inicia o painel Streamlit local."""

    module = Path(__file__).with_name("dashboard.py")
    subprocess.run(  # noqa: S603 - lista fixa, sem shell
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(module),
            "--server.port",
            str(port),
            "--server.address",
            "127.0.0.1",
        ],
        check=True,
    )


if __name__ == "__main__":
    app()
