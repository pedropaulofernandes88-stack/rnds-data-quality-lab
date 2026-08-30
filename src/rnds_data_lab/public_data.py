"""Carga opcional dos indicadores públicos e agregados da RNDS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import polars as pl

from rnds_data_lab.config import Settings
from rnds_data_lab.sources import (
    RNDS_PUBLIC_INDICATORS,
    download_csv_zip,
    parse_csv_zip,
)
from rnds_data_lab.storage import connect, initialize_schema

PUBLIC_CSV_URLS = {
    code: f"https://demas-dados-abertos.s3.amazonaws.com/csv/{code}rc.csv.zip"
    for code in RNDS_PUBLIC_INDICATORS
}

_REQUIRED_COLUMNS = {
    "co_anomes",
    "co_uf",
    "sg_uf",
    "no_uf",
    "co_regiao_brasil",
    "no_regiao_brasil",
    "vl_indicador_calculado_uf",
    "vl_indicador_calculado_reg",
    "vl_indicador_calculado_br",
    "dt_atualizacao",
    "sg_granularidade",
}


@dataclass(frozen=True, slots=True)
class IndicatorRefresh:
    code: str
    url: str
    source_sha256: str
    bytes_downloaded: int
    rows_read: int
    rows_inserted: int
    competencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicRefreshSummary:
    refreshed_at: datetime
    indicators: tuple[IndicatorRefresh, ...]

    @property
    def rows_inserted(self) -> int:
        return sum(item.rows_inserted for item in self.indicators)


def refresh_public_rnds_indicators(
    settings: Settings,
    *,
    codes: tuple[str, ...] | None = None,
    max_bytes_per_file: int = 5_000_000,
    timeout_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> PublicRefreshSummary:
    """Baixa e materializa apenas os indicadores agregados do portal oficial.

    Os arquivos ficam em ``data/raw`` (ignorado pelo Git). A função não acessa
    prontuários, credenciais ou endpoints assistenciais da RNDS.
    """

    selected = codes or tuple(RNDS_PUBLIC_INDICATORS)
    unknown = sorted(set(selected) - set(RNDS_PUBLIC_INDICATORS))
    if unknown:
        raise ValueError(f"Indicadores desconhecidos: {', '.join(unknown)}")

    settings.ensure_directories()
    raw_directory = settings.data_dir / "raw" / "rnds_public_indicators"
    raw_directory.mkdir(parents=True, exist_ok=True)
    summaries: list[IndicatorRefresh] = []

    with connect(settings.database_path) as connection:
        initialize_schema(connection)
        for code in selected:
            url = PUBLIC_CSV_URLS[code]
            archive_path = raw_directory / f"{code}.csv.zip"
            receipt = download_csv_zip(
                url,
                archive_path,
                max_bytes=max_bytes_per_file,
                timeout_seconds=timeout_seconds,
                transport=transport,
            )
            frame = _normalize_indicator_frame(parse_csv_zip(receipt.path), code=code)
            before = _scalar_int(
                connection.execute(
                    "SELECT COUNT(*) FROM rnds_public_indicators WHERE indicator_code = ?", [code]
                ).fetchone()
            )
            rows = [
                (
                    code,
                    RNDS_PUBLIC_INDICATORS[code].name,
                    row["competence"],
                    row["uf_code"],
                    row["uf_name"],
                    row["region_code"],
                    row["region_name"],
                    row["value_uf"],
                    row["value_region"],
                    row["value_brazil"],
                    row["updated_at"],
                    receipt.sha256,
                    receipt.extracted_at,
                )
                for row in frame.to_dicts()
            ]
            connection.executemany(
                """INSERT OR IGNORE INTO rnds_public_indicators VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            after = _scalar_int(
                connection.execute(
                    "SELECT COUNT(*) FROM rnds_public_indicators WHERE indicator_code = ?", [code]
                ).fetchone()
            )
            summaries.append(
                IndicatorRefresh(
                    code=code,
                    url=url,
                    source_sha256=receipt.sha256,
                    bytes_downloaded=receipt.bytes_downloaded,
                    rows_read=frame.height,
                    rows_inserted=after - before,
                    competencies=tuple(frame["competence"].unique().sort().to_list()),
                )
            )

    return PublicRefreshSummary(
        refreshed_at=datetime.now(tz=UTC),
        indicators=tuple(summaries),
    )


def _normalize_indicator_frame(frame: pl.DataFrame, *, code: str) -> pl.DataFrame:
    missing = sorted(_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"{code}: colunas ausentes: {', '.join(missing)}")

    normalized = frame.select(
        pl.col("co_anomes").cast(pl.Utf8).alias("competence"),
        pl.col("co_uf").cast(pl.Utf8).str.zfill(2).alias("uf_code"),
        pl.col("sg_uf").cast(pl.Utf8).alias("uf_abbreviation"),
        pl.col("no_uf").cast(pl.Utf8).alias("uf_name"),
        pl.col("co_regiao_brasil").cast(pl.Utf8).alias("region_code"),
        pl.col("no_regiao_brasil").cast(pl.Utf8).alias("region_name"),
        pl.col("vl_indicador_calculado_uf").cast(pl.Float64).alias("value_uf"),
        pl.col("vl_indicador_calculado_reg").cast(pl.Float64).alias("value_region"),
        pl.col("vl_indicador_calculado_br").cast(pl.Float64).alias("value_brazil"),
        pl.col("dt_atualizacao").cast(pl.Utf8).alias("updated_at"),
        pl.col("sg_granularidade").cast(pl.Utf8).alias("granularity"),
    )
    if normalized.null_count().select(pl.sum_horizontal(pl.all())).item() > 0:
        raise ValueError(f"{code}: valores obrigatórios ausentes")
    if not normalized["competence"].str.contains(r"^\d{6}$").all():
        raise ValueError(f"{code}: competência fora do formato AAAAMM")
    if normalized.filter(pl.col("granularity") != "UF").height:
        raise ValueError(f"{code}: granularidade diferente de UF")
    if normalized.select(["competence", "uf_code"]).is_duplicated().any():
        raise ValueError(f"{code}: competência/UF duplicada")
    if normalized.filter(
        (pl.col("value_uf") < 0) | (pl.col("value_region") < 0) | (pl.col("value_brazil") < 0)
    ).height:
        raise ValueError(f"{code}: indicador negativo")

    coverage = normalized.group_by("competence").agg(pl.col("uf_code").n_unique().alias("ufs"))
    if coverage.filter(pl.col("ufs") != 27).height:
        raise ValueError(f"{code}: alguma competência não cobre as 27 UFs")

    brazil_reconciliation = normalized.group_by("competence").agg(
        pl.col("value_uf").sum().alias("sum_uf"),
        pl.col("value_brazil").n_unique().alias("brazil_values"),
        pl.col("value_brazil").first().alias("brazil"),
    )
    if brazil_reconciliation.filter(
        (pl.col("brazil_values") != 1) | ((pl.col("sum_uf") - pl.col("brazil")).abs() > 0.5)
    ).height:
        raise ValueError(f"{code}: total Brasil não reconcilia com a soma das UFs")

    region_reconciliation = normalized.group_by(["competence", "region_code"]).agg(
        pl.col("value_uf").sum().alias("sum_uf"),
        pl.col("value_region").n_unique().alias("region_values"),
        pl.col("value_region").first().alias("region"),
    )
    if region_reconciliation.filter(
        (pl.col("region_values") != 1) | ((pl.col("sum_uf") - pl.col("region")).abs() > 0.5)
    ).height:
        raise ValueError(f"{code}: totais regionais não reconciliam com as UFs")

    return normalized.drop(["uf_abbreviation", "granularity"])


def _scalar_int(row: tuple[object, ...] | None) -> int:
    if row is None:
        raise RuntimeError("Consulta de contagem não retornou resultado")
    return int(str(row[0]))
