"""Relatório acadêmico reproduzível para as saídas sintéticas do laboratório.

O módulo mede somente a variação induzida pela geração sintética e pela
reamostragem. Ele não produz inferência sobre pessoas, serviços ou população
brasileira: esses dados não estão presentes neste repositório.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from rnds_data_lab.storage import connect
from rnds_data_lab.synthetic import (
    GROUND_TRUTH_SCENARIOS,
    ground_truth_scenarios,
    make_synthetic_bundle,
)
from rnds_data_lab.validation import validate_bundle

REPORT_VERSION = "1.0.0"
DEFAULT_BOOTSTRAP_RESAMPLES = 2_000
DEFAULT_BOOTSTRAP_SEED = 20_260_829
DEFAULT_CONFIDENCE_LEVEL = 0.95
WILSON_95_Z = 1.959963984540054


@dataclass(frozen=True, slots=True)
class PercentileInterval:
    """Intervalo bootstrap percentil para uma estatística de mediana."""

    estimate: float | None
    lower: float | None
    upper: float | None
    observations: int
    resamples: int
    confidence_level: float
    seed: int


@dataclass(frozen=True, slots=True)
class WilsonInterval:
    """IC de Wilson bilateral para uma proporção binomial."""

    estimate: float | None
    lower: float | None
    upper: float | None
    successes: int
    trials: int
    confidence_level: float


def bootstrap_median_percentile(
    values: Sequence[float],
    *,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> PercentileInterval:
    """Calcula IC percentil determinístico para a mediana.

    A geração é feita em blocos para limitar memória mesmo em experimentos
    sintéticos maiores. O ``seed`` é parte do resultado para permitir auditoria
    e repetição bit a bit da reamostragem, dada a mesma versão do NumPy.
    """

    if resamples < 1:
        raise ValueError("resamples deve ser maior ou igual a 1")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level deve estar estritamente entre 0 e 1")

    sample = np.asarray(values, dtype=np.float64)
    if sample.ndim != 1:
        raise ValueError("values deve ser uma sequência unidimensional")
    if not np.isfinite(sample).all():
        raise ValueError("values deve conter somente números finitos")
    if sample.size == 0:
        return PercentileInterval(
            estimate=None,
            lower=None,
            upper=None,
            observations=0,
            resamples=resamples,
            confidence_level=confidence_level,
            seed=seed,
        )

    generator = np.random.default_rng(seed)
    medians = np.empty(resamples, dtype=np.float64)
    # Até oito milhões de índices por bloco (~64 MiB em int64) mantém o custo
    # previsível sem alterar a sequência pseudoaleatória.
    block_size = max(1, min(resamples, 8_000_000 // sample.size))
    for start in range(0, resamples, block_size):
        stop = min(start + block_size, resamples)
        indices: npt.NDArray[np.int64] = generator.integers(
            0, sample.size, size=(stop - start, sample.size), dtype=np.int64
        )
        medians[start:stop] = np.median(sample[indices], axis=1)

    alpha = (1 - confidence_level) / 2
    lower, upper = np.quantile(medians, (alpha, 1 - alpha), method="linear")
    return PercentileInterval(
        estimate=float(np.median(sample)),
        lower=float(lower),
        upper=float(upper),
        observations=int(sample.size),
        resamples=resamples,
        confidence_level=confidence_level,
        seed=seed,
    )


def build_academic_report(
    database_path: Path,
    *,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """Produz um relatório JSON agregável e metodologicamente delimitado.

    Falha de forma explícita quando existir qualquer recurso não sintético em
    Bronze. Assim, a ferramenta não transforma acidentalmente dados reais em
    um relatório que se anuncia como experimento de simulação.
    """

    if not database_path.is_file():
        raise FileNotFoundError(f"Banco inexistente: {database_path}")

    with connect(database_path, read_only=True) as connection:
        non_synthetic = _scalar(
            connection, "SELECT COUNT(*) FROM bronze_resources WHERE NOT synthetic"
        )
        if non_synthetic:
            raise ValueError("O relatório acadêmico aceita exclusivamente recursos sintéticos")

        counts = {
            "ingestion_runs": _scalar(connection, "SELECT COUNT(*) FROM ingestion_runs"),
            "accepted_resources": _scalar(connection, "SELECT COUNT(*) FROM bronze_resources"),
            "synthetic_people": _scalar(connection, "SELECT COUNT(*) FROM dim_patient"),
            "federative_units": _scalar(
                connection,
                "SELECT COUNT(DISTINCT uf_code) FROM dim_patient WHERE uf_code IS NOT NULL",
            ),
            "quarantined_resources": _scalar(
                connection, "SELECT COALESCE(SUM(quarantined_count), 0) FROM ingestion_runs"
            ),
            "quality_issues": _scalar(connection, "SELECT COUNT(*) FROM quality_issues"),
        }
        wait_days = _metric_values(
            connection, "SELECT wait_days FROM fact_referral WHERE wait_days IS NOT NULL"
        )
        turnaround_hours = _metric_values(
            connection,
            "SELECT turnaround_hours FROM fact_lab_result WHERE turnaround_hours IS NOT NULL",
        )

    wait_interval = bootstrap_median_percentile(
        wait_days, resamples=resamples, seed=seed, confidence_level=confidence_level
    )
    turnaround_interval = bootstrap_median_percentile(
        turnaround_hours,
        resamples=resamples,
        seed=seed + 1,
        confidence_level=confidence_level,
    )
    return {
        "report_version": REPORT_VERSION,
        "data_scope": {
            "classification": "SYNTHETIC_ONLY",
            "unit_of_analysis": "eventos FHIR sintéticos aceitos no lakehouse local",
            "public_rnds_indicators_included": False,
            "non_synthetic_bronze_resources": non_synthetic,
        },
        "interpretation": {
            "uncertainty_scope": "variação da simulação e da reamostragem bootstrap",
            "not_population_inference": True,
            "not_clinical_effect_estimate": True,
            "not_service_performance_measurement": True,
            "warning": (
                "Os intervalos não estimam parâmetros populacionais, efeitos clínicos, "
                "desempenho assistencial ou resultados da RNDS."
            ),
        },
        "method": {
            "statistic": "mediana",
            "interval": "bootstrap percentil bilateral",
            "resamples": resamples,
            "confidence_level": confidence_level,
            "seed_wait_days": seed,
            "seed_turnaround_hours": seed + 1,
            "missing_values": "excluídos antes da estatística; contagem reportada em n",
        },
        "descriptive": {
            **counts,
            "referral_wait_days": _metric_summary(wait_days, wait_interval),
            "laboratory_turnaround_hours": _metric_summary(turnaround_hours, turnaround_interval),
        },
    }


def write_academic_report(report: dict[str, Any], destination: Path) -> Path:
    """Escreve JSON estável, sem payloads FHIR ou identificadores pessoais."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def wilson_interval_95(successes: int, trials: int) -> WilsonInterval:
    """Calcula IC95% de Wilson sem depender de SciPy.

    A constante normal usada é explicitada para que a implementação seja
    auditável e não dependa de tabelas externas durante a execução local.
    """

    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("sucessos deve estar entre zero e trials")
    if trials == 0:
        return WilsonInterval(None, None, None, successes, trials, 0.95)

    proportion = successes / trials
    z_squared = WILSON_95_Z**2
    denominator = 1 + z_squared / trials
    center = (proportion + z_squared / (2 * trials)) / denominator
    margin = (
        WILSON_95_Z
        * ((proportion * (1 - proportion) / trials + z_squared / (4 * trials**2)) ** 0.5)
        / denominator
    )
    lower = 0.0 if successes == 0 else max(0.0, center - margin)
    upper = 1.0 if successes == trials else min(1.0, center + margin)
    return WilsonInterval(
        estimate=proportion,
        lower=lower,
        upper=upper,
        successes=successes,
        trials=trials,
        confidence_level=0.95,
    )


def evaluate_validator_benchmark(
    *, seed: int = DEFAULT_BOOTSTRAP_SEED, samples_per_class: int = 100
) -> dict[str, Any]:
    """Avalia o validador contra cenários sintéticos de ground truth.

    Cada classe contém exatamente ``samples_per_class`` Bundles. A classe
    ``valid`` é negativa; cada um dos cenários em
    :data:`GROUND_TRUTH_SCENARIOS` é positivo. A decisão predita é a rejeição
    do Bundle inteiro pelo validador. O método mede apenas este experimento
    controlado e não estima validade clínica, da RNDS ou de implementações
    externas de FHIR.
    """

    if samples_per_class < 1:
        raise ValueError("samples_per_class deve ser maior ou igual a 1")

    class_names = ("valid", *GROUND_TRUTH_SCENARIOS)
    scenario_results: dict[str, dict[str, Any]] = {}
    all_positive: list[bool] = []
    all_predicted_positive: list[bool] = []
    valid_predictions, _ = _validator_predictions(
        seed=seed,
        samples=samples_per_class,
        error_scenario=None,
    )
    for index, scenario in enumerate(GROUND_TRUTH_SCENARIOS, start=1):
        scenario_seed = seed + index * samples_per_class
        predicted_positive, expected_rule_hits = _validator_predictions(
            seed=scenario_seed,
            samples=samples_per_class,
            error_scenario=scenario,
        )
        confusion = _confusion_matrix(
            actual_positive=[True] * samples_per_class + [False] * samples_per_class,
            predicted_positive=[*predicted_positive, *valid_predictions],
        )
        scenario_results[scenario] = {
            "ground_truth": {
                "positive_label": scenario,
                "expected_validation_codes": list(GROUND_TRUTH_SCENARIOS[scenario]),
                "positive_bundles": samples_per_class,
                "negative_valid_bundles": samples_per_class,
            },
            "confusion_matrix_bundle_level": confusion,
            "metrics": _proportion_metrics(confusion),
            "expected_rule_coverage": {
                "detected_bundles": expected_rule_hits,
                "eligible_bundles": samples_per_class,
                "proportion": asdict(wilson_interval_95(expected_rule_hits, samples_per_class)),
            },
        }
        all_positive.extend([True] * samples_per_class)
        all_predicted_positive.extend(predicted_positive)

    all_positive.extend([False] * samples_per_class)
    all_predicted_positive.extend(valid_predictions)
    global_confusion = _confusion_matrix(all_positive, all_predicted_positive)
    return {
        "report_version": REPORT_VERSION,
        "experiment": {
            "unit_of_analysis": "Bundle FHIR sintético",
            "seed": seed,
            "samples_per_class": samples_per_class,
            "classes": list(class_names),
            "ground_truth": (
                "classe valid sem tag de cenário; classes positivas registradas em "
                "Bundle.meta.tag com sistema controlado do laboratório"
            ),
            "decision_rule": "positivo = Bundle rejeitado por validate_bundle",
            "seed_allocation": "valid=seed; cenário i=seed + i*samples_per_class",
        },
        "interpretation": {
            "uncertainty_scope": "amostragem finita do experimento sintético controlado",
            "not_clinical_validity": True,
            "not_rnds_validation": True,
            "not_population_inference": True,
            "warning": (
                "Sensibilidade, especificidade e precisão referem-se apenas aos três "
                "cenários sintéticos e aos Bundles válidos gerados neste experimento."
            ),
        },
        "method": {
            "confusion_matrix_level": "Bundle",
            "interval": "Wilson bilateral 95%",
            "z_value": WILSON_95_Z,
            "positive_classes": list(GROUND_TRUTH_SCENARIOS),
            "negative_class": "valid",
        },
        "by_scenario": scenario_results,
        "global": {
            "ground_truth": {
                "positive_bundles": len(GROUND_TRUTH_SCENARIOS) * samples_per_class,
                "negative_valid_bundles": samples_per_class,
            },
            "confusion_matrix_bundle_level": global_confusion,
            "metrics": _proportion_metrics(global_confusion),
        },
    }


def _scalar(connection: Any, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _metric_values(connection: Any, sql: str) -> list[float]:
    values: list[float] = []
    for row in connection.execute(sql).fetchall():
        value = float(row[0])
        if not isfinite(value):
            raise ValueError("A métrica do banco contém valor não finito")
        values.append(value)
    return values


def _metric_summary(values: Sequence[float], interval: PercentileInterval) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p90": None,
            "median_bootstrap_percentile_ci": asdict(interval),
        }
    sample = np.asarray(values, dtype=np.float64)
    return {
        "n": len(values),
        "mean": float(np.mean(sample)),
        "median": float(np.median(sample)),
        "p90": float(np.quantile(sample, 0.9, method="linear")),
        "median_bootstrap_percentile_ci": asdict(interval),
    }


def _validator_predictions(
    *, seed: int, samples: int, error_scenario: str | None
) -> tuple[list[bool], int]:
    predictions: list[bool] = []
    expected_codes = set(GROUND_TRUTH_SCENARIOS[error_scenario]) if error_scenario else set()
    expected_rule_hits = 0
    for offset in range(samples):
        bundle = make_synthetic_bundle(seed + offset, error_scenario=error_scenario)
        scenarios = ground_truth_scenarios(bundle)
        if error_scenario is None and scenarios:
            raise RuntimeError("Bundle válido não pode declarar ground truth positivo")
        if error_scenario is not None and scenarios != (error_scenario,):
            raise RuntimeError("Ground truth do Bundle divergente do cenário solicitado")
        validation = validate_bundle(bundle)
        predictions.append(not validation.valid)
        if expected_codes <= {issue.code for issue in validation.issues}:
            expected_rule_hits += 1
    return predictions, expected_rule_hits


def _confusion_matrix(
    actual_positive: Sequence[bool], predicted_positive: Sequence[bool]
) -> dict[str, int]:
    if len(actual_positive) != len(predicted_positive):
        raise ValueError("rótulos reais e predições devem ter o mesmo tamanho")
    true_positive = sum(
        actual and predicted
        for actual, predicted in zip(actual_positive, predicted_positive, strict=True)
    )
    false_negative = sum(
        actual and not predicted
        for actual, predicted in zip(actual_positive, predicted_positive, strict=True)
    )
    false_positive = sum(
        not actual and predicted
        for actual, predicted in zip(actual_positive, predicted_positive, strict=True)
    )
    true_negative = sum(
        not actual and not predicted
        for actual, predicted in zip(actual_positive, predicted_positive, strict=True)
    )
    return {
        "true_positive": true_positive,
        "false_negative": false_negative,
        "false_positive": false_positive,
        "true_negative": true_negative,
        "total": len(actual_positive),
    }


def _proportion_metrics(confusion: dict[str, int]) -> dict[str, dict[str, float | int | None]]:
    return {
        "sensitivity": asdict(
            wilson_interval_95(
                confusion["true_positive"],
                confusion["true_positive"] + confusion["false_negative"],
            )
        ),
        "specificity": asdict(
            wilson_interval_95(
                confusion["true_negative"],
                confusion["true_negative"] + confusion["false_positive"],
            )
        ),
        "precision": asdict(
            wilson_interval_95(
                confusion["true_positive"],
                confusion["true_positive"] + confusion["false_positive"],
            )
        ),
    }
