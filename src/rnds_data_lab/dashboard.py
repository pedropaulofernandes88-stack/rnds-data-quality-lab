"""Painel Streamlit para exploração exclusivamente agregada."""

from __future__ import annotations

from typing import Any

import plotly.express as px
import polars as pl
import streamlit as st

from rnds_data_lab.config import Settings
from rnds_data_lab.storage import connect, query_dicts


def _rows(
    settings: Settings, sql: str, parameters: list[object] | None = None
) -> list[dict[str, Any]]:
    with connect(settings.database_path, read_only=True) as connection:
        return query_dicts(connection, sql, parameters)


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def render() -> None:
    settings = Settings.load()
    st.set_page_config(page_title="RNDS Data Quality Lab", page_icon="🧬", layout="wide")
    st.title("RNDS Data Quality Lab")
    st.caption(
        "Laboratório independente · FHIR R4 sintético + indicadores públicos agregados · "
        "sem conexão, certificação ou homologação RNDS"
    )

    if not settings.database_path.is_file():
        st.info("Execute `rnds-lab demo` para criar o lakehouse local.")
        return

    overview, quality, profiles, access, laboratory, medication, public = st.tabs(
        [
            "Visão geral",
            "Qualidade",
            "Perfis sintéticos",
            "Regulação",
            "Laboratório",
            "Prescrições",
            "RNDS pública",
        ]
    )
    runs = _rows(
        settings,
        "SELECT * FROM mart_quality_by_run ORDER BY completed_at DESC NULLS LAST",
    )
    counts = _rows(
        settings,
        """SELECT
             (SELECT COUNT(*) FROM bronze_resources) AS bronze_resources,
             (SELECT COUNT(*) FROM dim_patient) AS synthetic_patients,
             (SELECT COUNT(*) FROM fact_encounter) AS encounters,
             (SELECT COUNT(*) FROM rnds_public_indicators) AS public_indicator_rows""",
    )[0]

    with overview:
        columns = st.columns(4)
        columns[0].metric("Recursos Bronze", f"{counts['bronze_resources']:,}")
        columns[1].metric("Pacientes sintéticos", f"{counts['synthetic_patients']:,}")
        columns[2].metric("Atendimentos", f"{counts['encounters']:,}")
        columns[3].metric("Linhas RNDS públicas", f"{counts['public_indicator_rows']:,}")
        st.markdown("#### Fluxo e limites")
        st.code(
            "FHIR sintético → contrato + semântica → Bronze imutável → Silver canônica "
            "→ Gold agregada → API/painel\n"
            "RNDS pública (UF) → download controlado → reconciliação UF/região/Brasil "
            "→ Gold agregada",
            language=None,
        )
        st.warning(
            "A RNDS assistencial restringe registros individuais. Este projeto usa somente "
            "dados sintéticos e os indicadores agregados publicados pelo Ministério da Saúde."
        )
        model_volume = _rows(
            settings,
            """SELECT * FROM mart_model_volume
               ORDER BY resources DESC, model, resource_type""",
        )
        if model_volume:
            st.markdown("#### Cobertura dos modelos demonstrativos")
            st.dataframe(model_volume, use_container_width=True, hide_index=True)

    with quality:
        if runs:
            latest = runs[0]
            qcols = st.columns(4)
            qcols[0].metric("Taxa de aceitação", f"{latest['acceptance_rate']:.1%}")
            qcols[1].metric("Aceitos", f"{latest['accepted_count']:,}")
            qcols[2].metric("Quarentena", f"{latest['quarantined_count']:,}")
            qcols[3].metric("Falhas detectadas", f"{latest['quality_issue_count']:,}")
            st.dataframe(runs, use_container_width=True, hide_index=True)
        issues = _rows(
            settings,
            """SELECT * FROM mart_quality_issues
               ORDER BY issue_count DESC, run_id DESC""",
        )
        if issues:
            issue_frame = _frame(issues)
            chart = px.bar(
                issue_frame,
                x="code",
                y="issue_count",
                color="resource_type",
                title="Falhas intencionais capturadas antes da camada analítica",
            )
            st.plotly_chart(chart, use_container_width=True)

    with profiles:
        demographic_rows = _rows(
            settings,
            """SELECT * FROM mart_demographic_profile
               ORDER BY uf_code, age_group, gender""",
        )
        if demographic_rows:
            demographic_frame = _frame(demographic_rows)
            demographic_chart = px.bar(
                demographic_frame,
                x="uf_code",
                y="synthetic_people",
                color="age_group",
                facet_row="gender",
                title="Distribuição da população inteiramente sintética",
            )
            st.plotly_chart(demographic_chart, use_container_width=True)
        condition_rows = _rows(
            settings,
            """SELECT condition_code, SUM(conditions) AS conditions
               FROM mart_condition_monthly GROUP BY condition_code
               ORDER BY conditions DESC""",
        )
        if condition_rows:
            condition_chart = px.bar(
                _frame(condition_rows),
                x="condition_code",
                y="conditions",
                title="Condições sintéticas por código CID-10",
            )
            st.plotly_chart(condition_chart, use_container_width=True)

    with access:
        rows = _rows(
            settings,
            """SELECT * FROM mart_access_monthly
               ORDER BY period, uf_code, priority""",
        )
        if rows:
            frame = _frame(rows)
            chart = px.line(
                frame,
                x="period",
                y="p90_wait_days",
                color="uf_code",
                markers=True,
                title="P90 sintético de espera regulatória por UF",
            )
            st.plotly_chart(chart, use_container_width=True)
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Sem eventos RIRA sintéticos materializados.")

    with laboratory:
        rows = _rows(
            settings,
            """SELECT * FROM mart_laboratory_monthly
               ORDER BY period, uf_code, lab_code""",
        )
        if rows:
            frame = _frame(rows)
            chart = px.box(
                frame,
                x="uf_code",
                y="p90_turnaround_hours",
                points="all",
                title="P90 sintético de liberação de exames por UF",
            )
            st.plotly_chart(chart, use_container_width=True)
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Sem eventos REL sintéticos materializados.")

    with medication:
        rows = _rows(
            settings,
            """SELECT * FROM mart_medication_monthly
               ORDER BY period, uf_code, medication_code""",
        )
        if rows:
            frame = _frame(rows)
            chart = px.bar(
                frame,
                x="medication_code",
                y="prescriptions",
                color="route_code",
                facet_col="priority",
                title="Prescrições RPM demonstrativas por código e via",
            )
            st.plotly_chart(chart, use_container_width=True)
            st.caption(
                "Medicamentos, vias, doses e quantidades são códigos inteiramente sintéticos; "
                "não representam conduta clínica nem recomendação terapêutica."
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Sem eventos RPM sintéticos materializados.")

    with public:
        rows = _rows(
            settings,
            """SELECT * FROM mart_rnds_public_indicators
               ORDER BY competence, indicator_code, uf_code""",
        )
        if not rows:
            st.info("Execute `rnds-lab refresh-public` para baixar os agregados oficiais.")
        else:
            frame = _frame(rows)
            indicators = sorted(frame["indicator_code"].unique().to_list())
            selected = st.selectbox("Indicador", indicators)
            filtered = frame.filter(pl.col("indicator_code") == selected)
            latest_competence = filtered["competence"].max()
            latest_public = filtered.filter(pl.col("competence") == latest_competence)
            chart = px.bar(
                latest_public.sort("value_uf", descending=True).head(15),
                x="uf_code",
                y="value_uf",
                hover_name="uf_name",
                title=f"15 maiores UFs · {selected} · competência {latest_competence!s}",
            )
            st.plotly_chart(chart, use_container_width=True)
            trend = _rows(
                settings,
                """SELECT * FROM mart_rnds_brazil_trend
                   WHERE indicator_code = ? ORDER BY competence""",
                [selected],
            )
            if len(trend) > 1:
                trend_chart = px.line(
                    _frame(trend),
                    x="competence",
                    y="value_brazil",
                    markers=True,
                    title="Série histórica disponível do total Brasil",
                )
                st.plotly_chart(trend_chart, use_container_width=True)
            st.caption(
                "Fonte: Portal de Dados Abertos do SUS. Valores agregados por UF; "
                "não representam acesso a registros individuais da RNDS."
            )
            st.dataframe(latest_public, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    render()
