"""A dialect-neutral stand-in for an operator's tool module.

This is a fixture asset shaped exactly like an operator module, not a test module, so the
acceptance configs can name it as `tools_module = "acceptance_fixture"`. It resolves because
Compose mounts ./backend at /app, which is the working directory.

The schema deliberately uses only types every one of the three supported dialects renders
identically, so the same file proves the dialect promise on SQLite and on PostgreSQL.
"""

from typing import Any

import pandas as pd
from sqlalchemy import Engine, text

SCHEMA = """
CREATE TABLE station_readings (
    reading_id    INTEGER PRIMARY KEY,
    station       VARCHAR(64) NOT NULL,
    reading_day   VARCHAR(10) NOT NULL,
    reading_value INTEGER NOT NULL
)
"""

ROWS = (
    (1, "north", "2025-01-01", 10),
    (2, "north", "2025-01-02", 20),
    (3, "north", "2025-01-03", 30),
    (4, "south", "2025-01-01", 5),
    (5, "south", "2025-01-02", 7),
)


class StationService:
    """Reads over the station_readings table."""

    def __init__(self, engine: Engine):
        """Bind the injected engine. No connection is opened here."""
        self._engine = engine

    def list_stations(self) -> pd.DataFrame:
        """List every station with its reading count."""
        return pd.read_sql(
            text(
                "SELECT station, COUNT(*) AS reading_count "
                "FROM station_readings GROUP BY station ORDER BY station"
            ),
            self._engine,
        )

    def station_total(self, station: str) -> dict[str, Any]:
        """Return the total reading value for one station."""
        with self._engine.connect() as connection:
            total = connection.execute(
                text(
                    "SELECT SUM(reading_value) FROM station_readings WHERE station = :station"
                ),
                {"station": station},
            ).scalar()
        return {"station": station, "total": int(total or 0)}

    def insert_reading(self, station: str, value: int) -> dict[str, Any]:
        """Attempt to insert a reading, which exists to prove that writes are refused."""
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO station_readings "
                    "(reading_id, station, reading_day, reading_value) "
                    "VALUES (:reading_id, :station, :reading_day, :reading_value)"
                ),
                {
                    "reading_id": 999,
                    "station": station,
                    "reading_day": "2025-12-31",
                    "reading_value": value,
                },
            )
        return {"station": station, "inserted": value}


def build_service(engine: Engine) -> StationService:
    """Build the fixture service around the injected engine, opening no connection."""
    return StationService(engine)


def create_schema(engine: Engine) -> None:
    """Create the fixture table. Used by the acceptance lane's writable seeding engine only."""
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS station_readings"))
        connection.execute(text(SCHEMA))


def seed(engine: Engine) -> None:
    """Insert the fixture rows. Used by the acceptance lane's writable seeding engine only."""
    with engine.begin() as connection:
        for reading_id, station, reading_day, reading_value in ROWS:
            connection.execute(
                text(
                    "INSERT INTO station_readings "
                    "(reading_id, station, reading_day, reading_value) "
                    "VALUES (:reading_id, :station, :reading_day, :reading_value)"
                ),
                {
                    "reading_id": reading_id,
                    "station": station,
                    "reading_day": reading_day,
                    "reading_value": reading_value,
                },
            )
