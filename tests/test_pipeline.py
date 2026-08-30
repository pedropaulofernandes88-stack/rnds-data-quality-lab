from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rnds_data_lab.config import Settings
from rnds_data_lab.pipeline import deterministic_run_id, run_synthetic_pipeline
from rnds_data_lab.storage import connect
from rnds_data_lab.synthetic import GROUND_TRUTH_SCENARIOS, iter_resources, make_synthetic_bundle


def _settings(tmp_path: Path) -> Settings:
    return Settings.load(tmp_path)


_COUNT_SQL = {
    "ingestion_runs": "SELECT COUNT(*) FROM ingestion_runs",
    "bronze_resources": "SELECT COUNT(*) FROM bronze_resources",
}


def _count(database: Path, table: str) -> int:
    with connect(database, read_only=True) as connection:
        return int(connection.execute(_COUNT_SQL[table]).fetchone()[0])


def _resources_per_bundle() -> int:
    return len(list(iter_resources(make_synthetic_bundle())))


def test_pipeline_quarantines_entire_invalid_bundle_without_writing_payload(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    result = run_synthetic_pipeline(settings, patients=4, seed=31, invalid_every=2)

    assert result.valid_bundles == 2
    assert result.quarantined_bundles == 2
    assert result.run.accepted == result.valid_bundles * _resources_per_bundle()
    assert result.run.quarantined == result.quarantined_bundles * _resources_per_bundle()
    assert result.run.quality_issues > 0
    assert _count(settings.database_path, "bronze_resources") == result.run.accepted
    assert result.quarantine_manifest is not None

    lines = result.quarantine_manifest.read_text(encoding="utf-8").splitlines()
    assert lines
    permitted = {
        "run_id",
        "bundle_id",
        "bundle_sha256",
        "resource_type",
        "resource_id",
        "code",
        "severity",
        "path",
        "ground_truth_scenarios",
    }
    for line in lines:
        row: dict[str, Any] = json.loads(line)
        assert set(row) <= permitted
        serialized = json.dumps(row, sort_keys=True)
        assert "birthDate" not in serialized
        assert "valueQuantity" not in serialized
        assert "payload" not in serialized.lower()
        assert set(row["ground_truth_scenarios"]) <= set(GROUND_TRUTH_SCENARIOS)
        assert row["ground_truth_scenarios"]


def test_pipeline_is_deterministic_and_idempotent_for_same_input(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    expected_id = deterministic_run_id(seed=19, patients=5, invalid_every=0)

    first = run_synthetic_pipeline(settings, patients=5, seed=19, invalid_every=0)
    second = run_synthetic_pipeline(settings, patients=5, seed=19, invalid_every=0)

    assert first.run.run_id == expected_id
    assert second.run.run_id == expected_id
    assert first.run.source_sha256 == second.run.source_sha256
    assert first.run.inserted_bronze == 5 * _resources_per_bundle()
    assert second.run.inserted_bronze == 0
    assert _count(settings.database_path, "ingestion_runs") == 1
    assert _count(settings.database_path, "bronze_resources") == 5 * _resources_per_bundle()
