import os
import time
import uuid
from collections.abc import Callable
from typing import cast

import requests
import streamlit as st

from bd_shared.logging_setup import configure_logging, get_logger
from chat_pane import process_pending_request, render_chat_pane
from report_pane import render_report_pane
from split_pane import render_split_pane_controller


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
CHAT_REQUEST_TIMEOUT_SECONDS = int(os.environ["CHAT_REQUEST_TIMEOUT_SECONDS"])

configure_logging("webreport-frontend")
logger = get_logger(__name__)

st.set_page_config(
    page_title="Отчёты по данным",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            overflow: hidden;
        }
        [data-testid="stMainBlockContainer"] {
            max-width: none;
            padding-bottom: 0;
        }
        .st-key-chat-pane-scroll, .st-key-report-pane-scroll {
            overflow: auto;
        }
        .st-key-report-pane-scroll {
            position: relative;
        }
        [class*="st-key-active-request"] {
            background: color-mix(in srgb, #1E88E5 14%, transparent);
            border-left: 0.25rem solid #1E88E5;
            border-radius: 0.5rem;
            padding: 0.25rem 0.5rem;
        }
        .report-loading-overlay {
            align-items: center;
            background: rgba(255, 255, 255, 0.7);
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            inset: 0;
            justify-content: center;
            position: absolute;
            z-index: 10;
        }
        .report-loading-spinner {
            animation: report-spin 0.8s linear infinite;
            border: 0.25rem solid rgba(30, 136, 229, 0.2);
            border-radius: 50%;
            border-top-color: #1E88E5;
            height: 2rem;
            width: 2rem;
        }
        @keyframes report-spin {
            to { transform: rotate(360deg); }
        }
        @media (max-width: 768px) {
            [data-testid="stMainBlockContainer"] {
                padding-left: 0.75rem;
                padding-right: 0.75rem;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    defaults = {
        "session_id": str(uuid.uuid4()),
        "chat_history": [],
        "active_report_id": None,
        "split_pct": 65.0,
        "user_has_dragged": False,
        "fullscreen": None,
        "report_ready_badge": False,
        "pending_request": None,
        "is_generating": False,
        "api_available": False,
    }
    for name, value in defaults.items():
        if name not in st.session_state:
            st.session_state[name] = value


def _backend_call(
    call: Callable[..., requests.Response],
    method: str,
    path: str,
    **kwargs: object,
) -> requests.Response:
    request_id = uuid.uuid4().hex
    headers = dict(cast(dict[str, str], kwargs.pop("headers", {})))
    headers["X-Request-ID"] = request_id
    kwargs["headers"] = headers
    session_id = (
        st.session_state.get("session_id")
        if hasattr(st.session_state, "get")
        else getattr(st.session_state, "session_id", None)
    )
    started_at = time.perf_counter()
    try:
        response = call(f"{API_BASE_URL}{path}", **kwargs)
    except requests.RequestException:
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "backend_request_failed",
            method=method,
            path=path,
            duration_ms=duration_ms,
            request_id=request_id,
            session_id=session_id,
            exc_info=True,
        )
        raise
    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "backend_request",
        method=method,
        path=path,
        status=response.status_code,
        duration_ms=duration_ms,
        request_id=request_id,
        session_id=session_id,
    )
    return response


def check_api_health() -> bool:
    try:
        response = _backend_call(requests.get, "GET", "/health", timeout=2)
    except requests.RequestException:
        return False
    return response.status_code == 200


def send_chat_message(message: str) -> dict[str, object]:
    try:
        response = _backend_call(
            requests.post,
            "POST",
            "/api/chat",
            json={"message": message, "session_id": st.session_state.session_id},
            timeout=CHAT_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.HTTPError as error:
        try:
            error_payload: object = error.response.json() if error.response is not None else None
        except requests.exceptions.JSONDecodeError:
            error_payload = None
        detail: str | None = None
        if isinstance(error_payload, dict):
            raw_detail = error_payload.get("detail")
            if isinstance(raw_detail, str):
                detail = raw_detail
        message = detail or str(error)
        return {
            "success": False,
            "error": message,
            "message": message,
        }
    except requests.RequestException as error:
        return {
            "success": False,
            "error": str(error),
            "message": "Не удалось связаться с сервером.",
        }
    try:
        payload: object = response.json()
    except requests.exceptions.JSONDecodeError:
        return {
            "success": False,
            "error": "Сервер вернул некорректный ответ.",
            "message": "Сервер вернул некорректный ответ.",
        }
    if isinstance(payload, dict):
        return payload
    return {
        "success": False,
        "error": "Сервер вернул некорректный ответ.",
        "message": "Сервер вернул некорректный ответ.",
    }


def clear_conversation() -> None:
    try:
        response = _backend_call(
            requests.post,
            "POST",
            f"/api/clear/{st.session_state.session_id}",
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        st.warning(f"Не удалось очистить историю на сервере: {error}")
    st.session_state.chat_history = []
    st.session_state.active_report_id = None
    st.session_state.pending_request = None
    st.session_state.is_generating = False
    st.session_state.report_ready_badge = False
    st.session_state.split_pct = 65.0
    st.session_state.user_has_dragged = False


def rerun_page() -> None:
    st.rerun()


def main() -> None:
    init_session_state()
    st.session_state.api_available = check_api_health()

    split = st.session_state.split_pct
    chat_weight = split if isinstance(split, (float, int)) else 65.0
    report_weight = 100.0 - chat_weight
    chat_column, report_column = st.columns([chat_weight, report_weight], gap="small")

    with chat_column:
        st.markdown('<span id="chat-pane-anchor"></span>', unsafe_allow_html=True)
        render_chat_pane(clear_conversation)
    with report_column:
        st.markdown('<span id="report-pane-anchor"></span>', unsafe_allow_html=True)
        render_report_pane(rerun_page)

    render_split_pane_controller(
        chat_weight,
        st.session_state.fullscreen,
        st.session_state.is_generating,
    )
    process_pending_request(send_chat_message)


if __name__ == "__main__":
    main()
