"""Persistência DuckDB em camadas Bronze, Silver e Gold."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def reference_id(reference: str | None) -> str | None:
    if not reference:
        return None
    return reference.rsplit("/", maxsplit=1)[-1]


def first_coding(resource: Mapping[str, Any], field: str) -> tuple[str | None, str | None]:
    container = resource.get(field)
    if isinstance(container, list):
        container = container[0] if container and isinstance(container[0], Mapping) else None
    if not isinstance(container, Mapping):
        return None, None
    coding = container.get("coding")
    if not isinstance(coding, list) or not coding or not isinstance(coding[0], Mapping):
        return None, None
    return _optional_text(coding[0].get("system")), _optional_text(coding[0].get("code"))


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _nested_reference(resource: Mapping[str, Any], field: str) -> str | None:
    value = resource.get(field)
    if isinstance(value, Mapping):
        return reference_id(_optional_text(value.get("reference")))
    return None


def _period_value(resource: Mapping[str, Any], name: str) -> str | None:
    period = resource.get("period")
    return _optional_text(period.get(name)) if isinstance(period, Mapping) else None


def _extension_value(resource: Mapping[str, Any], suffix: str) -> str | None:
    extensions = resource.get("extension")
    if not isinstance(extensions, list):
        return None
    for extension in extensions:
        if not isinstance(extension, Mapping):
            continue
        if str(extension.get("url", "")).endswith(suffix):
            for key in ("valueCode", "valueString", "valueInteger", "valueDateTime"):
                if key in extension:
                    return _optional_text(extension[key])
    return None


def _synthetic_uf(resource: Mapping[str, Any]) -> str | None:
    return _extension_value(resource, "synthetic-federative-unit") or _extension_value(
        resource, "synthetic-uf"
    )


def _model_tag(resource: Mapping[str, Any]) -> str | None:
    meta = resource.get("meta")
    if not isinstance(meta, Mapping):
        return None
    tags = meta.get("tag")
    if not isinstance(tags, list):
        return None
    model_systems = {"urn:rnds-lab:model", "https://rnds.saude.gov.br/model"}
    for tag in tags:
        if isinstance(tag, Mapping) and tag.get("system") in model_systems:
            return _optional_text(tag.get("code"))
    return None


@dataclass(frozen=True, slots=True)
class QualityIssueRecord:
    resource_type: str
    resource_id: str
    code: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    accepted: int
    quarantined: int
    quality_issues: int
    inserted_bronze: int
    source_sha256: str
    database_path: Path


@contextmanager
def connect(database_path: Path, *, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path), read_only=read_only)
    try:
        yield connection
    finally:
        connection.close()


def initialize_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """Cria o contrato físico do lakehouse local."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            run_id VARCHAR PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            seed BIGINT NOT NULL,
            requested_patients BIGINT NOT NULL,
            source_sha256 VARCHAR NOT NULL,
            contract_version VARCHAR NOT NULL,
            accepted_count BIGINT DEFAULT 0,
            quarantined_count BIGINT DEFAULT 0,
            quality_issue_count BIGINT DEFAULT 0,
            inserted_bronze_count BIGINT DEFAULT 0,
            status VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bronze_resources (
            resource_key VARCHAR PRIMARY KEY,
            resource_type VARCHAR NOT NULL,
            resource_id VARCHAR NOT NULL,
            model VARCHAR,
            patient_ref VARCHAR,
            uf_code VARCHAR,
            event_at TIMESTAMPTZ,
            synthetic BOOLEAN NOT NULL,
            payload_json JSON NOT NULL,
            payload_sha256 VARCHAR NOT NULL,
            first_run_id VARCHAR NOT NULL,
            first_seen_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quality_issues (
            issue_key VARCHAR PRIMARY KEY,
            run_id VARCHAR NOT NULL,
            resource_type VARCHAR NOT NULL,
            resource_id VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            severity VARCHAR NOT NULL,
            message_digest VARCHAR NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dim_patient (
            patient_id VARCHAR PRIMARY KEY,
            birth_date DATE,
            gender VARCHAR,
            uf_code VARCHAR,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dim_organization (
            organization_id VARCHAR PRIMARY KEY,
            uf_code VARCHAR,
            organization_kind VARCHAR,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_encounter (
            encounter_id VARCHAR PRIMARY KEY,
            patient_id VARCHAR NOT NULL,
            organization_id VARCHAR,
            started_at TIMESTAMPTZ,
            ended_at TIMESTAMPTZ,
            status VARCHAR,
            care_type VARCHAR,
            uf_code VARCHAR,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_condition (
            condition_id VARCHAR PRIMARY KEY,
            patient_id VARCHAR NOT NULL,
            encounter_id VARCHAR,
            code_system VARCHAR,
            condition_code VARCHAR,
            recorded_at TIMESTAMPTZ,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_lab_result (
            observation_id VARCHAR PRIMARY KEY,
            patient_id VARCHAR NOT NULL,
            encounter_id VARCHAR,
            organization_id VARCHAR,
            code_system VARCHAR,
            lab_code VARCHAR,
            effective_at TIMESTAMPTZ,
            issued_at TIMESTAMPTZ,
            result_category VARCHAR,
            turnaround_hours DOUBLE,
            uf_code VARCHAR,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_immunization (
            immunization_id VARCHAR PRIMARY KEY,
            patient_id VARCHAR NOT NULL,
            organization_id VARCHAR,
            occurrence_at TIMESTAMPTZ,
            vaccine_code VARCHAR,
            dose_number BIGINT,
            uf_code VARCHAR,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_referral (
            referral_id VARCHAR PRIMARY KEY,
            patient_id VARCHAR NOT NULL,
            encounter_id VARCHAR,
            organization_id VARCHAR,
            requested_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            status VARCHAR,
            priority VARCHAR,
            wait_days DOUBLE,
            uf_code VARCHAR,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_medication_request (
            medication_request_id VARCHAR PRIMARY KEY,
            patient_id VARCHAR NOT NULL,
            encounter_id VARCHAR,
            organization_id VARCHAR,
            authored_at TIMESTAMPTZ,
            status VARCHAR,
            priority VARCHAR,
            medication_system VARCHAR,
            medication_code VARCHAR,
            route_code VARCHAR,
            dose_value DOUBLE,
            dose_unit VARCHAR,
            frequency_per_period BIGINT,
            period_value DOUBLE,
            period_unit VARCHAR,
            quantity_value DOUBLE,
            quantity_unit VARCHAR,
            expected_supply_days DOUBLE,
            validity_start TIMESTAMPTZ,
            validity_end TIMESTAMPTZ,
            uf_code VARCHAR,
            first_run_id VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rnds_public_indicators (
            indicator_code VARCHAR NOT NULL,
            indicator_name VARCHAR NOT NULL,
            competence VARCHAR NOT NULL,
            uf_code VARCHAR NOT NULL,
            uf_name VARCHAR NOT NULL,
            region_code VARCHAR,
            region_name VARCHAR,
            value_uf DOUBLE NOT NULL,
            value_region DOUBLE,
            value_brazil DOUBLE,
            updated_at TIMESTAMP,
            source_sha256 VARCHAR NOT NULL,
            loaded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (indicator_code, competence, uf_code, source_sha256)
        );
        """
    )
    connection.execute(
        "ALTER TABLE ingestion_runs ADD COLUMN IF NOT EXISTS quality_issue_count BIGINT DEFAULT 0"
    )
    connection.execute("ALTER TABLE bronze_resources ADD COLUMN IF NOT EXISTS uf_code VARCHAR")
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_bronze_resource_identity
           ON bronze_resources (resource_type, resource_id)"""
    )
    create_gold_views(connection)


def create_gold_views(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE OR REPLACE VIEW mart_quality_by_run AS
        SELECT
            r.run_id,
            r.completed_at,
            r.accepted_count,
            r.quarantined_count,
            r.quality_issue_count,
            r.inserted_bronze_count,
            CASE
                WHEN r.accepted_count + r.quarantined_count = 0 THEN 0
                ELSE r.accepted_count::DOUBLE /
                     (r.accepted_count + r.quarantined_count)::DOUBLE
            END AS acceptance_rate,
            r.source_sha256,
            r.contract_version,
            r.status
        FROM ingestion_runs r;

        CREATE OR REPLACE VIEW mart_quality_issues AS
        SELECT run_id, resource_type, code, severity, COUNT(*) AS issue_count
        FROM quality_issues
        GROUP BY run_id, resource_type, code, severity;

        CREATE OR REPLACE VIEW mart_access_monthly AS
        SELECT
            strftime(requested_at, '%Y-%m') AS period,
            COALESCE(uf_code, 'NI') AS uf_code,
            status,
            priority,
            COUNT(*) AS referrals,
            AVG(wait_days) AS mean_wait_days,
            MEDIAN(wait_days) AS median_wait_days,
            quantile_cont(wait_days, 0.9) AS p90_wait_days
        FROM fact_referral
        GROUP BY ALL;

        CREATE OR REPLACE VIEW mart_laboratory_monthly AS
        SELECT
            strftime(effective_at, '%Y-%m') AS period,
            COALESCE(uf_code, 'NI') AS uf_code,
            lab_code,
            COUNT(*) AS results,
            AVG(turnaround_hours) AS mean_turnaround_hours,
            MEDIAN(turnaround_hours) AS median_turnaround_hours,
            quantile_cont(turnaround_hours, 0.9) AS p90_turnaround_hours
        FROM fact_lab_result
        GROUP BY ALL;

        CREATE OR REPLACE VIEW mart_immunization_monthly AS
        SELECT
            strftime(occurrence_at, '%Y-%m') AS period,
            COALESCE(uf_code, 'NI') AS uf_code,
            vaccine_code,
            dose_number,
            COUNT(*) AS doses
        FROM fact_immunization
        GROUP BY ALL;

        CREATE OR REPLACE VIEW mart_condition_monthly AS
        SELECT
            strftime(recorded_at, '%Y-%m') AS period,
            COALESCE(p.uf_code, 'NI') AS uf_code,
            condition_code,
            COUNT(*) AS conditions
        FROM fact_condition c
        LEFT JOIN dim_patient p ON p.patient_id = c.patient_id
        GROUP BY ALL;

        CREATE OR REPLACE VIEW mart_medication_monthly AS
        SELECT
            strftime(authored_at, '%Y-%m') AS period,
            COALESCE(uf_code, 'NI') AS uf_code,
            medication_code,
            route_code,
            priority,
            COUNT(*) AS prescriptions,
            AVG(dose_value) AS mean_dose_value,
            AVG(frequency_per_period) AS mean_frequency_per_period,
            AVG(quantity_value) AS mean_quantity,
            AVG(expected_supply_days) AS mean_expected_supply_days
        FROM fact_medication_request
        GROUP BY ALL;

        CREATE OR REPLACE VIEW mart_model_volume AS
        SELECT
            COALESCE(model, 'BASE_FHIR') AS model,
            resource_type,
            COUNT(*) AS resources,
            COUNT(patient_ref) AS resources_with_patient,
            COUNT(event_at) AS resources_with_event_time,
            COUNT(uf_code) AS resources_with_uf
        FROM bronze_resources
        GROUP BY ALL;

        CREATE OR REPLACE VIEW mart_demographic_profile AS
        SELECT
            COALESCE(uf_code, 'NI') AS uf_code,
            gender,
            CASE
                WHEN date_diff('year', birth_date, DATE '2026-01-01') < 18 THEN '00-17'
                WHEN date_diff('year', birth_date, DATE '2026-01-01') < 40 THEN '18-39'
                WHEN date_diff('year', birth_date, DATE '2026-01-01') < 60 THEN '40-59'
                ELSE '60+'
            END AS age_group,
            COUNT(*) AS synthetic_people
        FROM dim_patient
        GROUP BY ALL;

        CREATE OR REPLACE VIEW mart_rnds_public_indicators AS
        SELECT
            indicator_code,
            indicator_name,
            competence,
            uf_code,
            uf_name,
            region_code,
            region_name,
            value_uf,
            value_region,
            value_brazil,
            updated_at,
            source_sha256
        FROM rnds_public_indicators
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY indicator_code, competence, uf_code
            ORDER BY loaded_at DESC, source_sha256 DESC
        ) = 1;

        CREATE OR REPLACE VIEW mart_rnds_brazil_trend AS
        WITH brazil AS (
            SELECT
                indicator_code,
                indicator_name,
                competence,
                MAX(value_brazil) AS value_brazil
            FROM mart_rnds_public_indicators
            GROUP BY ALL
        )
        SELECT
            indicator_code,
            indicator_name,
            competence,
            value_brazil,
            value_brazil - LAG(value_brazil) OVER (
                PARTITION BY indicator_code ORDER BY competence
            ) AS absolute_change,
            CASE
                WHEN LAG(value_brazil) OVER (
                    PARTITION BY indicator_code ORDER BY competence
                ) = 0 THEN NULL
                ELSE value_brazil / LAG(value_brazil) OVER (
                    PARTITION BY indicator_code ORDER BY competence
                ) - 1
            END AS relative_change
        FROM brazil;
        """
    )


def _resource_event_at(resource: Mapping[str, Any]) -> str | None:
    event_fields = (
        "recordedDate",
        "issued",
        "effectiveDateTime",
        "occurrenceDateTime",
        "authoredOn",
    )
    for field in event_fields:
        if field in resource:
            return _optional_text(resource[field])
    return _period_value(resource, "start")


def _resource_patient(resource: Mapping[str, Any]) -> str | None:
    for field in ("subject", "patient"):
        patient_id = _nested_reference(resource, field)
        if patient_id:
            return patient_id
    if resource.get("resourceType") == "Patient":
        return _optional_text(resource.get("id"))
    return None


def _resource_is_synthetic(resource: Mapping[str, Any]) -> bool:
    meta = resource.get("meta")
    if not isinstance(meta, Mapping):
        return False
    tags = meta.get("tag")
    synthetic_systems = {
        "urn:rnds-lab:data-classification",
        "https://rnds.saude.gov.br/tags/data-origin",
    }
    return isinstance(tags, list) and any(
        isinstance(tag, Mapping)
        and tag.get("system") in synthetic_systems
        and str(tag.get("code", "")).upper() == "SYNTHETIC"
        for tag in tags
    )


def store_run(
    connection: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    seed: int,
    requested_patients: int,
    contract_version: str,
    accepted: Iterable[Mapping[str, Any]],
    issues: Iterable[QualityIssueRecord],
    quarantined_count: int | None = None,
) -> RunSummary:
    """Persiste um lote validado e materializa suas projeções canônicas.

    O método é transacional. Conteúdo repetido é reconhecido pelo hash canônico,
    tornando a carga idempotente sem apagar a linhagem de execução.
    """

    accepted_list = list(accepted)
    issue_list = list(issues)
    rejected_count = quarantined_count if quarantined_count is not None else len(issue_list)
    if rejected_count < 0:
        raise ValueError("quarantined_count não pode ser negativo")
    source_digest = sha256(
        "".join(sorted(payload_sha256(item) for item in accepted_list)).encode("ascii")
    ).hexdigest()
    started_at = utc_now()
    inserted_bronze = 0

    previous_run = connection.execute(
        """SELECT seed, requested_patients, source_sha256, contract_version
           FROM ingestion_runs WHERE run_id = ?""",
        [run_id],
    ).fetchone()
    expected_identity = (seed, requested_patients, source_digest, contract_version)
    if previous_run is not None and tuple(previous_run) != expected_identity:
        raise ValueError("run_id já existe com entrada ou contrato diferente")

    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            """
            INSERT INTO ingestion_runs (
                run_id, started_at, completed_at, seed, requested_patients,
                source_sha256, contract_version, accepted_count,
                quarantined_count, quality_issue_count, inserted_bronze_count, status
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, 0, 0, 0, 0, 'running')
            ON CONFLICT (run_id) DO UPDATE SET
                started_at = excluded.started_at,
                completed_at = NULL,
                source_sha256 = excluded.source_sha256,
                accepted_count = 0,
                quarantined_count = 0,
                quality_issue_count = 0,
                inserted_bronze_count = 0,
                status = 'running'
            """,
            [run_id, started_at, seed, requested_patients, source_digest, contract_version],
        )
        connection.execute("DELETE FROM quality_issues WHERE run_id = ?", [run_id])
        new_resources = _insert_bronze_batch(connection, accepted_list, run_id, started_at)
        inserted_bronze = len(new_resources)
        _upsert_silver_batch(connection, new_resources, run_id)
        _insert_issues_batch(connection, issue_list, run_id, started_at)

        completed_at = utc_now()
        connection.execute(
            """
            UPDATE ingestion_runs
            SET completed_at = ?, accepted_count = ?, quarantined_count = ?,
                quality_issue_count = ?, inserted_bronze_count = ?, status = 'completed'
            WHERE run_id = ?
            """,
            [
                completed_at,
                len(accepted_list),
                rejected_count,
                len(issue_list),
                inserted_bronze,
                run_id,
            ],
        )
        create_gold_views(connection)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    database_row = connection.execute("PRAGMA database_list").fetchone()
    if database_row is None:  # pragma: no cover - DuckDB sempre informa o banco atual
        raise RuntimeError("DuckDB não informou o banco atual")
    database_file = Path(str(database_row[2]))
    return RunSummary(
        run_id=run_id,
        accepted=len(accepted_list),
        quarantined=rejected_count,
        quality_issues=len(issue_list),
        inserted_bronze=inserted_bronze,
        source_sha256=source_digest,
        database_path=database_file,
    )


def _insert_bronze_batch(
    connection: duckdb.DuckDBPyConnection,
    resources: Iterable[Mapping[str, Any]],
    run_id: str,
    started_at: datetime,
) -> list[Mapping[str, Any]]:
    """Valida identidades e insere Bronze em três operações em lote.

    A tabela temporária limita a verificação de imutabilidade às identidades do
    lote. Assim, uma carga grande não faz uma varredura Python de todo o Bronze.
    """

    staged: dict[str, tuple[Mapping[str, Any], tuple[object, ...]]] = {}
    for resource in resources:
        resource_type = str(resource.get("resourceType", "Unknown"))
        resource_id = str(resource.get("id", "missing"))
        digest = payload_sha256(resource)
        key = f"{resource_type}/{resource_id}/{digest}"
        staged.setdefault(
            key,
            (
                resource,
                (
                    key,
                    resource_type,
                    resource_id,
                    _model_tag(resource),
                    _resource_patient(resource),
                    _synthetic_uf(resource),
                    _resource_event_at(resource),
                    _resource_is_synthetic(resource),
                    canonical_json(resource),
                    digest,
                    run_id,
                    started_at,
                ),
            ),
        )

    connection.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS _incoming_bronze (
            resource_key VARCHAR, resource_type VARCHAR, resource_id VARCHAR,
            model VARCHAR, patient_ref VARCHAR, uf_code VARCHAR, event_at TIMESTAMPTZ,
            synthetic BOOLEAN, payload_json VARCHAR, payload_sha256 VARCHAR,
            first_run_id VARCHAR, first_seen_at TIMESTAMPTZ
        )
        """
    )
    connection.execute("DELETE FROM _incoming_bronze")
    if not staged:
        return []
    _append_arrow_batch(
        connection,
        "_incoming_bronze_input",
        "INSERT INTO _incoming_bronze SELECT * FROM _incoming_bronze_input",
        (
            "resource_key",
            "resource_type",
            "resource_id",
            "model",
            "patient_ref",
            "uf_code",
            "event_at",
            "synthetic",
            "payload_json",
            "payload_sha256",
            "first_run_id",
            "first_seen_at",
        ),
        [row for _, row in staged.values()],
    )

    within_batch_drift = connection.execute(
        """
        SELECT resource_type
        FROM _incoming_bronze
        GROUP BY resource_type, resource_id
        HAVING COUNT(DISTINCT payload_sha256) > 1
        LIMIT 1
        """
    ).fetchone()
    if within_batch_drift is not None:
        raise ValueError(f"Recurso imutável recebeu conteúdo divergente: {within_batch_drift[0]}")

    stored_drift = connection.execute(
        """
        SELECT incoming.resource_type
        FROM _incoming_bronze AS incoming
        JOIN bronze_resources AS stored
          ON stored.resource_type = incoming.resource_type
         AND stored.resource_id = incoming.resource_id
         AND stored.payload_sha256 <> incoming.payload_sha256
        LIMIT 1
        """
    ).fetchone()
    if stored_drift is not None:
        raise ValueError(f"Recurso imutável recebeu conteúdo divergente: {stored_drift[0]}")

    new_keys = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT incoming.resource_key
            FROM _incoming_bronze AS incoming
            LEFT JOIN bronze_resources AS stored
              ON stored.resource_key = incoming.resource_key
            WHERE stored.resource_key IS NULL
            """
        ).fetchall()
    }
    connection.execute(
        """
        INSERT INTO bronze_resources (
            resource_key, resource_type, resource_id, model, patient_ref,
            uf_code, event_at, synthetic, payload_json, payload_sha256,
            first_run_id, first_seen_at
        )
        SELECT resource_key, resource_type, resource_id, model, patient_ref,
               uf_code, event_at, synthetic, payload_json::JSON, payload_sha256,
               first_run_id, first_seen_at
        FROM _incoming_bronze
        ON CONFLICT (resource_key) DO NOTHING
        """
    )
    return [resource for key, (resource, _) in staged.items() if key in new_keys]


def _insert_issues_batch(
    connection: duckdb.DuckDBPyConnection,
    issues: Iterable[QualityIssueRecord],
    run_id: str,
    observed_at: datetime,
) -> None:
    rows: list[tuple[object, ...]] = []
    for issue in issues:
        message_digest = sha256(issue.message.encode("utf-8")).hexdigest()
        issue_key = sha256(
            f"{run_id}|{issue.resource_type}|{issue.resource_id}|{issue.code}|{message_digest}".encode()
        ).hexdigest()
        rows.append(
            (
                issue_key,
                run_id,
                issue.resource_type,
                issue.resource_id,
                issue.code,
                issue.severity,
                message_digest,
                observed_at,
            )
        )
    if rows:
        _append_arrow_batch(
            connection,
            "_quality_issues_input",
            "INSERT OR IGNORE INTO quality_issues SELECT * FROM _quality_issues_input",
            (
                "issue_key",
                "run_id",
                "resource_type",
                "resource_id",
                "code",
                "severity",
                "message_digest",
                "observed_at",
            ),
            rows,
        )


def _encounter_organization_map(
    connection: duckdb.DuckDBPyConnection, resources: Iterable[Mapping[str, Any]]
) -> dict[str, str | None]:
    encounter_ids = {
        encounter_id
        for resource in resources
        if str(resource.get("resourceType", "")) in {"Observation", "Immunization"}
        if (encounter_id := _nested_reference(resource, "encounter")) is not None
    }
    if not encounter_ids:
        return {}
    rows = connection.execute(
        """
        SELECT encounter_id, organization_id
        FROM fact_encounter
        WHERE encounter_id IN (SELECT UNNEST(?))
        """,
        [list(encounter_ids)],
    ).fetchall()
    return {
        str(encounter_id): _optional_text(organization_id) for encounter_id, organization_id in rows
    }


def _upsert_silver_batch(
    connection: duckdb.DuckDBPyConnection, resources: Iterable[Mapping[str, Any]], run_id: str
) -> None:
    """Projeta recursos Bronze recém-inseridos por tipo, com uma chamada por fato."""

    resource_list = list(resources)
    encounter_organizations = {
        str(resource.get("id")): _nested_reference(resource, "serviceProvider")
        for resource in resource_list
        if str(resource.get("resourceType", "")) == "Encounter"
    }
    encounter_organizations.update(_encounter_organization_map(connection, resource_list))
    patients: list[tuple[object, ...]] = []
    organizations: list[tuple[object, ...]] = []
    encounters: list[tuple[object, ...]] = []
    conditions: list[tuple[object, ...]] = []
    observations: list[tuple[object, ...]] = []
    immunizations: list[tuple[object, ...]] = []
    referrals: list[tuple[object, ...]] = []
    medication_requests: list[tuple[object, ...]] = []

    for resource in resource_list:
        resource_type = str(resource.get("resourceType", ""))
        resource_id = str(resource.get("id", ""))
        if not resource_id:
            continue
        if resource_type == "Patient":
            patients.append(
                (
                    resource_id,
                    resource.get("birthDate"),
                    resource.get("gender"),
                    _synthetic_uf(resource),
                    run_id,
                )
            )
        elif resource_type == "Organization":
            kind_system, kind_code = first_coding(resource, "type")
            organizations.append(
                (resource_id, _synthetic_uf(resource), kind_code or kind_system, run_id)
            )
        elif resource_type == "Encounter":
            _, care_type = first_coding(resource, "type")
            encounter_class = resource.get("class")
            if care_type is None and isinstance(encounter_class, Mapping):
                care_type = _optional_text(encounter_class.get("code"))
            encounters.append(
                (
                    resource_id,
                    _nested_reference(resource, "subject"),
                    _nested_reference(resource, "serviceProvider"),
                    _period_value(resource, "start"),
                    _period_value(resource, "end"),
                    resource.get("status"),
                    care_type,
                    _synthetic_uf(resource),
                    run_id,
                )
            )
        elif resource_type == "Condition":
            code_system, condition_code = first_coding(resource, "code")
            conditions.append(
                (
                    resource_id,
                    _nested_reference(resource, "subject"),
                    _nested_reference(resource, "encounter"),
                    code_system,
                    condition_code,
                    resource.get("recordedDate"),
                    run_id,
                )
            )
        elif resource_type == "Observation":
            code_system, lab_code = first_coding(resource, "code")
            effective_at = _optional_text(resource.get("effectiveDateTime"))
            issued_at = _optional_text(resource.get("issued"))
            performers = resource.get("performer")
            organization_id = _performer_organization(performers)
            encounter_id = _nested_reference(resource, "encounter")
            organization_id = organization_id or (
                encounter_organizations.get(encounter_id) if encounter_id else None
            )
            observations.append(
                (
                    resource_id,
                    _nested_reference(resource, "subject"),
                    encounter_id,
                    organization_id,
                    code_system,
                    lab_code,
                    effective_at,
                    issued_at,
                    _observation_result_category(resource),
                    _hours_between(effective_at, issued_at),
                    _synthetic_uf(resource),
                    run_id,
                )
            )
        elif resource_type == "Immunization":
            _, vaccine_code = first_coding(resource, "vaccineCode")
            encounter_id = _nested_reference(resource, "encounter")
            protocol = resource.get("protocolApplied")
            dose_number = (
                protocol[0].get("doseNumberPositiveInt")
                if isinstance(protocol, list) and protocol and isinstance(protocol[0], Mapping)
                else None
            )
            immunizations.append(
                (
                    resource_id,
                    _nested_reference(resource, "patient"),
                    _immunization_organization(resource)
                    or (encounter_organizations.get(encounter_id) if encounter_id else None),
                    resource.get("occurrenceDateTime"),
                    vaccine_code,
                    dose_number,
                    _synthetic_uf(resource),
                    run_id,
                )
            )
        elif resource_type == "ServiceRequest":
            requested_at = _optional_text(resource.get("authoredOn"))
            completed_at = _extension_value(resource, "synthetic-completed-at")
            requester = resource.get("requester")
            organization_id = (
                reference_id(_optional_text(requester.get("reference")))
                if isinstance(requester, Mapping)
                else None
            )
            referrals.append(
                (
                    resource_id,
                    _nested_reference(resource, "subject"),
                    _nested_reference(resource, "encounter"),
                    organization_id,
                    requested_at,
                    completed_at,
                    resource.get("status"),
                    resource.get("priority"),
                    _days_between(requested_at, completed_at),
                    _synthetic_uf(resource),
                    run_id,
                )
            )
        elif resource_type == "MedicationRequest":
            medication_system, medication_code = first_coding(resource, "medicationCodeableConcept")
            dosage = _first_mapping(resource.get("dosageInstruction"))
            route_code = None
            dose_value = None
            dose_unit = None
            frequency = None
            period_value = None
            period_unit = None
            if dosage is not None:
                route = dosage.get("route")
                if isinstance(route, Mapping):
                    _, route_code = first_coding({"route": route}, "route")
                dose_and_rate = _first_mapping(dosage.get("doseAndRate"))
                if dose_and_rate is not None:
                    dose = dose_and_rate.get("doseQuantity")
                    if isinstance(dose, Mapping):
                        dose_value = dose.get("value")
                        dose_unit = dose.get("code") or dose.get("unit")
                timing = dosage.get("timing")
                repeat = timing.get("repeat") if isinstance(timing, Mapping) else None
                if isinstance(repeat, Mapping):
                    frequency = repeat.get("frequency")
                    period_value = repeat.get("period")
                    period_unit = repeat.get("periodUnit")
            dispense = resource.get("dispenseRequest")
            quantity_value = None
            quantity_unit = None
            expected_supply_days = None
            validity_start = None
            validity_end = None
            if isinstance(dispense, Mapping):
                quantity = dispense.get("quantity")
                if isinstance(quantity, Mapping):
                    quantity_value = quantity.get("value")
                    quantity_unit = quantity.get("code") or quantity.get("unit")
                expected_supply = dispense.get("expectedSupplyDuration")
                if isinstance(expected_supply, Mapping):
                    expected_supply_days = _duration_in_days(expected_supply)
                validity = dispense.get("validityPeriod")
                if isinstance(validity, Mapping):
                    validity_start = validity.get("start")
                    validity_end = validity.get("end")
            medication_requests.append(
                (
                    resource_id,
                    _nested_reference(resource, "subject"),
                    _nested_reference(resource, "encounter"),
                    _nested_reference(resource, "requester"),
                    resource.get("authoredOn"),
                    resource.get("status"),
                    resource.get("priority"),
                    medication_system,
                    medication_code,
                    route_code,
                    dose_value,
                    dose_unit,
                    frequency,
                    period_value,
                    period_unit,
                    quantity_value,
                    quantity_unit,
                    expected_supply_days,
                    validity_start,
                    validity_end,
                    _synthetic_uf(resource),
                    run_id,
                )
            )

    for name, table, columns, rows in (
        (
            "_patients_input",
            "dim_patient",
            ("patient_id", "birth_date", "gender", "uf_code", "first_run_id"),
            patients,
        ),
        (
            "_organizations_input",
            "dim_organization",
            ("organization_id", "uf_code", "organization_kind", "first_run_id"),
            organizations,
        ),
        (
            "_encounters_input",
            "fact_encounter",
            (
                "encounter_id",
                "patient_id",
                "organization_id",
                "started_at",
                "ended_at",
                "status",
                "care_type",
                "uf_code",
                "first_run_id",
            ),
            encounters,
        ),
        (
            "_conditions_input",
            "fact_condition",
            (
                "condition_id",
                "patient_id",
                "encounter_id",
                "code_system",
                "condition_code",
                "recorded_at",
                "first_run_id",
            ),
            conditions,
        ),
        (
            "_observations_input",
            "fact_lab_result",
            (
                "observation_id",
                "patient_id",
                "encounter_id",
                "organization_id",
                "code_system",
                "lab_code",
                "effective_at",
                "issued_at",
                "result_category",
                "turnaround_hours",
                "uf_code",
                "first_run_id",
            ),
            observations,
        ),
        (
            "_immunizations_input",
            "fact_immunization",
            (
                "immunization_id",
                "patient_id",
                "organization_id",
                "occurrence_at",
                "vaccine_code",
                "dose_number",
                "uf_code",
                "first_run_id",
            ),
            immunizations,
        ),
        (
            "_referrals_input",
            "fact_referral",
            (
                "referral_id",
                "patient_id",
                "encounter_id",
                "organization_id",
                "requested_at",
                "completed_at",
                "status",
                "priority",
                "wait_days",
                "uf_code",
                "first_run_id",
            ),
            referrals,
        ),
        (
            "_medication_requests_input",
            "fact_medication_request",
            (
                "medication_request_id",
                "patient_id",
                "encounter_id",
                "organization_id",
                "authored_at",
                "status",
                "priority",
                "medication_system",
                "medication_code",
                "route_code",
                "dose_value",
                "dose_unit",
                "frequency_per_period",
                "period_value",
                "period_unit",
                "quantity_value",
                "quantity_unit",
                "expected_supply_days",
                "validity_start",
                "validity_end",
                "uf_code",
                "first_run_id",
            ),
            medication_requests,
        ),
    ):
        if rows:
            _append_arrow_batch(
                connection,
                name,
                f"INSERT OR IGNORE INTO {table} SELECT * FROM {name}",  # noqa: S608 - nomes internos fixos
                columns,
                rows,
            )


def _append_arrow_batch(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    statement: str,
    columns: tuple[str, ...],
    rows: Iterable[tuple[object, ...]],
) -> None:
    """Anexa um lote Arrow, evitando uma chamada DuckDB por recurso."""

    table = pa.Table.from_pylist([dict(zip(columns, row, strict=True)) for row in rows])
    connection.register(name, table)
    try:
        connection.execute(statement)
    finally:
        connection.unregister(name)


def _performer_organization(performers: object) -> str | None:
    if isinstance(performers, list) and performers and isinstance(performers[0], Mapping):
        return reference_id(_optional_text(performers[0].get("reference")))
    return None


def _first_mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return value[0]
    return None


def _duration_in_days(quantity: Mapping[str, Any]) -> float | None:
    value = quantity.get("value")
    if not isinstance(value, (int, float)):
        return None
    unit = str(quantity.get("code") or quantity.get("unit") or "").lower()
    factors = {"d": 1.0, "day": 1.0, "days": 1.0, "h": 1 / 24, "wk": 7.0}
    factor = factors.get(unit)
    return float(value) * factor if factor is not None else None


def _immunization_organization(resource: Mapping[str, Any]) -> str | None:
    performers = resource.get("performer")
    if isinstance(performers, list) and performers and isinstance(performers[0], Mapping):
        actor = performers[0].get("actor")
        if isinstance(actor, Mapping):
            return reference_id(_optional_text(actor.get("reference")))
    return None


def _observation_result_category(resource: Mapping[str, Any]) -> str | None:
    concept = resource.get("valueCodeableConcept")
    if isinstance(concept, Mapping):
        coding = concept.get("coding")
        if isinstance(coding, list) and coding and isinstance(coding[0], Mapping):
            return _optional_text(coding[0].get("code"))
    if "valueQuantity" in resource:
        return "quantitative"
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _hours_between(start: str | None, end: str | None) -> float | None:
    start_dt, end_dt = _parse_datetime(start), _parse_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    return (end_dt - start_dt).total_seconds() / 3600


def _days_between(start: str | None, end: str | None) -> float | None:
    hours = _hours_between(start, end)
    return hours / 24 if hours is not None else None


def query_dicts(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: Iterable[object] | None = None,
) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, list(parameters or []))
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
