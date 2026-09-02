"""Offline e2e coverage of the «Рассуждения» expander.

Drives the real Streamlit frontend in Chromium against the stdlib stub backend.
Selectors were pinned from a captured render (Streamlit 1.59): the expander is a
native ``<details>``/``<summary>`` pair under ``[data-testid="stExpander"]``, and
the summary label lives in its own ``stMarkdownContainer`` (the sibling
``stIconMaterial`` span contributes the ``keyboard_arrow_right`` ligature text,
so never assert on ``summary.inner_text()``).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect

PLACEHOLDER = "Опишите нужный отчёт..."
EXPANDER = '[data-testid="stExpander"]'
EXPANDER_LABEL = '[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"]'
EXPANDER_BODY = '[data-testid="stExpanderDetails"]'
CHAT_MESSAGE = '[data-testid="stChatMessage"]'
ASSISTANT_AVATAR = '[data-testid="stChatMessageAvatarAssistant"]'

EXPANDER_PRECEDES_ANSWER = """
node => {
    const expander = node.querySelector('[data-testid="stExpander"]');
    const answer = Array.from(node.querySelectorAll('[data-testid="stMarkdown"]'))
        .find(element => !expander.contains(element));
    return {
        answer: answer.innerText.trim(),
        precedes: Boolean(
            expander.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING
        ),
    };
}
"""


def _ask(page, message: str):
    """Submit a chat request and return the assistant bubble that answers it."""
    page.get_by_placeholder(PLACEHOLDER).fill(message)
    page.get_by_role("button", name="Отправить").click()
    assistant = page.locator(CHAT_MESSAGE).filter(has=page.locator(ASSISTANT_AVATAR))
    expect(assistant).to_have_count(1, timeout=60_000)
    return assistant.first


def test_reasoning_expander_is_collapsed_and_above_the_answer(app_page, payloads) -> None:
    """Given: a model turn that emits reasoning. Then: a collapsed «Рассуждения» block."""
    bubble = _ask(app_page, "обычный отчёт")

    expect(bubble.locator(EXPANDER_LABEL)).to_have_text("Рассуждения")
    expect(bubble.get_by_text(payloads.answer_with_reasoning)).to_be_visible()
    expect(bubble.locator(EXPANDER_BODY)).to_be_hidden()
    assert bubble.locator(f"{EXPANDER} details").evaluate("node => node.open") is False

    placement = bubble.evaluate(EXPANDER_PRECEDES_ANSWER)
    assert placement["precedes"], "the reasoning expander must precede the answer markdown"
    assert placement["answer"] == payloads.answer_with_reasoning


def test_clicking_the_expander_reveals_the_whole_reasoning(app_page, payloads) -> None:
    """Given: a collapsed reasoning block. When: clicked. Then: every segment shows."""
    bubble = _ask(app_page, "обычный отчёт")

    bubble.locator(f"{EXPANDER} summary").click()

    body = bubble.locator(EXPANDER_BODY)
    expect(body).to_be_visible()
    for segment in payloads.reasoning_full.split("\n\n"):
        expect(body.get_by_text(segment)).to_be_visible()


def test_no_expander_when_the_response_carries_no_reasoning(app_page, payloads) -> None:
    """Given: a success response with reasoning null. Then: no expander anywhere."""
    bubble = _ask(app_page, "без рассуждений")

    expect(bubble.get_by_text(payloads.answer_without_reasoning)).to_be_visible()
    expect(app_page.locator(EXPANDER)).to_have_count(0)


def test_failed_request_shows_partial_label_and_the_error(app_page, payloads) -> None:
    """Given: a failed request with partial reasoning. Then: «(неполные)» + error box."""
    bubble = _ask(app_page, "сбой отчёта")

    expect(bubble.locator(EXPANDER_LABEL)).to_have_text("Рассуждения (неполные)")
    expect(bubble.get_by_role("alert").filter(has_text=payloads.failure_message)).to_be_visible()
    expect(bubble.locator(EXPANDER_BODY)).to_be_hidden()

    bubble.locator(f"{EXPANDER} summary").click()
    expect(bubble.locator(EXPANDER_BODY).get_by_text(payloads.reasoning_partial)).to_be_visible()


def test_browser_traffic_is_loopback_only(app_page, blocked_requests: list[str]) -> None:
    """The route guard must abort browser requests that would leave loopback."""
    with pytest.raises(PlaywrightError):
        app_page.goto("http://example.com/", timeout=15_000)

    assert "http://example.com/" in blocked_requests


def test_streamlit_child_is_loopback_only(app_page, streamlit_app, stub_backend) -> None:
    """The child process itself is guarded, and telemetry is off in its live env."""
    _ask(app_page, "обычный отчёт")

    marker = streamlit_app.guard_marker.read_text(encoding="utf-8")
    assert "203.0.113.7" in marker, marker
    assert "NOT BLOCKED" not in marker, marker
    assert "blocked" in marker, marker

    environ = streamlit_app.child_environ()
    assert environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] == "false"
    assert environ["PYTHONPATH"].split(":")[0] == str(streamlit_app.guard_dir)
    assert environ["API_BASE_URL"].startswith("http://127.0.0.1:")

    assert ("POST", "/api/chat") in stub_backend.received
