from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import polars as pl
import pytest

from rnds_data_lab.config import Settings
from rnds_data_lab.public_data import _normalize_indicator_frame, refresh_public_rnds_indicators
from rnds_data_lab.storage import connect


def _public_frame(*, brazil_offset: float = 0.0) -> pl.DataFrame:
    ufs = [f"{number:02d}" for number in range(1, 28)]
    regions = ["N", "NE", "CO", "SE", "S"]
    region_for_uf = [regions[index // 6] if index < 24 else "S" for index in range(27)]
    values = [float(number) for number in range(1, 28)]
    regional_totals = {
        region: sum(
            value
            for value, assigned in zip(values, region_for_uf, strict=True)
            if assigned == region
        )
        for region in regions
    }
    brazil = sum(values) + brazil_offset
    return pl.DataFrame(
        {
            "co_anomes": [202606] * 27,
            "co_uf": ufs,
            "sg_uf": [f"U{number:02d}" for number in range(1, 28)],
            "no_uf": [f"UF {number:02d}" for number in range(1, 28)],
            "co_regiao_brasil": region_for_uf,
            "no_regiao_brasil": region_for_uf,
            "vl_indicador_calculado_uf": values,
            "vl_indicador_calculado_reg": [regional_totals[region] for region in region_for_uf],
            "vl_indicador_calculado_br": [brazil] * 27,
            "dt_atualizacao": ["2026-08-07T00:00:00Z"] * 27,
            "sg_granularidade": ["UF"] * 27,
        }
    )


def _zip_frame(frame: pl.DataFrame) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("indicadores.csv", frame.write_csv())
    return output.getvalue()


def test_normalization_preserves_canonical_columns_and_reconciles_all_totals() -> None:
    normalized = _normalize_indicator_frame(_public_frame(), code="sdigi008")

    assert normalized.columns == [
        "competence",
        "uf_code",
        "uf_name",
        "region_code",
        "region_name",
        "value_uf",
        "value_region",
        "value_brazil",
        "updated_at",
    ]
    assert normalized.height == 27
    assert normalized["competence"].unique().to_list() == ["202606"]
    assert normalized["uf_code"].to_list()[0] == "01"


def test_normalization_rejects_unreconciled_brazil_total_and_missing_uf() -> None:
    with pytest.raises(ValueError, match="Brasil não reconcilia"):
        _normalize_indicator_frame(_public_frame(brazil_offset=3), code="sdigi008")
    with pytest.raises(ValueError, match="27 UFs"):
        _normalize_indicator_frame(_public_frame().head(26), code="sdigi008")


def test_public_refresh_is_offline_mocked_and_idempotent(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    payload = _zip_frame(_public_frame())

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": str(len(payload))},
            content=payload,
        )

    transport = httpx.MockTransport(handler)

    first = refresh_public_rnds_indicators(settings, codes=("sdigi008",), transport=transport)
    second = refresh_public_rnds_indicators(settings, codes=("sdigi008",), transport=transport)

    assert first.rows_inserted == 27
    assert second.rows_inserted == 0
    assert first.indicators[0].competencies == ("202606",)
    with connect(settings.database_path, read_only=True) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM rnds_public_indicators").fetchone()[0])
        assert count == 27
