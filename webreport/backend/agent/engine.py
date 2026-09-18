"""Build the single read-only engine the backend owns and injects into the tool module.

Read-only is established once per connection, before the connection is handed out, so every
transaction the operator module opens on that engine is read-only regardless of whether the
module uses the ORM, Core, pandas.read_sql or parameterised text SQL. A dialect outside the
enforced set gets no wrapper, no warning and no refusal; read-only then depends on the account.
"""

from typing import Any, Final

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url

# PostgreSQL is made read-only through a libpq connection parameter, applied at connection
# startup outside any transaction, because SET is transactional and reverts on the pool's
# reset_rollback.
READ_ONLY_CONNECT_ARGS: Final[dict[str, dict[str, str]]] = {
    "postgresql": {"options": "-c default_transaction_read_only=on"},
}

# MySQL's session statement is not transactional, so a connect listener holds. MariaDB needs
# its own entry because SQLAlchemy gives `mariadb://` a distinct backend name; it is the one
# entry here with no live refused-write proof, which USER_GUIDE.md states.
READ_ONLY_STATEMENTS: Final[dict[str, str]] = {
    "mysql": "SET SESSION TRANSACTION READ ONLY",
    "mariadb": "SET SESSION TRANSACTION READ ONLY",
}


def read_only_url(url: URL) -> URL:
    """SQLite is opened read only by the operating system, through the file URI form.

    Any other dialect is returned unchanged. The file mode is strictly stronger than
    PRAGMA query_only, which a module could lift.
    """
    if url.get_backend_name() != "sqlite":
        return url
    if not url.database:
        raise ValueError("a SQLite URL with no database part cannot be opened read only")
    database = url.database if url.database.startswith("file:") else "file:" + url.database
    query = {**url.query, "mode": "ro", "uri": "true"}
    return url.set(database=database, query=query)


def build_read_only_engine(url_string: str) -> Engine:
    """Build the one engine the backend owns. No connection is opened here."""
    url = read_only_url(make_url(url_string))
    # One name drives both tables, so a dialect cannot be enforced by one and missed by the other.
    backend_name = url.get_backend_name()
    connect_args = dict(READ_ONLY_CONNECT_ARGS.get(backend_name, {}))

    configured = url.query.get("options")
    if "options" in connect_args and configured:
        # connect_args replaces the URL's own options outright, so merge to keep an operator's
        # tuning. The read-only flag goes last, where a configured value cannot turn it off.
        prefix = " ".join(configured) if isinstance(configured, tuple) else configured
        connect_args["options"] = f"{prefix} {connect_args['options']}"

    engine = create_engine(url, connect_args=connect_args)
    statement = READ_ONLY_STATEMENTS.get(backend_name)
    if statement is not None:

        @event.listens_for(engine, "connect")
        def _apply_read_only(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute(statement)
            cursor.close()

    return engine
