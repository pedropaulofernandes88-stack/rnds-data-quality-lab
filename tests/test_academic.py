"""Testes do relatório acadêmico sintético e reprodutível."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rnds_data_lab.academic import (
    DEFAULT_BOOTSTRAP_RESAMPLES,
    bootstrap_median_percentile,
    build_academic_report,
    evaluate_validator_benchmark,
    wilson_interval_95,
    write_academic_report,
)
from rnds_data_lab.config import Settings
from rnds_data_lab.pipeline import run_synthetic_pipeline
from rnds_data_lab.storage import connect, initialize_schema


def test_bootstrap_median_is_deterministic_and_validates_arguments() -> None:
    first = bootstrap_median_percentile([1.0, 2.0, 3.0, 9.0], resamples=101, seed=13)
    second = bootstrap_median_percentile([1.0, 2.0, 3.0, 9.0], resamples=101, seed=13)

    assert first == second
    assert first.estimate == 2.5
    assert first.lower is not None and first.upper is not None
    assert first.lower <= first.estimate <= first.upper
    assert first.observations == 4
    with pytest.raises(ValueError, match="resamples"):
        bootstrap_median_percentile([1.0], resamples=0)
    with pytest.raises(ValueError, match="confidence_level"):
        bootstrap_median_percentile([1.0], confidence_level=1.0)
    with pytest.raises(ValueError, match="finitos"):
        bootstrap_median_percentile([float("nan")])

    default_interval = bootstrap_median_percentile([1.0, 2.0])
    assert default_interval.resamples == DEFAULT_BOOTSTRAP_RESAMPLES


def test_academic_report_is_stable_scoped_to_synthetic_data_and_writes_json(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    run_synthetic_pipeline(settings, patients=12, seed=73, invalid_every=0)

    first = build_academic_report(settings.database_path, resamples=101, seed=5)
    second = build_academic_report(settings.database_path, resamples=101, seed=5)
    destination = write_academic_report(first, settings.artifacts_dir / "academic.json")

    assert first == second
    assert first["data_scope"]["classification"] == "SYNTHETIC_ONLY"
    assert first["interpretation"]["not_population_inference"] is True
    assert first["method"]["interval"] == "bootstrap percentil bilateral"
    assert first["descriptive"]["synthetic_people"] == 12
    wait = first["descriptive"]["referral_wait_days"]
    turnaround = first["descriptive"]["laboratory_turnaround_hours"]
    assert wait["n"] == turnaround["n"] == 12
    assert wait["median_bootstrap_percentile_ci"]["resamples"] == 101
    assert destination.is_file()
    assert json.loads(destination.read_text(encoding="utf-8")) == first

    with connect(settings.database_path) as connection:
        connection.execute("UPDATE bronze_resources SET synthetic = FALSE")
    with pytest.raises(ValueError, match="exclusivamente recursos sintéticos"):
        build_academic_report(settings.database_path, resamples=5)


def test_academic_report_handles_empty_initialized_lakehouse(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.ensure_directories()
    with connect(settings.database_path) as connection:
        initialize_schema(connection)

    report = build_academic_report(settings.database_path)
    assert report["method"]["resamples"] == DEFAULT_BOOTSTRAP_RESAMPLES
    assert report["descriptive"]["referral_wait_days"]["n"] == 0
    assert report["descriptive"]["referral_wait_days"]["median"] is None
    assert report["descriptive"]["laboratory_turnaround_hours"]["median"] is None


def test_wilson_interval_has_known_boundary_limits_and_validates_counts() -> None:
    none_detected = wilson_interval_95(0, 10)
    all_detected = wilson_interval_95(10, 10)
    unavailable = wilson_interval_95(0, 0)

    assert none_detected.estimate == 0
    assert none_detected.lower == 0
    assert none_detected.upper is not None and 0.27 < none_detected.upper < 0.28
    assert all_detected.estimate == 1
    assert all_detected.upper == 1
    assert all_detected.lower is not None and 0.72 < all_detected.lower < 0.73
    assert unavailable.estimate is unavailable.lower is unavailable.upper is None
    with pytest.raises(ValueError, match="sucessos"):
        wilson_interval_95(2, 1)


def test_validator_benchmark_is_deterministic_and_scoped_to_ground_truth() -> None:
    first = evaluate_validator_benchmark(seed=101, samples_per_class=3)
    second = evaluate_validator_benchmark(seed=101, samples_per_class=3)

    assert first == second
    assert first["experiment"]["classes"] == [
        "valid",
        "observation-temporal-reference",
        "rpm-validity-window",
        "service-request-occurrence",
    ]
    assert first["interpretation"]["not_clinical_validity"] is True
    assert first["interpretation"]["not_rnds_validation"] is True
    assert first["global"]["confusion_matrix_bundle_level"] == {
        "true_positive": 9,
        "false_negative": 0,
        "false_positive": 0,
        "true_negative": 3,
        "total": 12,
    }
    for result in first["by_scenario"].values():
        assert result["confusion_matrix_bundle_level"]["true_positive"] == 3
        assert result["confusion_matrix_bundle_level"]["true_negative"] == 3
        assert result["expected_rule_coverage"]["detected_bundles"] == 3
        assert result["metrics"]["sensitivity"]["estimate"] == 1
    with pytest.raises(ValueError, match="samples_per_class"):
        evaluate_validator_benchmark(samples_per_class=0)
