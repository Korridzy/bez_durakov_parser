from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd
import streamlit as st


def render_report_pane(refresh: Callable[[], None]) -> None:
    header, refresh_action, fullscreen = st.columns([8, 1, 1])
    with header:
        st.subheader("📊 Отчёт")
    with refresh_action:
        if st.button("⟳", key="refresh_report", help="Обновить страницу"):
            refresh()
    with fullscreen:
        if st.button("⛶", key="fullscreen_report", help="Развернуть отчёт"):
            st.session_state.fullscreen = None if st.session_state.fullscreen == "report" else "report"
            st.rerun()

    with st.container(height=520, key="report-pane-scroll", border=False):
        report = _active_report()
        if report is None:
            st.info("Отчёт появится здесь сразу после ответа агента.")
            st.markdown("""
            Примеры запросов:
            - все игры;
            - топ 10 команд по очкам;
            - статистика команды.
            """)
            return
        st.caption(f"Запрос: {report['request_text']}")
        st.markdown(f"### {report['title']}")
        if st.session_state.is_generating:
            st.markdown(
                """
                <div class="report-loading-overlay">
                    <div class="report-loading-spinner"></div>
                    <strong>Генерируем новый отчёт</strong>
                </div>
                """,
                unsafe_allow_html=True,
            )
        _render_data(report["data"])


def _active_report() -> dict[str, object] | None:
    for message in st.session_state.chat_history:
        report = message.get("report")
        if isinstance(report, dict) and report.get("id") == st.session_state.active_report_id:
            return report
    return None


def _render_data(data: object) -> None:
    if isinstance(data, list) and data:
        dataframe = pd.DataFrame(data)
        st.markdown("#### Основные показатели")
        total, points, dates = st.columns(3)
        with total:
            st.metric("Всего записей", len(dataframe))
        with points:
            if "total_points" in dataframe.columns:
                st.metric("Средние очки", f"{dataframe['total_points'].mean():.2f}")
        with dates:
            st.metric("Колонок", len(dataframe.columns))
        st.dataframe(dataframe, use_container_width=True, height=320)
        st.download_button(
            "Скачать CSV",
            data=dataframe.to_csv(index=False).encode("utf-8"),
            file_name=f"report_{datetime.now():%Y%m%d_%H%M%S}.csv",
            mime="text/csv",
        )
        index_column = dataframe.columns[0]
        numeric_columns = [
            column
            for column in dataframe.select_dtypes(include=["float64", "int64"]).columns.tolist()
            if column != index_column
        ]
        if numeric_columns:
            chart_column = st.selectbox("Колонка для графика", numeric_columns)
            st.bar_chart(dataframe.set_index(index_column)[chart_column])
        return
    if isinstance(data, dict):
        st.json(data)
        return
    st.write(data)
