from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import streamlit as st


def render_chat_pane(clear_conversation: Callable[[], None]) -> None:
    header, fullscreen = st.columns([12, 1])
    with header:
        st.subheader("💬 Разговор с AI-агентом")
    with fullscreen:
        suffix = " •" if st.session_state.report_ready_badge else ""
        if st.button(f"⛶{suffix}", key="fullscreen_chat", help="Развернуть чат"):
            st.session_state.fullscreen = None if st.session_state.fullscreen == "chat" else "chat"
            st.session_state.report_ready_badge = False
            st.rerun()

    if st.session_state.api_available:
        st.caption("API подключен")
    else:
        st.caption("API недоступен. Ошибки запросов появятся в истории чата.")

    with st.form(key="chat_form", clear_on_submit=True):
        user_input = st.text_area(
            "Ваше сообщение",
            height=60,
            placeholder="Опишите нужный отчёт...",
        )
        send, clear = st.columns(2)
        with send:
            submit = st.form_submit_button("Отправить", use_container_width=True)
        with clear:
            clear_requested = st.form_submit_button("🗑️ Очистить чат", use_container_width=True)

    if clear_requested:
        clear_conversation()
        st.rerun()
    if submit and user_input.strip():
        _queue_request(user_input.strip())
        st.rerun()

    selected_request_id = _selected_request_id()
    with st.container(height=520, key="chat-pane-scroll", border=False, autoscroll=True):
        if not st.session_state.chat_history:
            st.info("История диалога пуста. Начните с запроса к данным игр.")
        for message in st.session_state.chat_history:
            _render_message(message, selected_request_id)


def process_pending_request(send_message: Callable[[str], dict[str, object]]) -> None:
    pending = st.session_state.pending_request
    if pending is None:
        return

    response = send_message(pending["content"])
    st.session_state.pending_request = None
    st.session_state.is_generating = False
    assistant_message = {
        "id": str(uuid4()),
        "role": "assistant",
        "content": _response_text(response),
        "timestamp": datetime.now().isoformat(),
        "request_id": pending["id"],
    }
    reasoning = response.get("reasoning")
    if isinstance(reasoning, str) and reasoning:
        assistant_message["reasoning"] = reasoning
        assistant_message["reasoning_partial"] = response.get("success") is not True
    if response.get("success") is True:
        report_id = str(uuid4())
        assistant_message["report"] = {
            "id": report_id,
            "request_id": pending["id"],
            "request_text": pending["content"],
            "title": _response_text(response),
            "data": response.get("data"),
        }
        st.session_state.active_report_id = report_id
        if st.session_state.fullscreen == "chat":
            st.session_state.report_ready_badge = True
        elif not st.session_state.user_has_dragged:
            st.session_state.split_pct = 50.0
    else:
        assistant_message["error"] = _response_text(response, "Не удалось создать отчёт")
    st.session_state.chat_history.append(assistant_message)
    st.rerun()


def reasoning_view(message: dict[str, object]) -> tuple[str, str] | None:
    reasoning = message.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return None
    label = "Рассуждения (неполные)" if message.get("reasoning_partial") else "Рассуждения"
    return label, reasoning


def _queue_request(content: str) -> None:
    request = {
        "id": str(uuid4()),
        "role": "user",
        "content": content,
        "timestamp": datetime.now().isoformat(),
    }
    st.session_state.chat_history.append(request)
    st.session_state.pending_request = request
    st.session_state.is_generating = True


def _render_message(message: dict[str, object], selected_request_id: str | None) -> None:
    role = message.get("role")
    message_id = message.get("id")
    is_active_request = role == "user" and message_id == selected_request_id
    container = (
        st.container(key=f"active-request-{message_id}", border=False)
        if is_active_request and isinstance(message_id, str)
        else st.container()
    )
    with container:
        with st.chat_message("user" if role == "user" else "assistant"):
            reasoning = reasoning_view(message)
            if reasoning is not None:
                label, text = reasoning
                with st.expander(label, expanded=False):
                    st.markdown(text)
            content = message.get("content")
            st.markdown(content if isinstance(content, str) else "")
            if is_active_request:
                st.caption("Этот запрос открыт в области отчёта.")
            report = message.get("report")
            if role == "assistant" and isinstance(report, dict):
                report_id = report.get("id")
                if isinstance(report_id, str):
                    label = "Отчёт открыт" if report_id == st.session_state.active_report_id else "Открыть этот отчёт"
                    if st.button(label, key=f"open_report_{report_id}", use_container_width=True):
                        st.session_state.active_report_id = report_id
                        st.session_state.report_ready_badge = False
                        st.rerun()
            error = message.get("error")
            if isinstance(error, str):
                st.error(error)


def _selected_request_id() -> str | None:
    for message in st.session_state.chat_history:
        report = message.get("report")
        if not isinstance(report, dict) or report.get("id") != st.session_state.active_report_id:
            continue
        request_id = report.get("request_id")
        return request_id if isinstance(request_id, str) else None
    return None


def _response_text(response: dict[str, object], fallback: str = "Отчёт готов") -> str:
    value = response.get("message")
    if isinstance(value, str) and value:
        return value
    value = response.get("error")
    if isinstance(value, str) and value:
        return value
    return fallback
