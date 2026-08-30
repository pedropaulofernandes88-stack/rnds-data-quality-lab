"""Auditoria estrutural e metodológica do lakehouse local."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from rnds_data_lab.storage import connect, query_dicts


@dataclass(frozen=True, slots=True)
class AuditCheck:
    name: str
    passed: bool
    observed: int | float | str
    expectation: str


@dataclass(frozen=True, slots=True)
class AuditReport:
    generated_at: datetime
    database_path: Path
    checks: tuple[AuditCheck, ...]
    table_counts: dict[str, int]
    latest_runs: tuple[dict[str, Any], ...]
    quality_issues: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "database_path": str(self.database_path),
            "passed": self.passed,
            "checks": [asdict(check) for check in self.checks],
            "table_counts": self.table_counts,
            "latest_runs": list(self.latest_runs),
            "quality_issues": list(self.quality_issues),
        }


_COUNT_QUERIES = {
    "ingestion_runs": "SELECT COUNT(*) FROM ingestion_runs",
    "bronze_resources": "SELECT COUNT(*) FROM bronze_resources",
    "quality_issues": "SELECT COUNT(*) FROM quality_issues",
    "dim_patient": "SELECT COUNT(*) FROM dim_patient",
    "dim_organization": "SELECT COUNT(*) FROM dim_organization",
    "fact_encounter": "SELECT COUNT(*) FROM fact_encounter",
    "fact_condition": "SELECT COUNT(*) FROM fact_condition",
    "fact_lab_result": "SELECT COUNT(*) FROM fact_lab_result",
    "fact_immunization": "SELECT COUNT(*) FROM fact_immunization",
    "fact_referral": "SELECT COUNT(*) FROM fact_referral",
    "fact_medication_request": "SELECT COUNT(*) FROM fact_medication_request",
    "rnds_public_indicators": "SELECT COUNT(*) FROM rnds_public_indicators",
}


def audit_database(database_path: Path) -> AuditReport:
    """Executa invariantes que impedem a publicação de um artefato inconsistente."""

    if not database_path.is_file():
        raise FileNotFoundError(f"Banco não encontrado: {database_path}")

    with connect(database_path, read_only=True) as connection:
        counts = {
            table: _required_scalar(connection.execute(sql).fetchone())
            for table, sql in _COUNT_QUERIES.items()
        }
        checks = (
            _count_check(
                connection,
                "bronze_only_synthetic",
                "SELECT COUNT(*) FROM bronze_resources WHERE NOT synthetic",
                "zero recursos sem marcador SYNTHETIC",
            ),
            _count_check(
                connection,
                "encounter_patient_integrity",
                """SELECT COUNT(*) FROM fact_encounter f
                   LEFT JOIN dim_patient p ON p.patient_id = f.patient_id
                   WHERE p.patient_id IS NULL""",
                "zero encontros órfãos",
            ),
            _count_check(
                connection,
                "condition_patient_integrity",
                """SELECT COUNT(*) FROM fact_condition f
                   LEFT JOIN dim_patient p ON p.patient_id = f.patient_id
                   WHERE p.patient_id IS NULL""",
                "zero condições órfãs",
            ),
            _count_check(
                connection,
                "laboratory_patient_integrity",
                """SELECT COUNT(*) FROM fact_lab_result f
                   LEFT JOIN dim_patient p ON p.patient_id = f.patient_id
                   WHERE p.patient_id IS NULL""",
                "zero exames órfãos",
            ),
            _count_check(
                connection,
                "immunization_patient_integrity",
                """SELECT COUNT(*) FROM fact_immunization f
                   LEFT JOIN dim_patient p ON p.patient_id = f.patient_id
                   WHERE p.patient_id IS NULL""",
                "zero imunizações órfãs",
            ),
            _count_check(
                connection,
                "referral_patient_integrity",
                """SELECT COUNT(*) FROM fact_referral f
                   LEFT JOIN dim_patient p ON p.patient_id = f.patient_id
                   WHERE p.patient_id IS NULL""",
                "zero regulações órfãs",
            ),
            _count_check(
                connection,
                "medication_patient_integrity",
                """SELECT COUNT(*) FROM fact_medication_request f
                   LEFT JOIN dim_patient p ON p.patient_id = f.patient_id
                   WHERE p.patient_id IS NULL""",
                "zero prescrições sintéticas órfãs",
            ),
            _count_check(
                connection,
                "medication_encounter_integrity",
                """SELECT COUNT(*) FROM fact_medication_request f
                   LEFT JOIN fact_encounter e ON e.encounter_id = f.encounter_id
                   WHERE f.encounter_id IS NOT NULL AND e.encounter_id IS NULL""",
                "zero prescrições sem encontro correspondente",
            ),
            _count_check(
                connection,
                "medication_validity_order",
                """SELECT COUNT(*) FROM fact_medication_request
                   WHERE validity_start IS NOT NULL AND validity_end IS NOT NULL
                     AND validity_end < validity_start""",
                "zero vigências de prescrição invertidas",
            ),
            _count_check(
                connection,
                "medication_nonnegative_quantities",
                """SELECT COUNT(*) FROM fact_medication_request
                   WHERE dose_value < 0 OR quantity_value < 0
                      OR expected_supply_days < 0 OR frequency_per_period < 0""",
                "zero doses, quantidades ou durações negativas",
            ),
            _count_check(
                connection,
                "nonnegative_turnaround",
                "SELECT COUNT(*) FROM fact_lab_result WHERE turnaround_hours < 0",
                "zero tempos laboratoriais negativos",
            ),
            _count_check(
                connection,
                "nonnegative_wait",
                "SELECT COUNT(*) FROM fact_referral WHERE wait_days < 0",
                "zero esperas negativas",
            ),
            _count_check(
                connection,
                "public_indicator_bounds",
                """SELECT COUNT(*) FROM rnds_public_indicators
                   WHERE value_uf < 0 OR value_region < 0 OR value_brazil < 0
                      OR value_uf > value_brazil OR value_region > value_brazil""",
                "zero totais negativos ou acima do total Brasil",
            ),
            _count_check(
                connection,
                "completed_runs_have_timestamp",
                """SELECT COUNT(*) FROM ingestion_runs
                   WHERE status = 'completed' AND completed_at IS NULL""",
                "zero execuções concluídas sem timestamp",
            ),
        )
        latest_runs = tuple(
            query_dicts(
                connection,
                """SELECT * FROM mart_quality_by_run
                   ORDER BY completed_at DESC NULLS LAST LIMIT 20""",
            )
        )
        quality_issues = tuple(
            query_dicts(
                connection,
                """SELECT * FROM mart_quality_issues
                   ORDER BY run_id, severity, issue_count DESC LIMIT 200""",
            )
        )

    return AuditReport(
        generated_at=datetime.now(tz=UTC),
        database_path=database_path.resolve(),
        checks=checks,
        table_counts=counts,
        latest_runs=latest_runs,
        quality_issues=quality_issues,
    )


def _count_check(connection: Any, name: str, sql: str, expectation: str) -> AuditCheck:
    observed = _required_scalar(connection.execute(sql).fetchone())
    return AuditCheck(
        name=name,
        passed=observed == 0,
        observed=observed,
        expectation=expectation,
    )


def _required_scalar(row: tuple[object, ...] | None) -> int:
    if row is None:
        raise RuntimeError("Consulta de auditoria não retornou resultado")
    return int(str(row[0]))


def write_audit_report(report: AuditReport, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return destination


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Tipo não serializável: {type(value).__name__}")
