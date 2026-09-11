"""Database engine-injection cases.

The webreport backend owns exactly one engine, builds it read only and hands it to the
operator's tool module, so Database must bind an engine it is given rather than building a
second one. The historical URL form still has to work, because the parser and the data
collector keep constructing their own writable Database.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine

# Runnable both as `poetry run python bd_shared/test_db_engine.py` and through the root
# Makefile, so the package parent is put on the path the same way the backend suite does it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bd_shared.db import Database  # noqa: E402


class DatabaseEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///bd-test-injected.db")
        self.addCleanup(self.engine.dispose)

    def test_an_injected_engine_is_bound_and_no_other_is_created(self):
        """Given an engine, When Database is built around it, Then create_engine is never called."""
        with patch("bd_shared.db.create_engine", side_effect=AssertionError("built a second engine")):
            database = Database(engine=self.engine)

        self.assertIs(database.engine, self.engine)
        self.assertIs(database.Session.kw["bind"], self.engine)

    def test_the_url_form_still_builds_one_engine(self):
        """Given a URL, When Database is built, Then it constructs its own engine as before."""
        database = Database("sqlite:///bd-test-url.db")
        self.addCleanup(database.engine.dispose)

        self.assertEqual(str(database.engine.url), "sqlite:///bd-test-url.db")

    def test_neither_form_opens_a_connection(self):
        """Given either form, When Database is built, Then no connection is checked out."""
        injected = Database(engine=self.engine)
        from_url = Database("sqlite:///bd-test-url.db")
        self.addCleanup(from_url.engine.dispose)

        self.assertEqual(injected.engine.pool.checkedout(), 0)
        self.assertEqual(from_url.engine.pool.checkedout(), 0)


if __name__ == "__main__":
    unittest.main()
