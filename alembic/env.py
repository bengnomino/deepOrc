from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from orchestrator.config import get_settings
from orchestrator.models import Base
from orchestrator.models.gateway import Gateway  # noqa: F401
from orchestrator.models.job import Job  # noqa: F401
from orchestrator.models.metrics import GatewayMetric, PeerMetric  # noqa: F401
from orchestrator.models.peer import Peer  # noqa: F401
from orchestrator.models.resources import IpAllocation, PortAllocation  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
