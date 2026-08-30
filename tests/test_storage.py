from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from rnds_data_lab.storage import (
    QualityIssueRecord,
    connect,
    initialize_schema,
    store_run,
)
from rnds_data_lab.synthetic import iter_resources, make_synthetic_bundle

_COUNT_SQL = {
    "ingestion_runs": "SELECT COUNT(*) FROM ingestion_runs",
    "bronze_resources": "SELECT COUNT(*) FROM bronze_resources",
    "quality_issues": "SELECT COUNT(*) FROM quality_issues",
    "dim_patient": "SELECT COUNT(*) FROM dim_patient",
    "fact_encounter": "SELECT COUNT(*) FROM fact_encounter",
    "fact_medication_request": "SELECT COUNT(*) FROM fact_medication_request",
}


def _count(connection: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(connection.execute(_COUNT_SQL[table]).fetchone()[0])


def test_store_run_is_idempotent_and_keeps_issue_payload_out_of_storage(tmp_path: Path) -> None:
    database = tmp_path / "lab.duckdb"
    resources = list(iter_resources(make_synthetic_bundle(seed=13)))
    issue = QualityIssueRecord(
        resource_type="Bundle",
        resource_id="bundle-13",
        code="semantic.example",
        severity="error",
        message="private-marker-never-persisted",
    )

    with connect(database) as connection:
        initialize_schema(connection)
        first = store_run(
            connection,
            run_id="idempotency-run",
            seed=13,
            requested_patients=1,
            contract_version="contract/test",
            accepted=resources,
            issues=[issue],
            quarantined_count=1,
        )
        second = store_run(
            connection,
            run_id="idempotency-run",
            seed=13,
            requested_patients=1,
            contract_version="contract/test",
            accepted=resources,
            issues=[issue],
            quarantined_count=1,
        )

        assert first.inserted_bronze == len(resources)
        assert second.inserted_bronze == 0
        assert first.source_sha256 == second.source_sha256
        assert _count(connection, "ingestion_runs") == 1
        assert _count(connection, "bronze_resources") == len(resources)
        assert _count(connection, "quality_issues") == 1
        assert _count(connection, "fact_medication_request") == 1
        columns = [
            item[0] for item in connection.execute("SELECT * FROM quality_issues").description
        ]
        digest = str(connection.execute("SELECT message_digest FROM quality_issues").fetchone()[0])
        assert "message" not in columns
        assert digest != "private-marker-never-persisted"

        # A second execution may record lineage, but duplicate resources remain unique.
        third = store_run(
            connection,
            run_id="idempotency-run-second-lineage",
            seed=13,
            requested_patients=1,
            contract_version="contract/test",
            accepted=resources,
            issues=[],
        )
        assert third.inserted_bronze == 0
        assert _count(connection, "ingestion_runs") == 2
        assert _count(connection, "bronze_resources") == len(resources)


def test_store_run_rolls_back_when_a_silver_projection_breaks(tmp_path: Path) -> None:
    database = tmp_path / "transaction.duckdb"
    valid_patient = next(iter_resources(make_synthetic_bundle(seed=8)))
    invalid_encounter = {
        "resourceType": "Encounter",
        "id": "will-fail-not-null",
        "meta": valid_patient["meta"],
        "status": "finished",
        # Omitting subject makes fact_encounter.patient_id violate NOT NULL.
    }

    with connect(database) as connection:
        initialize_schema(connection)
        with pytest.raises(duckdb.ConstraintException):
            store_run(
                connection,
                run_id="rollback-run",
                seed=8,
                requested_patients=1,
                contract_version="contract/test",
                accepted=[valid_patient, invalid_encounter],
                issues=[],
            )

        assert _count(connection, "ingestion_runs") == 0
        assert _count(connection, "bronze_resources") == 0
        assert _count(connection, "dim_patient") == 0
        assert _count(connection, "fact_encounter") == 0


def test_store_run_rejects_run_collision_and_resource_version_drift(tmp_path: Path) -> None:
    database = tmp_path / "immutable.duckdb"
    resources = list(iter_resources(make_synthetic_bundle(seed=21)))

    with connect(database) as connection:
        initialize_schema(connection)
        store_run(
            connection,
            run_id="immutable-run",
            seed=21,
            requested_patients=1,
            contract_version="contract/test",
            accepted=resources,
            issues=[],
        )

        with pytest.raises(ValueError, match="run_id já existe"):
            store_run(
                connection,
                run_id="immutable-run",
                seed=22,
                requested_patients=1,
                contract_version="contract/test",
                accepted=list(iter_resources(make_synthetic_bundle(seed=22))),
                issues=[],
            )

        changed_resources = [dict(resource) for resource in resources]
        changed_resources[0]["active"] = not bool(changed_resources[0]["active"])
        with pytest.raises(ValueError, match="conteúdo divergente"):
            store_run(
                connection,
                run_id="version-drift",
                seed=21,
                requested_patients=1,
                contract_version="contract/test-v2",
                accepted=changed_resources,
                issues=[],
            )

        assert _count(connection, "ingestion_runs") == 1
        assert _count(connection, "bronze_resources") == len(resources)


def test_store_run_rejects_conflicting_identity_inside_one_batch(tmp_path: Path) -> None:
    database = tmp_path / "within-batch-drift.duckdb"
    patient = next(iter_resources(make_synthetic_bundle(seed=34)))
    conflicting_patient = {**patient, "active": not bool(patient["active"])}

    with connect(database) as connection:
        initialize_schema(connection)
        with pytest.raises(ValueError, match="conteúdo divergente"):
            store_run(
                connection,
                run_id="within-batch-drift",
                seed=34,
                requested_patients=1,
                contract_version="contract/test",
                accepted=[patient, conflicting_patient],
                issues=[],
            )

        assert _count(connection, "ingestion_runs") == 0
        assert _count(connection, "bronze_resources") == 0
        assert _count(connection, "dim_patient") == 0
