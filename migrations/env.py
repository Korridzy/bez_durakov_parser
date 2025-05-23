import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
import sqlalchemy as sa

from alembic import context

from db import Base

# Add the project root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import URL from our configuration
from config import DATABASE_URL

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Replacing the sqlalchemy.url option with one from project config file
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# setting the render mode to "batch" for SQLite
render_as_batch = config.get_main_option("sqlalchemy.url", "").startswith("sqlite")

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def process_revision_directives_sqlite(context, revision, directives):
    """Process migration directives to automatically add server_default for NOT NULL columns in SQLite."""

    # Only apply for SQLite database
    if not context.dialect.name == 'sqlite':
        return

    migration_script = directives[0]
    operations = migration_script.upgrade_ops

    # Function to process operations recursively
    def process_op(op):
        # For column additions
        if hasattr(op, 'column') and op.column.nullable is False and not op.column.server_default:
            # For numeric types
            if isinstance(op.column.type, sa.Numeric) or isinstance(op.column.type, sa.Integer):
                op.column.server_default = sa.DefaultClause('0')
            # For string types
            elif isinstance(op.column.type, sa.String):
                op.column.server_default = sa.DefaultClause("''")
            # For boolean types
            elif isinstance(op.column.type, sa.Boolean):
                op.column.server_default = sa.DefaultClause('false')

        # Process nested operations like batch operations
        if hasattr(op, 'ops'):
            for nested_op in op.ops:
                process_op(nested_op)

    # Process all operations
    for op in operations.ops:
        process_op(op)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=render_as_batch,
        process_revision_directives=process_revision_directives_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=render_as_batch,
            process_revision_directives=process_revision_directives_sqlite,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
