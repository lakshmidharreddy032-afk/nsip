from alembic import context
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import Base, engine
import app.models  # noqa: F401  (register tables)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    schema = get_settings().db_schema
    with engine.connect() as connection:
        if schema and connection.dialect.name == "postgresql":
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata,
                          version_table_schema=schema, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
