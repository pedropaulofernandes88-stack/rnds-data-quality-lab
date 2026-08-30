from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rnds_data_lab.api import MAX_VALIDATION_BODY_BYTES, create_app
from rnds_data_lab.config import Settings
from rnds_data_lab.pipeline import run_synthetic_pipeline
from rnds_data_lab.storage import connect, initialize_schema
from rnds_data_lab.synthetic import make_synthetic_bundle


def _settings(tmp_path: Path) -> Settings:
    return Settings.load(tmp_path)


def test_api_exposes_only_aggregates_and_suppresses_small_cells(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    run_synthetic_pipeline(settings, patients=3, seed=2, invalid_every=0)

    with TestClient(create_app(settings)) as client:
        metadata = client.get("/v1/metadata")
        assert metadata.status_code == 200
        assert metadata.json()["individual_records_exposed"] is False
        assert metadata.json()["rnds_connection"] is False
        assert metadata.json()["demonstrative_models"] == ["RIA", "RAC", "REL", "RIRA", "RPM"]

        access = client.get("/v1/analytics/access")
        assert access.status_code == 200
        access_rows = access.json()
        assert access_rows
        for row in access_rows:
            assert "payload_json" not in row
            assert row["referrals"] is None
            assert row["mean_wait_days"] is None
            assert row["median_wait_days"] is None
            assert row["p90_wait_days"] is None
            assert row["suppressed"] is True

        laboratory = client.get("/v1/analytics/laboratory")
        assert laboratory.status_code == 200
        assert all(
            row["suppressed"] is True and row["results"] is None for row in laboratory.json()
        )

        medication = client.get("/v1/analytics/medication")
        assert medication.status_code == 200
        assert all(
            row["suppressed"] is True and row["prescriptions"] is None for row in medication.json()
        )

        schema_paths = client.get("/openapi.json").json()["paths"]
        assert not any("bronze" in path or "patient" in path for path in schema_paths)


def test_validation_endpoint_never_echoes_or_persists_request_payload_and_limits_body(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    distinctive = "request-secret-marker-should-never-return"
    bundle = make_synthetic_bundle(seed=77)
    bundle["entry"][0]["resource"]["text"] = {"status": "generated", "div": distinctive}

    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/fhir/validate", json=bundle)
        assert response.status_code == 200
        body = response.json()
        assert body["payload_persisted"] is False
        assert body["payload_echoed"] is False
        assert distinctive not in response.text
        assert client.get("/health").json()["runs"] == 0

        oversized = b"{" + (b" " * MAX_VALIDATION_BODY_BYTES) + b"}"
        too_large = client.post(
            "/v1/fhir/validate",
            content=oversized,
            headers={"content-type": "application/json"},
        )
        assert too_large.status_code == 413
        assert "excede" in too_large.text

        # The aggregate endpoint remains JSON-only and has no route parameter that accepts payloads.
        assert json.dumps(client.get("/openapi.json").json())


def test_api_covers_aggregate_filters_public_indicators_and_query_validation(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    run_synthetic_pipeline(settings, patients=12, seed=202, invalid_every=3)
    with connect(settings.database_path) as connection:
        initialize_schema(connection)
        connection.executemany(
            """INSERT INTO rnds_public_indicators VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())""",
            [
                (
                    "sdigi008",
                    "Registros",
                    "202605",
                    "35",
                    "São Paulo",
                    "SE",
                    "Sudeste",
                    9.0,
                    9.0,
                    9.0,
                    None,
                    "a" * 64,
                ),
                (
                    "sdigi008",
                    "Registros",
                    "202606",
                    "35",
                    "São Paulo",
                    "SE",
                    "Sudeste",
                    10.0,
                    10.0,
                    10.0,
                    None,
                    "b" * 64,
                ),
                (
                    "sdigi009",
                    "RIA",
                    "202606",
                    "33",
                    "Rio de Janeiro",
                    "SE",
                    "Sudeste",
                    8.0,
                    18.0,
                    18.0,
                    None,
                    "c" * 64,
                ),
            ],
        )

    with TestClient(create_app(settings)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["runs"] == 1
        assert client.get("/v1/quality/runs", params={"limit": 1}).json()[0]["run_id"]
        assert client.get("/v1/quality/issues", params={"run_id": "missing"}).json() == []
        assert client.get("/v1/quality/issues").json()

        endpoint_expectations = {
            "/v1/analytics/access": "referrals",
            "/v1/analytics/laboratory": "results",
            "/v1/analytics/immunization": "doses",
            "/v1/analytics/medication": "prescriptions",
            "/v1/analytics/conditions": "conditions",
            "/v1/analytics/demographics": "synthetic_people",
        }
        for endpoint, count_field in endpoint_expectations.items():
            rows = client.get(endpoint, params={"limit": 500}).json()
            assert rows
            assert all("suppressed" in row and count_field in row for row in rows)
            uf = rows[0]["uf_code"]
            filtered = client.get(endpoint, params={"uf": uf, "limit": 1})
            assert filtered.status_code == 200
            assert all(row["uf_code"] == uf for row in filtered.json())

        assert client.get("/v1/interoperability/model-volume", params={"limit": 1}).json()
        assert client.get("/v1/analytics/access", params={"uf": "sp"}).status_code == 422
        assert client.get("/v1/quality/runs", params={"limit": 0}).status_code == 422

        assert len(client.get("/v1/rnds/public-indicators").json()) == 3
        by_indicator = client.get("/v1/rnds/public-indicators", params={"indicator": "sdigi008"})
        by_competence = client.get("/v1/rnds/public-indicators", params={"competence": "202606"})
        assert len(by_indicator.json()) == 2
        assert len(by_competence.json()) == 2
        exact = client.get(
            "/v1/rnds/public-indicators",
            params={"indicator": "sdigi008", "competence": "202606"},
        ).json()
        assert exact[0]["value_uf"] == 10.0
        invalid_indicator = client.get("/v1/rnds/public-indicators", params={"indicator": "bad"})
        assert invalid_indicator.status_code == 422
        assert len(client.get("/v1/rnds/brazil-trend").json()) == 3
        by_trend_indicator = client.get("/v1/rnds/brazil-trend", params={"indicator": "sdigi008"})
        assert len(by_trend_indicator.json()) == 2
