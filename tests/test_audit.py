from __future__ import annotations

import json
from pathlib import Path

from rnds_data_lab.audit import audit_database, write_audit_report
from rnds_data_lab.config import Settings
from rnds_data_lab.pipeline import run_synthetic_pipeline
from rnds_data_lab.storage import connect
from rnds_data_lab.synthetic import iter_resources, make_synthetic_bundle


def _resources_per_bundle() -> int:
    return len(list(iter_resources(make_synthetic_bundle())))


def test_audit_reports_clean_synthetic_pipeline_and_writes_json(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    run_synthetic_pipeline(settings, patients=3, seed=90, invalid_every=0)

    report = audit_database(settings.database_path)
    destination = write_audit_report(report, settings.artifacts_dir / "audit.json")

    assert report.passed
    assert report.table_counts["bronze_resources"] == 3 * _resources_per_bundle()
    assert report.table_counts["fact_medication_request"] == 3
    assert destination.is_file()
    serialized = json.loads(destination.read_text(encoding="utf-8"))
    assert serialized["passed"] is True
    assert serialized["latest_runs"][0]["status"] == "completed"


def test_audit_detects_non_synthetic_bronze_record(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    run_synthetic_pipeline(settings, patients=1, seed=91, invalid_every=0)
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE bronze_resources SET synthetic = FALSE")

    report = audit_database(settings.database_path)
    check = next(item for item in report.checks if item.name == "bronze_only_synthetic")

    assert not report.passed
    assert not check.passed
    assert check.observed == _resources_per_bundle()
