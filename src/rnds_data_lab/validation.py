"""Validação segura de Bundles FHIR sintéticos para o laboratório."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

from rnds_data_lab.synthetic import (
    MODEL_TAG_SYSTEM,
    RNDS_MODEL_BY_RESOURCE,
    SYNTHETIC_CODE,
    SYNTHETIC_COMPLETED_AT_EXTENSION_URL,
    SYNTHETIC_TAG_SYSTEM,
    SYNTHETIC_WAIT_EXTENSION_URL,
    iter_resources,
)

JsonObject = dict[str, Any]
EXPECTED_RESOURCE_TYPES = frozenset(
    {
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
)
FORBIDDEN_DATA_FIELDS = frozenset({"identifier", "name", "address", "telecom", "photo", "text"})


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Falha sem dados brutos, valores clínicos ou payload de entrada."""

    code: str
    message: str
    resource_type: str | None = None
    resource_id: str | None = None
    path: str | None = None
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Resultado tipado e seguro para API, logs e quarentena."""

    valid: bool
    resource_count: int
    issues: tuple[ValidationIssue, ...]


def _contract_path() -> Path:
    repository_path = Path(__file__).resolve().parents[2] / "contracts" / "fhir_bundle.schema.json"
    if repository_path.is_file():
        return repository_path
    return Path(__file__).resolve().parent / "contracts" / "fhir_bundle.schema.json"


@lru_cache(maxsize=1)
def _load_schema() -> JsonObject:
    with _contract_path().open(encoding="utf-8") as schema_file:
        loaded = json.load(schema_file)
    if not isinstance(loaded, dict):  # Defensive: contract files must be JSON objects.
        raise ValueError("O contrato FHIR deve ser um objeto JSON.")
    return loaded


def _issue(
    code: str,
    message: str,
    resource: Mapping[str, Any] | None = None,
    *,
    path: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        resource_type=str(resource.get("resourceType")) if resource else None,
        resource_id=str(resource.get("id")) if resource else None,
        path=path,
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _find_forbidden_fields(value: Any, path: str = "$") -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_DATA_FIELDS:
                yield child_path
            yield from _find_forbidden_fields(nested, child_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _find_forbidden_fields(nested, f"{path}[{index}]")


def _references(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        reference = value.get("reference")
        if isinstance(reference, str):
            yield reference
        for nested in value.values():
            yield from _references(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _references(nested)


def _has_tag(resource: Mapping[str, Any], system: str, code: str) -> bool:
    meta = resource.get("meta")
    if not isinstance(meta, Mapping):
        return False
    tags = meta.get("tag")
    if not isinstance(tags, list):
        return False
    return any(
        isinstance(tag, Mapping) and tag.get("system") == system and tag.get("code") == code
        for tag in tags
    )


def _extension_value(resource: Mapping[str, Any], url: str) -> Any:
    extensions = resource.get("extension")
    if not isinstance(extensions, list):
        return None
    for extension in extensions:
        if isinstance(extension, Mapping) and extension.get("url") == url:
            for key, value in extension.items():
                if key.startswith("value"):
                    return value
    return None


def _validate_schema(bundle: Mapping[str, Any]) -> list[ValidationIssue]:
    validator = Draft202012Validator(_load_schema())
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(bundle), key=lambda item: list(item.path)):
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.path
        )
        issues.append(
            _issue("structure.schema", "Bundle não atende ao contrato estrutural.", path=path)
        )
    return issues


def _validate_resource_set(resources: list[JsonObject]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str]] = set()
    present_types: set[str] = set()
    for resource in resources:
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        if not isinstance(resource_type, str) or not isinstance(resource_id, str):
            continue
        present_types.add(resource_type)
        key = (resource_type, resource_id)
        if key in seen:
            issues.append(
                _issue("structure.duplicate_resource", "Recurso duplicado no Bundle.", resource)
            )
        seen.add(key)
    for resource_type in sorted(EXPECTED_RESOURCE_TYPES - present_types):
        issues.append(
            _issue("structure.missing_resource", f"Tipo obrigatório ausente: {resource_type}.")
        )
    return issues


def _validate_semantics(resources: list[JsonObject]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for resource in resources:
        resource_type = resource.get("resourceType")
        if not isinstance(resource_type, str):
            continue
        if not _has_tag(resource, SYNTHETIC_TAG_SYSTEM, SYNTHETIC_CODE):
            issues.append(
                _issue(
                    "semantic.synthetic_tag", "Marcador SYNTHETIC obrigatório ausente.", resource
                )
            )
        model_code = RNDS_MODEL_BY_RESOURCE.get(resource_type)
        if model_code and not _has_tag(resource, MODEL_TAG_SYSTEM, model_code):
            issues.append(
                _issue(
                    "semantic.rnds_model_tag", "Tag de modelo demonstrativo RNDS ausente.", resource
                )
            )
        for path in _find_forbidden_fields(resource):
            issues.append(
                _issue(
                    "privacy.forbidden_field",
                    "Campo não permitido em dados sintéticos.",
                    resource,
                    path=path,
                )
            )
        if resource_type == "Observation" and not isinstance(
            resource.get("valueQuantity"), Mapping
        ):
            issues.append(
                _issue("semantic.observation_value", "Observation exige valueQuantity.", resource)
            )
        if resource_type == "ServiceRequest" and resource.get("intent") != "order":
            issues.append(
                _issue(
                    "semantic.service_request_intent",
                    "ServiceRequest exige intent=order.",
                    resource,
                )
            )
        if resource_type == "MedicationRequest":
            if resource.get("status") != "active":
                issues.append(
                    _issue(
                        "semantic.medication_request_status",
                        "MedicationRequest demonstrativo exige status=active.",
                        resource,
                    )
                )
            if resource.get("intent") != "order":
                issues.append(
                    _issue(
                        "semantic.medication_request_intent",
                        "MedicationRequest demonstrativo exige intent=order.",
                        resource,
                    )
                )
            medication = resource.get("medicationCodeableConcept")
            coding = medication.get("coding") if isinstance(medication, Mapping) else None
            if not isinstance(coding, list) or not any(
                isinstance(item, Mapping)
                and isinstance(item.get("system"), str)
                and isinstance(item.get("code"), str)
                for item in coding
            ):
                issues.append(
                    _issue(
                        "semantic.medication_request_medication",
                        "MedicationRequest exige medicamento codificado.",
                        resource,
                    )
                )
            dispense_request = resource.get("dispenseRequest")
            if not isinstance(dispense_request, Mapping):
                issues.append(
                    _issue(
                        "semantic.medication_request_dispense",
                        "MedicationRequest exige bloco estruturado de dispensação sintética.",
                        resource,
                    )
                )
    return issues


def _validate_references(resources: list[JsonObject]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known_references = {
        f"{resource['resourceType']}/{resource['id']}"
        for resource in resources
        if isinstance(resource.get("resourceType"), str) and isinstance(resource.get("id"), str)
    }
    for resource in resources:
        for reference in _references(resource):
            if reference not in known_references:
                issues.append(
                    _issue("reference.unresolved", "Referência não encontrada no Bundle.", resource)
                )
    return issues


def _validate_temporal(resources: list[JsonObject]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    patient_birth_dates = {
        str(resource.get("id")): _parse_date(resource.get("birthDate"))
        for resource in resources
        if resource.get("resourceType") == "Patient"
    }
    for resource in resources:
        resource_type = resource.get("resourceType")
        if resource_type == "Encounter":
            period = resource.get("period")
            if isinstance(period, Mapping):
                start = _parse_datetime(period.get("start"))
                end = _parse_datetime(period.get("end"))
                if start and end and start > end:
                    issues.append(
                        _issue(
                            "temporal.encounter_period",
                            "Fim anterior ao início do atendimento.",
                            resource,
                        )
                    )
        elif resource_type == "Observation":
            effective = _parse_datetime(resource.get("effectiveDateTime"))
            issued = _parse_datetime(resource.get("issued"))
            if effective and issued and effective > issued:
                issues.append(
                    _issue(
                        "temporal.observation_issued",
                        "Resultado anterior à data efetiva não é permitido.",
                        resource,
                    )
                )
        elif resource_type == "Immunization":
            patient = resource.get("patient")
            reference = patient.get("reference") if isinstance(patient, Mapping) else None
            patient_id = reference.removeprefix("Patient/") if isinstance(reference, str) else ""
            birth_date = patient_birth_dates.get(patient_id)
            occurrence = _parse_datetime(resource.get("occurrenceDateTime"))
            if birth_date and occurrence and occurrence.date() < birth_date:
                issues.append(
                    _issue(
                        "temporal.immunization_birth",
                        "Imunização anterior ao nascimento.",
                        resource,
                    )
                )
        elif resource_type == "ServiceRequest":
            authored = _parse_datetime(resource.get("authoredOn"))
            occurrence = _parse_datetime(resource.get("occurrenceDateTime"))
            completed_at = _parse_datetime(
                _extension_value(resource, SYNTHETIC_COMPLETED_AT_EXTENSION_URL)
            )
            wait_hours = _extension_value(resource, SYNTHETIC_WAIT_EXTENSION_URL)
            if authored and occurrence and occurrence < authored:
                issues.append(
                    _issue(
                        "temporal.service_request_occurrence",
                        "Conclusão anterior à solicitação não é permitida.",
                        resource,
                    )
                )
            if authored and completed_at and completed_at < authored:
                issues.append(
                    _issue(
                        "temporal.service_request_completed",
                        "Data de conclusão anterior à solicitação.",
                        resource,
                    )
                )
            if (
                authored
                and completed_at
                and isinstance(wait_hours, int)
                and (completed_at - authored).total_seconds() != wait_hours * 3600
            ):
                issues.append(
                    _issue(
                        "temporal.service_request_wait",
                        "Espera não corresponde ao intervalo informado.",
                        resource,
                    )
                )
        elif resource_type == "MedicationRequest":
            authored = _parse_datetime(resource.get("authoredOn"))
            dispense_request = resource.get("dispenseRequest")
            validity_period = (
                dispense_request.get("validityPeriod")
                if isinstance(dispense_request, Mapping)
                else None
            )
            valid_from = (
                _parse_datetime(validity_period.get("start"))
                if isinstance(validity_period, Mapping)
                else None
            )
            valid_until = (
                _parse_datetime(validity_period.get("end"))
                if isinstance(validity_period, Mapping)
                else None
            )
            if authored and valid_from and valid_from < authored:
                issues.append(
                    _issue(
                        "temporal.medication_request_validity_start",
                        "Vigência anterior à emissão da prescrição não é permitida.",
                        resource,
                    )
                )
            if valid_from and valid_until and valid_until < valid_from:
                issues.append(
                    _issue(
                        "temporal.medication_request_validity_end",
                        "Fim da vigência anterior ao início não é permitido.",
                        resource,
                    )
                )
    return issues


def validate_bundle(bundle: Mapping[str, Any]) -> ValidationResult:
    """Executa validações estruturais, semânticas, temporais e referenciais.

    A saída contém apenas metadados de falha; o payload recebido nunca é incluído
    em mensagens ou no objeto retornado.
    """
    schema_issues = _validate_schema(bundle)
    safe_bundle: JsonObject = dict(bundle)
    resources = list(iter_resources(safe_bundle))
    issues = [
        *schema_issues,
        *_validate_resource_set(resources),
        *_validate_semantics(resources),
        *_validate_references(resources),
        *_validate_temporal(resources),
    ]
    return ValidationResult(valid=not issues, resource_count=len(resources), issues=tuple(issues))
