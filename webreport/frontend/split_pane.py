"""Browser-side controls for the Streamlit split-pane layout."""

from __future__ import annotations

from typing import Final, TypeGuard

import streamlit as st
from streamlit.components.v2 import component


CONTROLLER_KEY: Final = "split_pane_controller"
_MINIMUM_PANE_WIDTH: Final = 20.0

_SPLIT_PANE_CONTROLLER = component(
    "split_pane_controller",
    html="<div aria-hidden=\"true\"></div>",
    js="""
export default function({ parentElement, data, setTriggerValue }) {
  const documentRoot = parentElement.ownerDocument;
  const stateKey = "__gameReportSplitPane";
  const state = documentRoot[stateKey] ?? {};
  documentRoot[stateKey] = state;
  state.data = data;
  state.emit = setTriggerValue;

  const setStyle = (element, property, value) => {
    if (!element) return;
    if (value === null) {
      element.style.removeProperty(property);
      return;
    }
    element.style.setProperty(property, value, "important");
  };

  const anchors = () => ({
    chat: documentRoot.getElementById("chat-pane-anchor"),
    report: documentRoot.getElementById("report-pane-anchor"),
  });

  const layout = () => {
    const { chat, report } = anchors();
    if (!chat || !report) return null;
    const chatColumn = chat.closest('[data-testid="stColumn"]');
    const reportColumn = report.closest('[data-testid="stColumn"]');
    if (!chatColumn || !reportColumn) return null;
    return { chatColumn, reportColumn, row: chatColumn.parentElement };
  };

  const ensureDivider = (row, reportColumn) => {
    let divider = row.querySelector(".split-pane-divider");
    if (divider) return divider;
    divider = documentRoot.createElement("div");
    divider.className = "split-pane-divider";
    divider.setAttribute("aria-label", "Изменить ширину панелей");
    divider.setAttribute("role", "separator");
    divider.tabIndex = 0;
    divider.innerHTML = "<span></span><span></span><span></span>";
    reportColumn.before(divider);
    return divider;
  };

  const clamp = (value) => Math.min(100 - %MINIMUM_PANE_WIDTH%, Math.max(%MINIMUM_PANE_WIDTH%, value));
  const isStacked = () => window.matchMedia("(max-width: 768px)").matches;

  const applySplit = (position) => {
    const current = layout();
    if (!current || !current.row) return;
    const { chatColumn, reportColumn, row } = current;
    const divider = ensureDivider(row, reportColumn);
    const stacked = isStacked();
    const fullscreen = state.data.fullscreen;
    const chatPane = documentRoot.querySelector(".st-key-chat-pane-scroll");
    const reportPane = documentRoot.querySelector(".st-key-report-pane-scroll");
    const loadingOverlay = documentRoot.querySelector(".report-loading-overlay");
    const viewportHeight = Math.max(320, window.innerHeight - 118);
    const paneHeight = stacked ? Math.max(230, Math.floor(viewportHeight / 2) - 8) : viewportHeight;
    const chatPaneHeight = Math.max(96, paneHeight - 240);
    const reportPaneHeight = Math.max(160, paneHeight - 112);

    row.style.display = "flex";
    row.style.height = `${viewportHeight}px`;
    row.style.maxHeight = `${viewportHeight}px`;
    row.style.overflow = "hidden";
    row.style.flexDirection = stacked ? "column-reverse" : "row";
    row.style.alignItems = "stretch";
    row.style.flexWrap = "nowrap";
    row.style.gap = "0";
    setStyle(chatPane, "height", `${chatPaneHeight}px`);
    setStyle(reportPane, "height", `${reportPaneHeight}px`);
    setStyle(chatPane, "max-height", `${chatPaneHeight}px`);
    setStyle(reportPane, "max-height", `${reportPaneHeight}px`);

    if (stacked) {
      divider.style.display = "none";
      setStyle(chatColumn, "flex", "0 0 auto");
      setStyle(reportColumn, "flex", "0 0 auto");
      setStyle(chatColumn, "height", `${paneHeight}px`);
      setStyle(reportColumn, "height", `${paneHeight}px`);
      setStyle(chatColumn, "max-height", `${paneHeight}px`);
      setStyle(reportColumn, "max-height", `${paneHeight}px`);
      setStyle(chatColumn, "overflow", "hidden");
      setStyle(reportColumn, "overflow", "hidden");
      setStyle(chatColumn, "width", "100%");
      setStyle(reportColumn, "width", "100%");
    } else {
      divider.style.display = "flex";
      setStyle(chatColumn, "height", null);
      setStyle(reportColumn, "height", null);
      setStyle(chatColumn, "max-height", null);
      setStyle(reportColumn, "max-height", null);
      setStyle(chatColumn, "overflow", null);
      setStyle(reportColumn, "overflow", null);
      setStyle(chatColumn, "flex", `0 0 ${position}%`);
      setStyle(reportColumn, "flex", `1 1 ${100 - position}%`);
      setStyle(chatColumn, "width", `${position}%`);
      setStyle(reportColumn, "width", `${100 - position}%`);
    }

    const header = documentRoot.querySelector('[data-testid="stHeader"]');
    if (fullscreen === "chat" || fullscreen === "report") {
      const visibleColumn = fullscreen === "chat" ? chatColumn : reportColumn;
      const hiddenColumn = fullscreen === "chat" ? reportColumn : chatColumn;
      hiddenColumn.style.display = "none";
      setStyle(visibleColumn, "display", "block");
      setStyle(visibleColumn, "flex", "1 1 100%");
      setStyle(visibleColumn, "width", "100%");
      row.style.position = "fixed";
      row.style.inset = "0";
      row.style.zIndex = "1000000";
      row.style.height = "100dvh";
      row.style.maxHeight = "100dvh";
      if (header) header.style.display = "none";
      const fullscreenPane = fullscreen === "chat" ? chatPane : reportPane;
      setStyle(fullscreenPane, "height", "100dvh");
      setStyle(fullscreenPane, "max-height", "100dvh");
    } else {
      chatColumn.style.removeProperty("display");
      reportColumn.style.removeProperty("display");
      row.style.removeProperty("position");
      row.style.removeProperty("inset");
      row.style.removeProperty("z-index");
      if (header) header.style.removeProperty("display");
    }

    if (loadingOverlay && reportPane) {
      const bounds = reportPane.getBoundingClientRect();
      loadingOverlay.style.position = "fixed";
      loadingOverlay.style.left = `${bounds.left}px`;
      loadingOverlay.style.top = `${bounds.top}px`;
      loadingOverlay.style.width = `${bounds.width}px`;
      loadingOverlay.style.height = `${bounds.height}px`;
    }
  };

  const current = layout();
  if (current && current.row) {
    const divider = ensureDivider(current.row, current.reportColumn);
    if (!divider.dataset.splitPaneBound) {
      divider.dataset.splitPaneBound = "true";
      divider.addEventListener("pointerdown", (event) => {
        if (isStacked()) return;
        event.preventDefault();
        divider.setPointerCapture(event.pointerId);
        const move = (moveEvent) => {
          const activeLayout = layout();
          if (!activeLayout || !activeLayout.row) return;
          const bounds = activeLayout.row.getBoundingClientRect();
          const next = clamp(((moveEvent.clientX - bounds.left) / bounds.width) * 100);
          state.preview = next;
          applySplit(next);
        };
        const release = (releaseEvent) => {
          move(releaseEvent);
          divider.releasePointerCapture(releaseEvent.pointerId);
          divider.removeEventListener("pointermove", move);
          divider.removeEventListener("pointerup", release);
          state.emit("divider_released", {
            position_pct: state.preview ?? state.data.split_pct,
            released_at: Date.now(),
          });
        };
        divider.addEventListener("pointermove", move);
        divider.addEventListener("pointerup", release, { once: true });
      });
    }
  }

  if (!state.escapeListener) {
    state.escapeListener = (event) => {
      if (event.key === "Escape" && state.data.fullscreen) {
        state.emit("escape", { released_at: Date.now() });
      }
    };
    documentRoot.addEventListener("keydown", state.escapeListener);
    window.addEventListener("resize", () => applySplit(state.data.split_pct));
  }

  documentRoot.documentElement.style.overflow = "hidden";
  documentRoot.body.style.overflow = "hidden";
  requestAnimationFrame(() => applySplit(state.data.split_pct));
}
""".replace("%MINIMUM_PANE_WIDTH%", str(_MINIMUM_PANE_WIDTH)),
    css="""
.split-pane-divider {
  align-items: center;
  background: rgba(30, 136, 229, 0.14);
  border-left: 1px solid rgba(30, 136, 229, 0.5);
  border-right: 1px solid rgba(30, 136, 229, 0.5);
  cursor: ew-resize;
  display: flex;
  flex: 0 0 22px;
  flex-direction: column;
  gap: 4px;
  justify-content: center;
  min-width: 22px;
  overflow: hidden;
  resize: horizontal;
  transition: background-color 120ms ease;
}
.split-pane-divider:hover,
.split-pane-divider:focus-visible {
  background: rgba(30, 136, 229, 0.28);
  outline: none;
}
.split-pane-divider span {
  background: #1E88E5;
  border-radius: 999px;
  height: 5px;
  opacity: 0.9;
  width: 5px;
}
""",
    isolate_styles=False,
)


def _controller_value(event_name: str) -> object:
    controller_state = st.session_state.get(CONTROLLER_KEY)
    return getattr(controller_state, event_name, None)


def _is_object_map(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _save_split_position() -> None:
    event = _controller_value("divider_released")
    if not _is_object_map(event):
        return
    position = event.get("position_pct")
    if isinstance(position, bool) or not isinstance(position, (int, float)):
        return
    st.session_state.split_pct = min(80.0, max(_MINIMUM_PANE_WIDTH, float(position)))
    st.session_state.user_has_dragged = True


def _exit_fullscreen() -> None:
    if _controller_value("escape") is not None:
        st.session_state.fullscreen = None


def render_split_pane_controller(
    split_pct: float,
    fullscreen: str | None,
    is_generating: bool,
) -> None:
    """Synchronize the browser-side divider and fullscreen keyboard shortcut."""
    _ = _SPLIT_PANE_CONTROLLER(
        key=CONTROLLER_KEY,
        data={
            "split_pct": split_pct,
            "fullscreen": fullscreen,
            "is_generating": is_generating,
        },
        height=0,
        on_divider_released_change=_save_split_position,
        on_escape_change=_exit_fullscreen,
    )
