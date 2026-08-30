"""API somente de agregados e validação sem persistência de payload."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response, status

from rnds_data_lab import __version__
from rnds_data_lab.config import Settings
from rnds_data_lab.storage import connect, initialize_schema, query_dicts
from rnds_data_lab.validation import validate_bundle

MAX_VALIDATION_BODY_BYTES = 2_000_000


def create_app(settings: Settings | None = None) -> FastAPI:
    effective_settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        effective_settings.ensure_directories()
        with connect(effective_settings.database_path) as connection:
            initialize_schema(connection)
        yield

    app = FastAPI(
        title="RNDS Data Quality Lab",
        summary="Analytics agregados e validação demonstrativa FHIR R4",
        description=(
            "Laboratório independente com dados sintéticos e indicadores públicos agregados. "
            "Não é um serviço oficial, homologado ou conectado à RNDS assistencial."
        ),
        version=__version__,
        lifespan=lifespan,
        contact={"name": "Projeto no GitHub"},
        license_info={"name": "MIT"},
    )

    @app.middleware("http")
    async def limit_validation_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/v1/fhir/validate":
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    declared_bytes = int(content_length)
                except ValueError:
                    declared_bytes = MAX_VALIDATION_BODY_BYTES + 1
                if declared_bytes > MAX_VALIDATION_BODY_BYTES:
                    return Response(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        content="Payload excede o limite de validação",
                    )
        return await call_next(request)

    @app.get("/health", tags=["operacional"])
    def health() -> dict[str, Any]:
        with connect(effective_settings.database_path, read_only=True) as connection:
            count_row = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()
            run_count = int(count_row[0]) if count_row else 0
        return {"status": "ok", "version": __version__, "runs": run_count}

    @app.get("/v1/metadata", tags=["governança"])
    def metadata() -> dict[str, Any]:
        return {
            "data_classification": ["SYNTHETIC", "PUBLIC_AGGREGATE"],
            "individual_records_exposed": False,
            "rnds_connection": False,
            "rnds_homologation": False,
            "demonstrative_models": ["RIA", "RAC", "REL", "RIRA", "RPM"],
            "small_cell_threshold": effective_settings.minimum_public_cell_size,
            "contract_version": effective_settings.contract_version,
        }

    @app.post("/v1/fhir/validate", tags=["qualidade"])
    def validate_fhir(
        bundle: Annotated[dict[str, Any], Body(description="Bundle FHIR R4 demonstrativo")],
    ) -> dict[str, Any]:
        result = validate_bundle(bundle)
        return {
            "valid": result.valid,
            "resource_count": result.resource_count,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "resource_type": issue.resource_type,
                    "resource_id": issue.resource_id,
                    "path": issue.path,
                    "message": issue.message,
                }
                for issue in result.issues
            ],
            "payload_persisted": False,
            "payload_echoed": False,
        }

    @app.get("/v1/quality/runs", tags=["qualidade"])
    def quality_runs(limit: int = Query(20, ge=1, le=200)) -> list[dict[str, Any]]:
        return _query(
            effective_settings,
            """SELECT * FROM mart_quality_by_run
               ORDER BY completed_at DESC NULLS LAST LIMIT ?""",
            [limit],
        )

    @app.get("/v1/quality/issues", tags=["qualidade"])
    def quality_issues(
        run_id: str | None = Query(None, max_length=120),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        if run_id:
            return _query(
                effective_settings,
                """SELECT * FROM mart_quality_issues WHERE run_id = ?
                   ORDER BY issue_count DESC LIMIT ?""",
                [run_id, limit],
            )
        return _query(
            effective_settings,
            """SELECT * FROM mart_quality_issues
               ORDER BY run_id DESC, issue_count DESC LIMIT ?""",
            [limit],
        )

    @app.get("/v1/analytics/access", tags=["analytics"])
    def access(
        uf: str | None = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows = _filtered_mart(effective_settings, "mart_access_monthly", uf=uf, limit=limit)
        return _suppress_rows(
            rows,
            count_field="referrals",
            derived_fields=("mean_wait_days", "median_wait_days", "p90_wait_days"),
            minimum=effective_settings.minimum_public_cell_size,
        )

    @app.get("/v1/analytics/laboratory", tags=["analytics"])
    def laboratory(
        uf: str | None = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows = _filtered_mart(effective_settings, "mart_laboratory_monthly", uf=uf, limit=limit)
        return _suppress_rows(
            rows,
            count_field="results",
            derived_fields=(
                "mean_turnaround_hours",
                "median_turnaround_hours",
                "p90_turnaround_hours",
            ),
            minimum=effective_settings.minimum_public_cell_size,
        )

    @app.get("/v1/analytics/immunization", tags=["analytics"])
    def immunization(
        uf: str | None = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows = _filtered_mart(effective_settings, "mart_immunization_monthly", uf=uf, limit=limit)
        return _suppress_rows(
            rows,
            count_field="doses",
            derived_fields=(),
            minimum=effective_settings.minimum_public_cell_size,
        )

    @app.get("/v1/analytics/medication", tags=["analytics"])
    def medication(
        uf: str | None = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows = _filtered_mart(effective_settings, "mart_medication_monthly", uf=uf, limit=limit)
        return _suppress_rows(
            rows,
            count_field="prescriptions",
            derived_fields=(
                "mean_dose_value",
                "mean_frequency_per_period",
                "mean_quantity",
                "mean_expected_supply_days",
            ),
            minimum=effective_settings.minimum_public_cell_size,
        )

    @app.get("/v1/analytics/conditions", tags=["analytics"])
    def conditions(
        uf: str | None = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows = _filtered_mart(effective_settings, "mart_condition_monthly", uf=uf, limit=limit)
        return _suppress_rows(
            rows,
            count_field="conditions",
            derived_fields=(),
            minimum=effective_settings.minimum_public_cell_size,
        )

    @app.get("/v1/analytics/demographics", tags=["analytics"])
    def demographics(
        uf: str | None = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
        limit: int = Query(200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows = _filtered_mart(effective_settings, "mart_demographic_profile", uf=uf, limit=limit)
        return _suppress_rows(
            rows,
            count_field="synthetic_people",
            derived_fields=(),
            minimum=effective_settings.minimum_public_cell_size,
        )

    @app.get("/v1/interoperability/model-volume", tags=["qualidade"])
    def model_volume(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return _query(
            effective_settings,
            """SELECT * FROM mart_model_volume
               ORDER BY resources DESC, model, resource_type LIMIT ?""",
            [limit],
        )

    @app.get("/v1/rnds/public-indicators", tags=["RNDS pública"])
    def public_indicators(
        indicator: str | None = Query(None, pattern=r"^sdigi\d{3}$"),
        competence: str | None = Query(None, pattern=r"^\d{6}$"),
        limit: int = Query(200, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        parameters: list[object] = []
        if indicator:
            parameters.append(indicator)
        if competence:
            parameters.append(competence)
        parameters.append(limit)
        if indicator and competence:
            sql = """SELECT * FROM mart_rnds_public_indicators
                     WHERE indicator_code = ? AND competence = ?
                     ORDER BY competence DESC, indicator_code, uf_code LIMIT ?"""
        elif indicator:
            sql = """SELECT * FROM mart_rnds_public_indicators
                     WHERE indicator_code = ?
                     ORDER BY competence DESC, indicator_code, uf_code LIMIT ?"""
        elif competence:
            sql = """SELECT * FROM mart_rnds_public_indicators
                     WHERE competence = ?
                     ORDER BY competence DESC, indicator_code, uf_code LIMIT ?"""
        else:
            sql = """SELECT * FROM mart_rnds_public_indicators
                     ORDER BY competence DESC, indicator_code, uf_code LIMIT ?"""
        return _query(effective_settings, sql, parameters)

    @app.get("/v1/rnds/brazil-trend", tags=["RNDS pública"])
    def brazil_trend(
        indicator: str | None = Query(None, pattern=r"^sdigi\d{3}$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        if indicator:
            return _query(
                effective_settings,
                """SELECT * FROM mart_rnds_brazil_trend WHERE indicator_code = ?
                   ORDER BY competence DESC LIMIT ?""",
                [indicator, limit],
            )
        return _query(
            effective_settings,
            """SELECT * FROM mart_rnds_brazil_trend
               ORDER BY indicator_code, competence DESC LIMIT ?""",
            [limit],
        )

    return app


def _query(settings: Settings, sql: str, parameters: list[object]) -> list[dict[str, Any]]:
    try:
        with connect(settings.database_path, read_only=True) as connection:
            return query_dicts(connection, sql, parameters)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Camada analítica indisponível") from exc


def _filtered_mart(
    settings: Settings, mart: str, *, uf: str | None, limit: int
) -> list[dict[str, Any]]:
    allowed_marts = {
        "mart_access_monthly",
        "mart_laboratory_monthly",
        "mart_immunization_monthly",
        "mart_medication_monthly",
        "mart_condition_monthly",
        "mart_demographic_profile",
    }
    if mart not in allowed_marts:
        raise ValueError("mart não permitido")
    filtered_sql = {
        "mart_access_monthly": (
            "SELECT * FROM mart_access_monthly WHERE uf_code = ? ORDER BY period DESC LIMIT ?"
        ),
        "mart_laboratory_monthly": (
            "SELECT * FROM mart_laboratory_monthly WHERE uf_code = ? ORDER BY period DESC LIMIT ?"
        ),
        "mart_immunization_monthly": (
            "SELECT * FROM mart_immunization_monthly WHERE uf_code = ? ORDER BY period DESC LIMIT ?"
        ),
        "mart_medication_monthly": (
            "SELECT * FROM mart_medication_monthly WHERE uf_code = ? ORDER BY period DESC LIMIT ?"
        ),
        "mart_condition_monthly": (
            "SELECT * FROM mart_condition_monthly WHERE uf_code = ? ORDER BY period DESC LIMIT ?"
        ),
        "mart_demographic_profile": (
            "SELECT * FROM mart_demographic_profile WHERE uf_code = ? LIMIT ?"
        ),
    }
    unfiltered_sql = {
        "mart_access_monthly": "SELECT * FROM mart_access_monthly ORDER BY period DESC LIMIT ?",
        "mart_laboratory_monthly": (
            "SELECT * FROM mart_laboratory_monthly ORDER BY period DESC LIMIT ?"
        ),
        "mart_immunization_monthly": (
            "SELECT * FROM mart_immunization_monthly ORDER BY period DESC LIMIT ?"
        ),
        "mart_medication_monthly": (
            "SELECT * FROM mart_medication_monthly ORDER BY period DESC LIMIT ?"
        ),
        "mart_condition_monthly": (
            "SELECT * FROM mart_condition_monthly ORDER BY period DESC LIMIT ?"
        ),
        "mart_demographic_profile": "SELECT * FROM mart_demographic_profile LIMIT ?",
    }
    return _query(
        settings,
        filtered_sql[mart] if uf else unfiltered_sql[mart],
        [uf, limit] if uf else [limit],
    )


def _suppress_rows(
    rows: list[dict[str, Any]],
    *,
    count_field: str,
    derived_fields: tuple[str, ...],
    minimum: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        protected = dict(row)
        count = protected.get(count_field)
        if isinstance(count, int) and count < minimum:
            protected[count_field] = None
            for field in derived_fields:
                protected[field] = None
            protected["suppressed"] = True
        else:
            protected["suppressed"] = False
        output.append(protected)
    return output


app = create_app()
