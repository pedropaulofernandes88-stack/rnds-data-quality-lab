"""Orquestração reproduzível do pipeline sintético FHIR."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from rnds_data_lab.config import Settings
from rnds_data_lab.storage import (
    QualityIssueRecord,
    RunSummary,
    canonical_json,
    connect,
    initialize_schema,
    store_run,
)
from rnds_data_lab.synthetic import ground_truth_scenarios, iter_resources, make_synthetic_bundle
from rnds_data_lab.validation import validate_bundle

_SAFE_RUN_ID = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Resumo sem payload clínico do processamento de um lote."""

    run: RunSummary
    requested_patients: int
    valid_bundles: int
    quarantined_bundles: int
    quarantine_manifest: Path | None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["run"]["database_path"] = str(self.run.database_path)
        value["quarantine_manifest"] = (
            str(self.quarantine_manifest) if self.quarantine_manifest else None
        )
        return value


def deterministic_run_id(*, seed: int, patients: int, invalid_every: int) -> str:
    """Identifica semanticamente uma entrada para facilitar testes de idempotência."""

    signature = f"seed={seed}|patients={patients}|invalid_every={invalid_every}"
    suffix = sha256(signature.encode()).hexdigest()[:12]
    return f"synthetic-s{seed}-n{patients}-e{invalid_every}-{suffix}"


def _safe_run_id(value: str) -> str:
    cleaned = _SAFE_RUN_ID.sub("-", value).strip(".-")
    if not cleaned or len(cleaned) > 120:
        raise ValueError("run_id deve conter de 1 a 120 caracteres seguros")
    return cleaned


def run_synthetic_pipeline(
    settings: Settings,
    *,
    patients: int = 250,
    seed: int = 42,
    invalid_every: int = 17,
    run_id: str | None = None,
) -> PipelineResult:
    """Gera, valida, quarentena e materializa recursos inteiramente sintéticos.

    Um ``invalid_every`` igual a zero desativa a injeção de falhas. Lotes
    inválidos são rejeitados integralmente, evitando análises sobre registros
    parcialmente consistentes.
    """

    if not 1 <= patients <= 100_000:
        raise ValueError("patients deve estar entre 1 e 100000")
    if invalid_every < 0:
        raise ValueError("invalid_every não pode ser negativo")

    settings.ensure_directories()
    effective_run_id = _safe_run_id(
        run_id or deterministic_run_id(seed=seed, patients=patients, invalid_every=invalid_every)
    )
    accepted: list[dict[str, Any]] = []
    quality_issues: list[QualityIssueRecord] = []
    quarantine_rows: list[dict[str, Any]] = []
    valid_bundles = 0
    quarantined_bundles = 0
    quarantined_resources = 0

    for offset in range(patients):
        bundle_seed = seed + offset
        inject_errors = invalid_every > 0 and (offset + 1) % invalid_every == 0
        bundle = make_synthetic_bundle(bundle_seed, inject_errors=inject_errors)
        resources = list(iter_resources(bundle))
        result = validate_bundle(bundle)
        if result.valid:
            valid_bundles += 1
            accepted.extend(resources)
            continue

        quarantined_bundles += 1
        quarantined_resources += len(resources)
        bundle_id = str(bundle.get("id", f"bundle-seed-{bundle_seed}"))
        bundle_digest = sha256(canonical_json(bundle).encode()).hexdigest()
        scenarios = ground_truth_scenarios(bundle)
        for issue in result.issues:
            resource_type = issue.resource_type or "Bundle"
            resource_id = issue.resource_id or bundle_id
            quality_issues.append(
                QualityIssueRecord(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    code=issue.code,
                    severity=issue.severity,
                    message=issue.message,
                )
            )
            quarantine_rows.append(
                {
                    "run_id": effective_run_id,
                    "bundle_id": bundle_id,
                    "bundle_sha256": bundle_digest,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "code": issue.code,
                    "severity": issue.severity,
                    "path": issue.path,
                    "ground_truth_scenarios": list(scenarios),
                }
            )

    quarantine_path = _write_quarantine_manifest(
        settings.data_dir / "quarantine" / f"{effective_run_id}.jsonl",
        quarantine_rows,
    )
    with connect(settings.database_path) as connection:
        initialize_schema(connection)
        summary = store_run(
            connection,
            run_id=effective_run_id,
            seed=seed,
            requested_patients=patients,
            contract_version=settings.contract_version,
            accepted=accepted,
            issues=quality_issues,
            quarantined_count=quarantined_resources,
        )

    return PipelineResult(
        run=summary,
        requested_patients=patients,
        valid_bundles=valid_bundles,
        quarantined_bundles=quarantined_bundles,
        quarantine_manifest=quarantine_path,
    )


def _write_quarantine_manifest(path: Path, rows: list[dict[str, Any]]) -> Path | None:
    """Grava somente metadados e hashes; nunca o payload rejeitado."""

    if not rows:
        if path.exists():
            path.unlink()
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(f"{serialized}\n", encoding="utf-8")
    return path
