"""Gerador determinístico de eventos FHIR R4 inteiramente sintéticos.

Os recursos deste módulo existem apenas para demonstração técnica. Eles não
representam pessoas, atendimentos, estabelecimentos ou dados da RNDS.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

JsonObject = dict[str, Any]

SYNTHETIC_TAG_SYSTEM = "https://rnds.saude.gov.br/tags/data-origin"
MODEL_TAG_SYSTEM = "https://rnds.saude.gov.br/model"
GROUND_TRUTH_TAG_SYSTEM = "https://example.org/fhir/CodeSystem/rnds-lab-ground-truth"
SYNTHETIC_CODE = "SYNTHETIC"
SYNTHETIC_UF_EXTENSION_URL = (
    "https://example.org/fhir/StructureDefinition/synthetic-federative-unit"
)
SYNTHETIC_WAIT_EXTENSION_URL = "https://example.org/fhir/StructureDefinition/synthetic-wait-hours"
SYNTHETIC_COMPLETED_AT_EXTENSION_URL = (
    "https://example.org/fhir/StructureDefinition/synthetic-completed-at"
)
SYNTHETIC_UFS = (
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
)

# Mapeamento demonstrativo: não afirma homologação, integração ou certificação RNDS.
RNDS_MODEL_BY_RESOURCE: dict[str, str] = {
    "Encounter": "RAC",
    "Condition": "RAC",
    "Observation": "REL",
    "Immunization": "RIA",
    "ServiceRequest": "RIRA",
    "MedicationRequest": "RPM",
    "Provenance": "PROVENANCE",
}

# Cenários deliberadamente pequenos, determinísticos e sem conteúdo clínico. Os
# códigos esperados correspondem às regras locais de validação, não a um
# veredito sobre conformidade de uma instância real da RNDS.
GROUND_TRUTH_SCENARIOS: dict[str, tuple[str, ...]] = {
    "observation-temporal-reference": (
        "temporal.observation_issued",
        "reference.unresolved",
    ),
    "rpm-validity-window": ("temporal.medication_request_validity_end",),
    "service-request-occurrence": ("temporal.service_request_occurrence",),
}
_GROUND_TRUTH_SCENARIO_ORDER = tuple(GROUND_TRUTH_SCENARIOS)


def _stable_id(seed: int, resource_type: str) -> str:
    """Cria identificadores estáveis, deliberadamente não ligados a pessoas reais."""
    return str(uuid5(NAMESPACE_URL, f"rnds-data-quality-lab:{seed}:{resource_type}"))


def _reference(resource_type: str, identifier: str) -> str:
    return f"{resource_type}/{identifier}"


def _meta(model_code: str | None = None) -> JsonObject:
    tags: list[JsonObject] = [
        {
            "system": SYNTHETIC_TAG_SYSTEM,
            "code": SYNTHETIC_CODE,
            "display": "Dado sintético para demonstração",
        }
    ]
    if model_code is not None:
        tags.append(
            {
                "system": MODEL_TAG_SYSTEM,
                "code": model_code,
                "display": f"Mapeamento demonstrativo {model_code}",
            }
        )
    return {"tag": tags}


def _bundle_meta(scenarios: tuple[str, ...]) -> JsonObject:
    """Cria metadados de experimento sem incluir qualquer payload clínico."""

    return {
        "tag": [
            {
                "system": GROUND_TRUTH_TAG_SYSTEM,
                "code": scenario,
                "display": "Cenário sintético de ground truth",
            }
            for scenario in scenarios
        ]
    }


def ground_truth_scenarios(bundle: JsonObject) -> tuple[str, ...]:
    """Extrai somente identificadores conhecidos de cenários do ``Bundle``.

    O filtro por sistema e por lista permitida evita transportar conteúdo
    arbitrário para manifestos de quarentena ou métricas de avaliação.
    """

    meta = bundle.get("meta")
    tags = meta.get("tag") if isinstance(meta, dict) else None
    if not isinstance(tags, list):
        return ()
    return tuple(
        tag["code"]
        for tag in tags
        if isinstance(tag, dict)
        and tag.get("system") == GROUND_TRUTH_TAG_SYSTEM
        and tag.get("code") in GROUND_TRUTH_SCENARIOS
        and isinstance(tag.get("code"), str)
    )


def _fhir_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _synthetic_uf_extension(uf: str) -> JsonObject:
    return {"url": SYNTHETIC_UF_EXTENSION_URL, "valueCode": uf}


def _entry(resource: JsonObject) -> JsonObject:
    return {
        "fullUrl": f"urn:uuid:{resource['id']}",
        "resource": resource,
    }


def _tagged_resource(
    resource_type: str,
    identifier: str,
    body: JsonObject,
    *,
    extensions: list[JsonObject] | None = None,
) -> JsonObject:
    """Adiciona o marcador sintético e o mapeamento demonstrativo RNDS."""
    model_code = RNDS_MODEL_BY_RESOURCE.get(resource_type)
    resource: JsonObject = {
        "resourceType": resource_type,
        "id": identifier,
        "meta": _meta(model_code),
        **body,
    }
    if extensions:
        resource["extension"] = extensions
    return resource


def make_synthetic_bundle(
    seed: int = 42,
    *,
    inject_errors: bool = False,
    error_scenario: str | None = None,
) -> JsonObject:
    """Gera um Bundle FHIR R4 completo e reprodutível.

    ``inject_errors`` seleciona um cenário inválido a partir do ``seed``. Um
    ``error_scenario`` nomeado permite avaliar uma regra específica. As falhas
    escolhidas ficam em ``Bundle.meta.tag`` e não carregam dados clínicos.
    Nenhum caminho do gerador aceita dados reais.
    """
    if error_scenario is not None and error_scenario not in GROUND_TRUTH_SCENARIOS:
        allowed = ", ".join(_GROUND_TRUTH_SCENARIO_ORDER)
        raise ValueError(f"error_scenario deve ser um de: {allowed}")
    scenario = (
        error_scenario
        if error_scenario is not None
        else _GROUND_TRUTH_SCENARIO_ORDER[seed % len(_GROUND_TRUTH_SCENARIO_ORDER)]
        if inject_errors
        else None
    )
    patient_id = _stable_id(seed, "Patient")
    organization_id = _stable_id(seed, "Organization")
    encounter_id = _stable_id(seed, "Encounter")
    condition_id = _stable_id(seed, "Condition")
    observation_id = _stable_id(seed, "Observation")
    immunization_id = _stable_id(seed, "Immunization")
    service_request_id = _stable_id(seed, "ServiceRequest")
    medication_request_id = _stable_id(seed, "MedicationRequest")
    provenance_id = _stable_id(seed, "Provenance")
    encounter_classes = ("AMB", "EMER", "IMP")
    encounter_types = ("CONS", "URGEN", "INTERN")
    vaccine_codes = ("140", "208", "210")
    genders = ("female", "male", "other", "unknown")
    condition_codes = ("L30.9", "L20.9", "J06.9", "E11.9", "I10")
    laboratory_tests = (
        ("718-7", "g/dL", "g/dL", 11.0, 4.5),
        ("2345-7", "mg/dL", "mg/dL", 70.0, 110.0),
        ("4548-4", "%", "%", 4.8, 3.0),
        ("6690-2", "10*3/uL", "10*3/uL", 3.5, 9.0),
    )
    regulated_services = ("DERM", "CARD", "ENDO", "OFT", "PNEU")
    priorities = ("routine", "urgent", "asap", "stat")
    medication_codes = ("MED-001", "MED-002", "MED-003", "MED-004", "MED-005")
    routes = ("PO", "TOP", "IM", "IV", "INH")
    medication_units = ("TAB", "CAP", "ML", "DOSE", "AMP")
    uf = SYNTHETIC_UFS[seed % len(SYNTHETIC_UFS)]
    encounter_class = encounter_classes[seed % len(encounter_classes)]
    encounter_type = encounter_types[seed % len(encounter_types)]
    vaccine_code = vaccine_codes[seed % len(vaccine_codes)]
    vaccine_dose = (seed % 3) + 1
    gender = genders[seed % len(genders)]
    condition_code = condition_codes[seed % len(condition_codes)]
    lab_code, lab_unit, lab_ucum_code, lab_minimum, lab_span = laboratory_tests[
        seed % len(laboratory_tests)
    ]
    regulated_service = regulated_services[seed % len(regulated_services)]
    priority = priorities[seed % len(priorities)]
    medication_code = medication_codes[seed % len(medication_codes)]
    medication_route = routes[seed % len(routes)]
    medication_unit = medication_units[seed % len(medication_units)]
    encounter_start = datetime(2025, (seed % 12) + 1, (seed % 20) + 1, 9, tzinfo=UTC)
    encounter_end = encounter_start + timedelta(minutes=25 + (seed % 46))
    result_effective = encounter_start + timedelta(minutes=15)
    result_issued = result_effective + timedelta(hours=2 + (seed % 36))
    request_authored = encounter_start + timedelta(minutes=20)
    request_wait_hours = 24 + (seed % 21) * 12
    request_completed = request_authored + timedelta(hours=request_wait_hours)
    medication_authored = encounter_start + timedelta(minutes=20)
    medication_valid_until = medication_authored + timedelta(days=30 + (seed % 4) * 30)
    medication_quantity = 10 + (seed % 6) * 10
    resource_extensions = [_synthetic_uf_extension(uf)]
    ages = (7, 18, 34, 57, 76)
    age = ages[seed % len(ages)]
    birth_date = date(encounter_start.year - age, (seed % 12) + 1, (seed % 20) + 1)

    patient = _tagged_resource(
        "Patient",
        patient_id,
        {
            "active": True,
            "gender": gender,
            "birthDate": birth_date.isoformat(),
        },
        extensions=resource_extensions,
    )
    organization = _tagged_resource(
        "Organization",
        organization_id,
        {
            "active": True,
            "type": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                            "code": "prov",
                        }
                    ]
                }
            ],
        },
        extensions=resource_extensions,
    )
    encounter = _tagged_resource(
        "Encounter",
        encounter_id,
        {
            "status": "finished",
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": encounter_class,
            },
            "type": [
                {
                    "coding": [
                        {
                            "system": "https://example.org/CodeSystem/synthetic-encounter-type",
                            "code": encounter_type,
                        }
                    ]
                }
            ],
            "subject": {"reference": _reference("Patient", patient_id)},
            "serviceProvider": {"reference": _reference("Organization", organization_id)},
            "period": {
                "start": _fhir_datetime(encounter_start),
                "end": _fhir_datetime(encounter_end),
            },
        },
        extensions=resource_extensions,
    )
    condition = _tagged_resource(
        "Condition",
        condition_id,
        {
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "active",
                    }
                ]
            },
            "code": {
                "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": condition_code}]
            },
            "subject": {"reference": _reference("Patient", patient_id)},
            "encounter": {"reference": _reference("Encounter", encounter_id)},
            "recordedDate": _fhir_datetime(encounter_start + timedelta(minutes=18)),
        },
        extensions=resource_extensions,
    )
    observation = _tagged_resource(
        "Observation",
        observation_id,
        {
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "laboratory",
                        }
                    ]
                }
            ],
            "code": {"coding": [{"system": "http://loinc.org", "code": lab_code}]},
            "subject": {"reference": _reference("Patient", patient_id)},
            "encounter": {"reference": _reference("Encounter", encounter_id)},
            "effectiveDateTime": _fhir_datetime(result_effective),
            "issued": _fhir_datetime(result_issued),
            "performer": [{"reference": _reference("Organization", organization_id)}],
            "valueQuantity": {
                "value": round(lab_minimum + (seed % 40) * lab_span / 40, 1),
                "unit": lab_unit,
                "system": "http://unitsofmeasure.org",
                "code": lab_ucum_code,
            },
        },
        extensions=resource_extensions,
    )
    immunization = _tagged_resource(
        "Immunization",
        immunization_id,
        {
            "status": "completed",
            "vaccineCode": {
                "coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": vaccine_code}]
            },
            "patient": {"reference": _reference("Patient", patient_id)},
            "encounter": {"reference": _reference("Encounter", encounter_id)},
            "occurrenceDateTime": _fhir_datetime(encounter_start + timedelta(minutes=22)),
            "performer": [{"actor": {"reference": _reference("Organization", organization_id)}}],
            "primarySource": True,
            "protocolApplied": [{"doseNumberPositiveInt": vaccine_dose}],
        },
        extensions=resource_extensions,
    )
    service_request = _tagged_resource(
        "ServiceRequest",
        service_request_id,
        {
            "status": "completed",
            "intent": "order",
            "priority": priority,
            "code": {
                "coding": [
                    {
                        "system": "https://example.org/CodeSystem/synthetic-regulated-service",
                        "code": regulated_service,
                    }
                ],
            },
            "subject": {"reference": _reference("Patient", patient_id)},
            "encounter": {"reference": _reference("Encounter", encounter_id)},
            "authoredOn": _fhir_datetime(request_authored),
            "occurrenceDateTime": _fhir_datetime(request_completed),
            "requester": {"reference": _reference("Organization", organization_id)},
            "reasonReference": [{"reference": _reference("Condition", condition_id)}],
            "supportingInfo": [{"reference": _reference("Observation", observation_id)}],
            "performer": [{"reference": _reference("Organization", organization_id)}],
        },
        extensions=[
            *resource_extensions,
            {"url": SYNTHETIC_WAIT_EXTENSION_URL, "valueInteger": request_wait_hours},
            {
                "url": SYNTHETIC_COMPLETED_AT_EXTENSION_URL,
                "valueDateTime": _fhir_datetime(request_completed),
            },
        ],
    )
    # RPM demonstrativo: códigos e posologia inteiramente sintéticos. A modelagem
    # não representa uma prescrição real, nem constitui perfil homologado da RNDS.
    medication_request = _tagged_resource(
        "MedicationRequest",
        medication_request_id,
        {
            "status": "active",
            "intent": "order",
            "priority": priority,
            "medicationCodeableConcept": {
                "coding": [
                    {
                        "system": "https://example.org/CodeSystem/synthetic-medication",
                        "code": medication_code,
                    }
                ]
            },
            "subject": {"reference": _reference("Patient", patient_id)},
            "encounter": {"reference": _reference("Encounter", encounter_id)},
            "authoredOn": _fhir_datetime(medication_authored),
            "requester": {"reference": _reference("Organization", organization_id)},
            "reasonReference": [{"reference": _reference("Condition", condition_id)}],
            "dosageInstruction": [
                {
                    "route": {
                        "coding": [
                            {
                                "system": "https://example.org/CodeSystem/synthetic-route",
                                "code": medication_route,
                            }
                        ]
                    },
                    "doseAndRate": [
                        {
                            "doseQuantity": {
                                "value": (seed % 3) + 1,
                                "unit": medication_unit,
                                "system": "http://unitsofmeasure.org",
                                "code": medication_unit,
                            }
                        }
                    ],
                    "timing": {
                        "repeat": {"frequency": (seed % 3) + 1, "period": 1, "periodUnit": "d"}
                    },
                }
            ],
            "dispenseRequest": {
                "validityPeriod": {
                    "start": _fhir_datetime(medication_authored),
                    "end": _fhir_datetime(medication_valid_until),
                },
                "numberOfRepeatsAllowed": seed % 3,
                "quantity": {
                    "value": medication_quantity,
                    "unit": medication_unit,
                    "system": "http://unitsofmeasure.org",
                    "code": medication_unit,
                },
                "expectedSupplyDuration": {
                    "value": 30,
                    "unit": "d",
                    "system": "http://unitsofmeasure.org",
                    "code": "d",
                },
            },
        },
        extensions=resource_extensions,
    )
    targets = [
        patient,
        organization,
        encounter,
        condition,
        observation,
        immunization,
        service_request,
        medication_request,
    ]
    provenance = _tagged_resource(
        "Provenance",
        provenance_id,
        {
            "target": [
                {"reference": _reference(str(resource["resourceType"]), str(resource["id"]))}
                for resource in targets
            ],
            "recorded": _fhir_datetime(request_completed + timedelta(minutes=15)),
            "agent": [
                {
                    "type": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                                "code": "assembler",
                            }
                        ]
                    },
                    "who": {"reference": _reference("Organization", organization_id)},
                }
            ],
        },
        extensions=resource_extensions,
    )

    if scenario == "observation-temporal-reference":
        observation["effectiveDateTime"] = _fhir_datetime(result_issued + timedelta(days=1))
        service_request["reasonReference"] = [
            {"reference": "Condition/referencia-ausente-sintetica"}
        ]
    elif scenario == "rpm-validity-window":
        medication_request["dispenseRequest"]["validityPeriod"]["end"] = _fhir_datetime(
            medication_authored - timedelta(days=1)
        )
    elif scenario == "service-request-occurrence":
        service_request["occurrenceDateTime"] = _fhir_datetime(
            request_authored - timedelta(hours=1)
        )

    return {
        "resourceType": "Bundle",
        "id": _stable_id(seed, "Bundle"),
        "type": "collection",
        "meta": _bundle_meta((scenario,) if scenario is not None else ()),
        "timestamp": _fhir_datetime(request_completed + timedelta(minutes=15)),
        "entry": [_entry(resource) for resource in (*targets, provenance)],
    }


def iter_resources(bundle: JsonObject) -> Iterable[JsonObject]:
    """Itera recursos de um Bundle sem retornar ou registrar o payload bruto."""
    entries = bundle.get("entry", [])
    if not isinstance(entries, list):
        return
    for entry in entries:
        if isinstance(entry, dict):
            resource = entry.get("resource")
            if isinstance(resource, dict):
                yield resource
