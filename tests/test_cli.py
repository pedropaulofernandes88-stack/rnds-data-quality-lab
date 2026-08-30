"""Testes da interface de linha de comando sem rede ou processos persistentes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from rnds_data_lab import cli
from rnds_data_lab.audit import audit_database
from rnds_data_lab.config import Settings

runner = CliRunner()


@dataclass(frozen=True)
class _Indicator:
    code: str = "sdigi008"
    rows_read: int = 27
    rows_inserted: int = 27
    competencies: tuple[str, ...] = ("202606",)
    source_sha256: str = "a" * 64


@dataclass(frozen=True)
class _RefreshResult:
    indicators: tuple[_Indicator, ...] = (_Indicator(),)

    @property
    def rows_inserted(self) -> int:
        return sum(item.rows_inserted for item in self.indicators)


@dataclass(frozen=True)
class _Finding:
    kind: str = "secret"
    rule: str = "demo-rule"
    path: Path = Path("demo.txt")
    line: int = 3
    column: int = 7


def _local_settings(monkeypatch: Any, tmp_path: Path) -> Settings:
    settings = Settings.load(tmp_path)
    monkeypatch.setattr(cli.Settings, "load", lambda: settings)
    return settings


def test_cli_init_demo_version_and_audit_happy_path(monkeypatch: Any, tmp_path: Path) -> None:
    settings = _local_settings(monkeypatch, tmp_path)

    initialized = runner.invoke(cli.app, ["init"])
    assert initialized.exit_code == 0, initialized.output
    assert settings.database_path.is_file()

    version = runner.invoke(cli.app, ["version"])
    assert version.exit_code == 0
    assert "0.1.0" in version.output

    demo = runner.invoke(
        cli.app,
        ["demo", "--patients", "2", "--seed", "12", "--invalid-every", "0", "--json-output"],
    )
    assert demo.exit_code == 0, demo.output
    assert '"valid_bundles": 2' in demo.output
    assert '"public_rows_inserted": 0' in demo.output

    report_path = tmp_path / "audit.json"
    audited = runner.invoke(cli.app, ["audit", "--output", str(report_path)])
    assert audited.exit_code == 0, audited.output
    assert report_path.is_file()
    assert audit_database(settings.database_path).passed


def test_cli_demo_table_and_optional_public_refresh(monkeypatch: Any, tmp_path: Path) -> None:
    _local_settings(monkeypatch, tmp_path)
    calls: list[Settings] = []

    def fake_refresh(settings: Settings, **_: object) -> _RefreshResult:
        calls.append(settings)
        return _RefreshResult()

    monkeypatch.setattr(cli, "refresh_public_rnds_indicators", fake_refresh)
    result = runner.invoke(
        cli.app,
        ["demo", "--patients", "1", "--invalid-every", "0", "--include-public"],
    )

    assert result.exit_code == 0, result.output
    assert calls
    assert "Execução reproduzível" in result.output
    assert "agregados públicos inseridos" in result.output


def test_cli_academic_report_writes_reproducible_json(monkeypatch: Any, tmp_path: Path) -> None:
    _local_settings(monkeypatch, tmp_path)
    demo = runner.invoke(cli.app, ["demo", "--patients", "4", "--invalid-every", "0"])
    assert demo.exit_code == 0, demo.output

    destination = tmp_path / "academic-report.json"
    reported = runner.invoke(
        cli.app,
        ["academic-report", "--output", str(destination), "--resamples", "31", "--seed", "99"],
    )

    assert reported.exit_code == 0, reported.output
    assert destination.is_file()
    content = destination.read_text(encoding="utf-8")
    assert '"classification": "SYNTHETIC_ONLY"' in content
    assert "não são inferência populacional" in reported.output


def test_cli_evaluate_validator_writes_ground_truth_report(tmp_path: Path) -> None:
    destination = tmp_path / "validator-evaluation.json"
    evaluated = runner.invoke(
        cli.app,
        [
            "evaluate-validator",
            "--output",
            str(destination),
            "--samples-per-class",
            "2",
            "--seed",
            "7",
        ],
    )

    assert evaluated.exit_code == 0, evaluated.output
    content = destination.read_text(encoding="utf-8")
    assert '"not_rnds_validation": true' in content
    assert '"true_positive": 6' in content
    assert "não é validade clínica" in evaluated.output


def test_cli_refresh_audit_failure_and_scan_branches(monkeypatch: Any, tmp_path: Path) -> None:
    settings = _local_settings(monkeypatch, tmp_path)
    refresh_calls: list[tuple[Settings, tuple[str, ...] | None]] = []

    def fake_refresh(
        effective_settings: Settings, *, codes: tuple[str, ...] | None = None
    ) -> _RefreshResult:
        refresh_calls.append((effective_settings, codes))
        return _RefreshResult()

    monkeypatch.setattr(cli, "refresh_public_rnds_indicators", fake_refresh)
    refreshed = runner.invoke(cli.app, ["refresh-public", "--code", "sdigi008"])
    assert refreshed.exit_code == 0, refreshed.output
    assert refresh_calls == [(settings, ("sdigi008",))]
    assert "Indicadores públicos RNDS" in refreshed.output

    class _FailedReport:
        passed = False
        checks = (type("Check", (), {"name": "integrity", "passed": False, "observed": 1})(),)

    destination = tmp_path / "failed-audit.json"
    monkeypatch.setattr(cli, "audit_database", lambda _: _FailedReport())
    monkeypatch.setattr(cli, "write_audit_report", lambda _report, path: path)
    failed_audit = runner.invoke(cli.app, ["audit", "--output", str(destination)])
    assert failed_audit.exit_code == 1
    assert "FAIL" in failed_audit.output

    scan_calls: list[list[Path]] = []
    monkeypatch.setattr(cli, "scan_paths", lambda paths: scan_calls.append(paths) or [])
    clean_scan = runner.invoke(cli.app, ["scan", str(tmp_path / "absent"), "src"])
    assert clean_scan.exit_code == 0
    assert scan_calls == [[Path("src")]]
    assert "Nenhum padrão proibido" in clean_scan.output

    monkeypatch.setattr(cli, "scan_paths", lambda _: [_Finding()])
    unsafe_scan = runner.invoke(cli.app, ["scan", "src"])
    assert unsafe_scan.exit_code == 1
    assert "demo-rule" in unsafe_scan.output


def test_cli_delegates_server_and_dashboard_without_starting_them(monkeypatch: Any) -> None:
    uvicorn_calls: list[dict[str, object]] = []
    subprocess_calls: list[tuple[list[str], bool]] = []

    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: uvicorn_calls.append(kwargs))

    def fake_run(command: list[str], *, check: bool) -> None:
        subprocess_calls.append((command, check))

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    served = runner.invoke(cli.app, ["serve-api", "--host", "127.0.0.2", "--port", "9012"])
    dashboard = runner.invoke(cli.app, ["dashboard", "--port", "9013"])

    assert served.exit_code == 0, served.output
    assert dashboard.exit_code == 0, dashboard.output
    assert uvicorn_calls == [{"host": "127.0.0.2", "port": 9012, "reload": False}]
    assert subprocess_calls[0][1] is True
    assert subprocess_calls[0][0][-4:] == ["--server.port", "9013", "--server.address", "127.0.0.1"]
