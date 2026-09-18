"""The frontend's production files carry no dataset vocabulary.

The backend learns its tool surface from an operator's module, so the interface around it
must not name one particular dataset. This reads the four production files as text, which
is what makes the assertion independent of Streamlit being importable.
"""

import unittest
from pathlib import Path

PRODUCTION_FILES = ("main.py", "chat_pane.py", "report_pane.py", "split_pane.py")

FORBIDDEN_STRINGS = (
    "Game Data Reports",
    "🎮",
    "все игры",
    "топ 10 команд по очкам",
    "статистика команды",
    "total_points",
    "Средние очки",
    "данным игр",
)


class FrontendNeutralityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent

    def test_production_files_carry_no_dataset_vocabulary(self):
        """Given the production files, When they are read, Then no forbidden string appears."""
        for name in PRODUCTION_FILES:
            text = (self.root / name).read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_STRINGS:
                with self.subTest(file=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_the_neutral_title_and_icon_are_in_place(self):
        """Given main.py, When it is read, Then the neutral page identity is present."""
        text = (self.root / "main.py").read_text(encoding="utf-8")

        self.assertIn('page_title="Отчёты по данным"', text)
        self.assertIn('page_icon="📊"', text)

    def test_the_empty_state_offers_neutral_examples(self):
        """Given report_pane.py, When it is read, Then the examples name no dataset."""
        text = (self.root / "report_pane.py").read_text(encoding="utf-8")

        for example in (
            "сводка по всем записям",
            "десять наибольших значений",
            "подробности по одному объекту",
        ):
            with self.subTest(example=example):
                self.assertIn(example, text)


if __name__ == "__main__":
    unittest.main()
