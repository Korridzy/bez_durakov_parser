"""Read-only engine cases: per-dialect mechanism, the SQLite URL rewrite, and a real refusal.

Aggregated into test_agent, which is the public path the plan's acceptance commands use.
"""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from agent.engine import (
    READ_ONLY_CONNECT_ARGS,
    READ_ONLY_STATEMENTS,
    build_read_only_engine,
    read_only_url,
)

SCHEMA = "CREATE TABLE readings (reading_id INTEGER PRIMARY KEY, value INTEGER NOT NULL)"


class ReadOnlyMechanismTests(unittest.TestCase):
    """Which mechanism each dialect gets, asserted against the lookup tables themselves.

    Asserting through the dicts rather than through create_engine is deliberate: an unknown
    dialect makes create_engine import a DBAPI that does not exist, so it raises before any
    assertion about the absence of a wrapper could run.
    """

    def test_postgresql_uses_the_connection_parameter(self):
        """Given PostgreSQL, When the mechanism is selected, Then it is a connect argument."""
        self.assertEqual(
            READ_ONLY_CONNECT_ARGS["postgresql"],
            {"options": "-c default_transaction_read_only=on"},
        )
        self.assertNotIn("postgresql", READ_ONLY_STATEMENTS)

    def test_mysql_uses_the_connect_time_session_statement(self):
        """Given MySQL, When the mechanism is selected, Then it is a connect-time statement."""
        self.assertEqual(READ_ONLY_STATEMENTS["mysql"], "SET SESSION TRANSACTION READ ONLY")
        self.assertNotIn("mysql", READ_ONLY_CONNECT_ARGS)

    def test_mariadb_is_enforced_under_its_own_backend_name(self):
        """Given a mariadb URL, When the mechanism is selected, Then it is not silently skipped.

        SQLAlchemy gives `mariadb://` its own backend name, so it does not inherit the MySQL
        entry. Without its own key it would reach an operator's database unprotected.
        """
        self.assertEqual(make_url("mariadb+pymysql://u:p@h:3306/d").get_backend_name(), "mariadb")
        self.assertEqual(READ_ONLY_STATEMENTS["mariadb"], "SET SESSION TRANSACTION READ ONLY")

    def test_both_lookup_tables_key_off_the_same_name(self):
        """Given any enforced dialect, When it is looked up, Then one name drives both tables."""
        for url_string in (
            "mysql+pymysql://u:p@h:3306/d",
            "mariadb+pymysql://u:p@h:3306/d",
            "postgresql+psycopg://u:p@h:5432/d",
            "sqlite:///x.db",
        ):
            with self.subTest(url=url_string):
                backend_name = make_url(url_string).get_backend_name()
                # Every enforced dialect must be reachable by the URL's own backend name, so
                # a dialect can never be enforced by one table and missed by the other.
                self.assertTrue(
                    backend_name in READ_ONLY_STATEMENTS
                    or backend_name in READ_ONLY_CONNECT_ARGS
                    or backend_name == "sqlite",
                    f"{backend_name} is enforced by neither table",
                )

    def test_sqlite_uses_neither_table_because_the_url_carries_the_mode(self):
        """Given SQLite, When the mechanism is selected, Then neither table holds an entry."""
        self.assertNotIn("sqlite", READ_ONLY_CONNECT_ARGS)
        self.assertNotIn("sqlite", READ_ONLY_STATEMENTS)

    def test_an_unenforced_dialect_gets_no_wrapper_and_no_warning(self):
        """Given a dialect outside the enforced set, When it is looked up, Then nothing applies."""
        for dialect in ("oracle", "mssql", "firebird"):
            with self.subTest(dialect=dialect):
                self.assertNotIn(dialect, READ_ONLY_CONNECT_ARGS)
                self.assertNotIn(dialect, READ_ONLY_STATEMENTS)

    def test_an_unenforced_dialect_url_passes_through_without_a_log_record(self):
        """Given a non-SQLite URL, When it is rewritten, Then it is unchanged and silent."""
        for url_string in (
            "mysql+pymysql://durak:devpass@mysql:3306/bez_durakov",
            "postgresql+psycopg://u:p@pg:5432/warehouse",
            "oracle+cx_oracle://u:p@host:1521/xe",
        ):
            with self.subTest(url=url_string):
                url = make_url(url_string)
                with self.assertNoLogs():
                    self.assertEqual(read_only_url(url), url)


class ReadOnlyUrlTests(unittest.TestCase):
    """The SQLite URL rewrite, which is the only enforcement a module cannot lift."""

    def test_sqlite_urls_are_rewritten_to_the_read_only_file_uri_form(self):
        """Given a SQLite URL, When it is rewritten, Then it carries mode=ro and uri=true."""
        cases = {
            "sqlite:////data/library.db": "sqlite:///file:/data/library.db?mode=ro&uri=true",
            "sqlite:///library.db": "sqlite:///file:library.db?mode=ro&uri=true",
            "sqlite:///file:/x/y.db?uri=true": "sqlite:///file:/x/y.db?mode=ro&uri=true",
        }
        for configured, expected in cases.items():
            with self.subTest(configured=configured):
                self.assertEqual(str(read_only_url(make_url(configured))), expected)

    def test_a_database_less_sqlite_url_is_refused(self):
        """Given sqlite:// with no file, When it is rewritten, Then ValueError is raised."""
        with self.assertRaises(ValueError):
            read_only_url(make_url("sqlite://"))

    def test_an_in_memory_sqlite_url_is_rewritten_rather_than_refused_here(self):
        """Given :memory:, When it is rewritten, Then this function passes it through.

        The rejection that matters belongs to bd_shared.config._derive_database_name, which
        refuses both sqlite:// and sqlite:///:memory: at config import, so no production path
        reaches this function with either.
        """
        self.assertEqual(
            str(read_only_url(make_url("sqlite:///:memory:"))),
            "sqlite:///file::memory:?mode=ro&uri=true",
        )


class ReadOnlyEngineTests(unittest.TestCase):
    """A real SQLite engine, proving the refusal and that no connection opens at build time."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.database_path = Path(self._directory.name) / "fixture.db"

        seeding_engine = create_engine(f"sqlite:///{self.database_path}")
        with seeding_engine.begin() as connection:
            connection.execute(text(SCHEMA))
            connection.execute(text("INSERT INTO readings (reading_id, value) VALUES (1, 10)"))
        seeding_engine.dispose()

        self.engine = build_read_only_engine(f"sqlite:///{self.database_path}")
        self.addCleanup(self.engine.dispose)

    def test_building_the_engine_opens_no_connection(self):
        """Given a built engine, When nothing has run, Then the pool has handed out nothing."""
        engine = build_read_only_engine(f"sqlite:///{self.database_path}")
        self.addCleanup(engine.dispose)

        self.assertEqual(engine.pool.checkedout(), 0)

    def test_a_select_still_works(self):
        """Given the read-only engine, When a SELECT runs, Then the seeded row comes back."""
        with self.engine.connect() as connection:
            value = connection.execute(text("SELECT value FROM readings WHERE reading_id = 1")).scalar()

        self.assertEqual(value, 10)

    def test_an_insert_is_refused(self):
        """Given the read-only engine, When an INSERT runs, Then the driver refuses it."""
        with self.assertRaises(OperationalError) as caught:
            with self.engine.begin() as connection:
                connection.execute(text("INSERT INTO readings (reading_id, value) VALUES (2, 20)"))

        self.assertIn("readonly database", str(caught.exception))

    def test_pragma_query_only_off_does_not_lift_the_refusal(self):
        """Given a module trying to lift the mode, When it writes, Then it is still refused."""
        with self.assertRaises(OperationalError):
            with self.engine.begin() as connection:
                connection.execute(text("PRAGMA query_only = OFF"))
                connection.execute(text("INSERT INTO readings (reading_id, value) VALUES (3, 30)"))

    def test_the_refusal_survives_a_pool_round_trip(self):
        """Given a reset pooled connection, When a second write runs, Then it is still refused.

        This is the assertion that would have caught a mechanism reverting on check-in.
        """
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                with self.assertRaises(OperationalError):
                    with self.engine.begin() as connection:
                        connection.execute(
                            text("INSERT INTO readings (reading_id, value) VALUES (4, 40)")
                        )

        with self.engine.connect() as connection:
            count = connection.execute(text("SELECT COUNT(*) FROM readings")).scalar()
        self.assertEqual(count, 1)

    def test_a_missing_sqlite_file_refuses_to_open(self):
        """Given a missing file, When a connection opens, Then the read-only URI refuses it."""
        engine = build_read_only_engine(f"sqlite:///{self._directory.name}/absent.db")
        self.addCleanup(engine.dispose)

        with self.assertRaises(OperationalError):
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))


if __name__ == "__main__":
    unittest.main()
