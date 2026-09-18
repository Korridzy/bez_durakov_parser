from __future__ import annotations

import unittest
from collections.abc import Sequence
from unittest.mock import patch

import report_pane


class _Container:
    def __enter__(self) -> _Container:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> bool:
        return False


class _Streamlit:
    def __init__(self) -> None:
        self.bar_chart_calls: int = 0
        self.session_state: object = type(
            "SessionState",
            (),
            {
                "active_report_id": "report",
                "chat_history": [
                    {
                        "report": {
                            "id": "report",
                            "request_text": "пустой отчёт",
                            "title": "Пустой отчёт",
                            "data": [{}],
                        }
                    }
                ],
                "fullscreen": None,
                "is_generating": False,
            },
        )()

    def subheader(self, _body: str) -> None:
        return None

    def markdown(self, _body: str) -> None:
        return None

    def columns(self, spec: int | Sequence[float]) -> tuple[_Container, ...]:
        # The fake's arity follows the production call, so a change to the metric row
        # surfaces here as an unpack error rather than passing silently. Streamlit accepts
        # either a count or a list of relative widths, and the pane uses both.
        count = spec if isinstance(spec, int) else len(spec)
        return tuple(_Container() for _ in range(count))

    def button(self, _label: str, **_kwargs: object) -> bool:
        return False

    def rerun(self) -> None:
        return None

    def container(self, **_kwargs: object) -> _Container:
        return _Container()

    def info(self, _body: str) -> None:
        return None

    def caption(self, _body: str) -> None:
        return None

    def metric(self, _label: str, _value: object) -> None:
        return None

    def dataframe(self, _data: object, **_kwargs: object) -> None:
        return None

    def download_button(self, _label: str, **_kwargs: object) -> None:
        return None

    def bar_chart(self, _data: object) -> None:
        self.bar_chart_calls += 1


class RenderDataTest(unittest.TestCase):
    def test_skips_chart_when_records_have_no_columns(self) -> None:
        streamlit = _Streamlit()

        with patch.object(report_pane, "st", streamlit):
            report_pane.render_report_pane(lambda: None)

        self.assertEqual(0, streamlit.bar_chart_calls)


if __name__ == "__main__":
    _ = unittest.main()
