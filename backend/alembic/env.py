from logging.config import fileConfig

from alembic import context

from app import models, models_auth, models_docs, models_finance, models_monitoring, models_notify, models_security, models_service, models_trade  # noqa: F401  (registers tables)
from app.config import get_settings
from app.db import Base, make_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Render app-specific column types as plain SQLAlchemy types so migrations never import app code."""
    if type_ == "type" and type(obj).__name__ == "UTCDateTime":
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    url = config.attributes.get("database_url") or get_settings().database_url
    engine = make_engine(url)
    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            # Batch migrations rebuild tables (DROP + RENAME). With FKs on, dropping a parent table fires
            # ON DELETE CASCADE and silently deletes child rows. Must be set outside a transaction.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        context.configure(connection=conn, target_metadata=target_metadata,
                          render_as_batch=conn.dialect.name == "sqlite", render_item=render_item)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
