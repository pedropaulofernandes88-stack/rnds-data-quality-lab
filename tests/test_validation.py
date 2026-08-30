from __future__ import annotations

import json
from pathlib import Path

from rnds_data_lab.synthetic import make_synthetic_bundle
from rnds_data_lab.validation import ValidationResult, validate_bundle

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "fhir"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_valid_fixture_passes_all_checks() -> None:
    result = validate_bundle(_fixture("valid_bundle.json"))

    assert result.valid
    assert result.resource_count == 9
    assert result.issues == ()


def test_generated_bundle_passes_all_checks() -> None:
    result = validate_bundle(make_synthetic_bundle(seed=22))

    assert result.valid
    assert result.resource_count == 9


def test_invalid_fixture_returns_safe_typed_issues() -> None:
    result = validate_bundle(_fixture("invalid_bundle.json"))

    assert isinstance(result, ValidationResult)
    assert not result.valid
    assert any(issue.code == "privacy.forbidden_field" for issue in result.issues)
    assert not hasattr(result, "payload")


def test_injected_errors_are_temporal_and_referential() -> None:
    result = validate_bundle(make_synthetic_bundle(inject_errors=True))
    codes = {issue.code for issue in result.issues}

    assert "temporal.observation_issued" in codes
    assert "reference.unresolved" in codes


def test_invalid_rpm_fields_are_rejected_without_echoing_payload_values() -> None:
    bundle = make_synthetic_bundle(seed=21)
    medication_request = next(
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == "MedicationRequest"
    )
    medication_request["status"] = "completed"
    medication_request["medicationCodeableConcept"] = {"coding": [{"system": "x"}]}
    medication_request["dispenseRequest"]["validityPeriod"]["end"] = "2025-01-01T00:00:00Z"

    result = validate_bundle(bundle)
    codes = {issue.code for issue in result.issues}
    rendered_issues = " ".join(
        f"{issue.code} {issue.message} {issue.path or ''}" for issue in result.issues
    )

    assert not result.valid
    assert "semantic.medication_request_status" in codes
    assert "semantic.medication_request_medication" in codes
    assert "temporal.medication_request_validity_end" in codes
    assert "completed" not in rendered_issues
    assert not hasattr(result, "payload")
