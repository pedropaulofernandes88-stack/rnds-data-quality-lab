"""Testes do painel com uma fachada Streamlit local, sem navegador ou servidor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rnds_data_lab import dashboard
from rnds_data_lab.config import Settings
from rnds_data_lab.pipeline import run_synthetic_pipeline


class _Context:
    def __enter__(self) -> _Context:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


class _Column:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, str]] = []

    def metric(self, label: str, value: str) -> None:
        self.metrics.append((label, value))


class _Streamlit:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.captions: list[str] = []
        self.charts: list[object] = []
        self.frames: list[object] = []
        self.columns_created: list[_Column] = []

    def set_page_config(self, **_: object) -> None:
        pass

    def title(self, _: str) -> None:
        pass

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def info(self, value: str) -> None:
        self.info_messages.append(value)

    def tabs(self, _: list[str]) -> list[_Context]:
        return [_Context() for _ in range(7)]

    def columns(self, count: int) -> list[_Column]:
        columns = [_Column() for _ in range(count)]
        self.columns_created.extend(columns)
        return columns

    def markdown(self, _: str) -> None:
        pass

    def code(self, _: str, *, language: None) -> None:
        pass

    def warning(self, _: str) -> None:
        pass

    def dataframe(self, value: object, **_: object) -> None:
        self.frames.append(value)

    def plotly_chart(self, chart: object, **_: object) -> None:
        self.charts.append(chart)

    def selectbox(self, _: str, options: list[str]) -> str:
        return options[0]


class _Express:
    def bar(self, *_: object, **kwargs: object) -> dict[str, object]:
        return {"chart": "bar", **kwargs}

    def line(self, *_: object, **kwargs: object) -> dict[str, object]:
        return {"chart": "line", **kwargs}

    def box(self, *_: object, **kwargs: object) -> dict[str, object]:
        return {"chart": "box", **kwargs}


def test_rows_frame_and_render_empty_lakehouse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings.load(tmp_path)
    fake_st = _Streamlit()
    monkeypatch.setattr(dashboard.Settings, "load", lambda: settings)
    monkeypatch.setattr(dashboard, "st", fake_st)

    assert dashboard._frame([]).is_empty()
    dashboard.render()

    assert fake_st.info_messages == ["Execute `rnds-lab demo` para criar o lakehouse local."]


def test_rows_reads_populated_duckdb_and_render_all_panels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings.load(tmp_path)
    run_synthetic_pipeline(settings, patients=8, seed=222, invalid_every=2)
    fake_st = _Streamlit()
    monkeypatch.setattr(dashboard.Settings, "load", lambda: settings)
    monkeypatch.setattr(dashboard, "st", fake_st)
    monkeypatch.setattr(dashboard, "px", _Express())

    public_rows = [
        {
            "indicator_code": "sdigi008",
            "competence": "202605",
            "uf_code": "35",
            "uf_name": "São Paulo",
            "value_uf": 5.0,
            "value_brazil": 5.0,
        },
        {
            "indicator_code": "sdigi008",
            "competence": "202606",
            "uf_code": "35",
            "uf_name": "São Paulo",
            "value_uf": 6.0,
            "value_brazil": 6.0,
        },
    ]

    real_rows = dashboard._rows

    def rows_with_public(
        effective_settings: Settings, sql: str, parameters: list[object] | None = None
    ) -> list[dict[str, Any]]:
        if "mart_rnds_public_indicators" in sql:
            return public_rows
        if "mart_rnds_brazil_trend" in sql:
            return [
                {"indicator_code": "sdigi008", "competence": "202605", "value_brazil": 5.0},
                {"indicator_code": "sdigi008", "competence": "202606", "value_brazil": 6.0},
            ]
        return real_rows(effective_settings, sql, parameters)

    monkeypatch.setattr(dashboard, "_rows", rows_with_public)
    dashboard.render()

    assert any(column.metrics for column in fake_st.columns_created)
    assert len(fake_st.charts) >= 5
    assert fake_st.frames
    assert any("Fonte: Portal" in caption for caption in fake_st.captions)
