from __future__ import annotations

from typing import Any

from rnds_data_lab.synthetic import (
    GROUND_TRUTH_SCENARIOS,
    GROUND_TRUTH_TAG_SYSTEM,
    MODEL_TAG_SYSTEM,
    RNDS_MODEL_BY_RESOURCE,
    SYNTHETIC_CODE,
    SYNTHETIC_TAG_SYSTEM,
    SYNTHETIC_UF_EXTENSION_URL,
    SYNTHETIC_UFS,
    ground_truth_scenarios,
    iter_resources,
    make_synthetic_bundle,
)
from rnds_data_lab.validation import validate_bundle


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value)) if value else set()
    return set()


def test_generator_is_deterministic_and_complete() -> None:
    first = make_synthetic_bundle(seed=7)
    second = make_synthetic_bundle(seed=7)

    assert first == second
    assert first != make_synthetic_bundle(seed=8)
    resources = list(iter_resources(first))
    assert {str(item["resourceType"]) for item in resources} == {
        "Patient",
        "Organization",
        "Encounter",
        "Condition",
        "Observation",
        "Immunization",
        "ServiceRequest",
        "MedicationRequest",
        "Provenance",
    }


def test_generator_marks_models_and_excludes_sensitive_fields() -> None:
    bundle = make_synthetic_bundle()
    assert not {"identifier", "name", "address", "telecom", "photo", "text"} & _keys(bundle)

    for resource in iter_resources(bundle):
        tags = resource["meta"]["tag"]
        assert {
            "system": SYNTHETIC_TAG_SYSTEM,
            "code": SYNTHETIC_CODE,
            "display": "Dado sintético para demonstração",
        } in tags
        model = RNDS_MODEL_BY_RESOURCE.get(resource["resourceType"])
        if model:
            assert any(tag["system"] == MODEL_TAG_SYSTEM and tag["code"] == model for tag in tags)


def test_generator_varies_uf_time_and_operational_events_by_seed() -> None:
    first = {
        resource["resourceType"]: resource for resource in iter_resources(make_synthetic_bundle(1))
    }
    second = {
        resource["resourceType"]: resource for resource in iter_resources(make_synthetic_bundle(2))
    }

    assert first["Encounter"]["period"] != second["Encounter"]["period"]
    assert first["Observation"]["valueQuantity"] != second["Observation"]["valueQuantity"]
    assert first["Immunization"]["vaccineCode"] != second["Immunization"]["vaccineCode"]
    assert first["ServiceRequest"]["extension"] != second["ServiceRequest"]["extension"]
    assert (
        first["MedicationRequest"]["medicationCodeableConcept"]
        != second["MedicationRequest"]["medicationCodeableConcept"]
    )
    assert any(
        extension["url"] == SYNTHETIC_UF_EXTENSION_URL
        for extension in first["Encounter"]["extension"]
    )


def test_generator_covers_all_ufs_and_varies_clinical_scenarios() -> None:
    bundles = [
        {
            resource["resourceType"]: resource
            for resource in iter_resources(make_synthetic_bundle(seed))
        }
        for seed in range(len(SYNTHETIC_UFS))
    ]
    ufs = {
        next(
            extension["valueCode"]
            for extension in bundle["Encounter"]["extension"]
            if extension["url"] == SYNTHETIC_UF_EXTENSION_URL
        )
        for bundle in bundles
    }
    genders = {bundle["Patient"]["gender"] for bundle in bundles}
    condition_codes = {bundle["Condition"]["code"]["coding"][0]["code"] for bundle in bundles}
    lab_codes = {bundle["Observation"]["code"]["coding"][0]["code"] for bundle in bundles}
    priorities = {bundle["ServiceRequest"]["priority"] for bundle in bundles}
    medication_codes = {
        bundle["MedicationRequest"]["medicationCodeableConcept"]["coding"][0]["code"]
        for bundle in bundles
    }
    medication_routes = {
        bundle["MedicationRequest"]["dosageInstruction"][0]["route"]["coding"][0]["code"]
        for bundle in bundles
    }

    assert ufs == set(SYNTHETIC_UFS)
    assert genders == {"female", "male", "other", "unknown"}
    assert len(condition_codes) == 5
    assert len(lab_codes) == 4
    assert priorities == {"routine", "urgent", "asap", "stat"}
    assert len(medication_codes) == 5
    assert len(medication_routes) == 5
    assert "performer" in bundles[0]["Observation"]
    assert "performer" in bundles[0]["Immunization"]


def test_generator_covers_all_twelve_synthetic_competencies() -> None:
    months = {
        next(
            resource["period"]["start"][5:7]
            for resource in iter_resources(make_synthetic_bundle(seed))
            if resource["resourceType"] == "Encounter"
        )
        for seed in range(12)
    }

    assert months == {f"{month:02d}" for month in range(1, 13)}


def test_ground_truth_scenarios_are_deterministic_safe_and_detectable() -> None:
    for scenario, expected_codes in GROUND_TRUTH_SCENARIOS.items():
        bundle = make_synthetic_bundle(seed=11, error_scenario=scenario)
        validation = validate_bundle(bundle)

        assert ground_truth_scenarios(bundle) == (scenario,)
        assert not validation.valid
        assert set(expected_codes) <= {issue.code for issue in validation.issues}
        tags = bundle["meta"]["tag"]
        assert tags == [
            {
                "system": GROUND_TRUTH_TAG_SYSTEM,
                "code": scenario,
                "display": "Cenário sintético de ground truth",
            }
        ]
        assert not {"birthDate", "valueQuantity", "payload"} & _keys(bundle["meta"])


def test_ground_truth_helper_filters_untrusted_tags() -> None:
    bundle = make_synthetic_bundle()
    bundle["meta"]["tag"].append({"system": GROUND_TRUTH_TAG_SYSTEM, "code": "untrusted-free-text"})

    assert ground_truth_scenarios(bundle) == ()


def test_rpm_medication_request_is_coded_structured_and_provenanced() -> None:
    resources = {
        resource["resourceType"]: resource
        for resource in iter_resources(make_synthetic_bundle(seed=13))
    }
    medication_request = resources["MedicationRequest"]
    provenance = resources["Provenance"]

    assert medication_request["status"] == "active"
    assert medication_request["intent"] == "order"
    assert medication_request["subject"] == {"reference": f"Patient/{resources['Patient']['id']}"}
    assert medication_request["requester"] == {
        "reference": f"Organization/{resources['Organization']['id']}"
    }
    assert medication_request["medicationCodeableConcept"]["coding"][0]["code"].startswith("MED-")
    assert "text" not in _keys(medication_request)
    assert medication_request["dispenseRequest"]["quantity"]["value"] > 0
    assert {"reference": f"MedicationRequest/{medication_request['id']}"} in provenance["target"]
