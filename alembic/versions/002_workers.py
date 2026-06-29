"""Workers table and gateway worker_id

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _find_unique_constraint(table: str, columns: list[str]) -> str | None:
    bind = op.get_bind()
    for constraint in inspect(bind).get_unique_constraints(table):
        if constraint["column_names"] == columns and constraint.get("name"):
            return constraint["name"]
    return None


def _upgrade_gateways_sqlite() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE gateways_new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL REFERENCES workers(id),
                name VARCHAR(128) NOT NULL,
                incus_instance VARCHAR(128) NOT NULL,
                vm_ip VARCHAR(45) NOT NULL,
                udp_port INTEGER NOT NULL,
                wg_subnet VARCHAR(18) NOT NULL,
                wg_server_pubkey VARCHAR(64) NOT NULL,
                wg_server_privkey_enc TEXT NOT NULL,
                exit_node_id VARCHAR(128) NOT NULL,
                tailscale_auth_key_enc TEXT NOT NULL,
                tailscale_hostname VARCHAR(128) NOT NULL,
                agent_token_hash VARCHAR(128) NOT NULL,
                agent_token_enc TEXT NOT NULL,
                status VARCHAR(12) NOT NULL,
                error_message TEXT,
                created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                UNIQUE (name),
                UNIQUE (worker_id, udp_port)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO gateways_new (
                id, worker_id, name, incus_instance, vm_ip, udp_port, wg_subnet,
                wg_server_pubkey, wg_server_privkey_enc, exit_node_id,
                tailscale_auth_key_enc, tailscale_hostname, agent_token_hash,
                agent_token_enc, status, error_message, created_at, updated_at
            )
            SELECT
                id, 1, name, incus_instance, vm_ip, udp_port, wg_subnet,
                wg_server_pubkey, wg_server_privkey_enc, exit_node_id,
                tailscale_auth_key_enc, tailscale_hostname, agent_token_hash,
                agent_token_enc, status, error_message, created_at, updated_at
            FROM gateways
            """
        )
    )
    op.execute(sa.text("DROP TABLE gateways"))
    op.execute(sa.text("ALTER TABLE gateways_new RENAME TO gateways"))
    op.create_index("ix_gateways_name", "gateways", ["name"], unique=False)
    op.create_index("ix_gateways_worker_id", "gateways", ["worker_id"], unique=False)


def _upgrade_port_allocations_sqlite() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE port_allocations_new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                udp_port INTEGER NOT NULL,
                gateway_id INTEGER REFERENCES gateways(id) ON DELETE SET NULL,
                allocated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                UNIQUE (worker_id, udp_port)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO port_allocations_new (id, worker_id, udp_port, gateway_id, allocated_at)
            SELECT id, 1, udp_port, gateway_id, allocated_at
            FROM port_allocations
            """
        )
    )
    op.execute(sa.text("DROP TABLE port_allocations"))
    op.execute(sa.text("ALTER TABLE port_allocations_new RENAME TO port_allocations"))


def _upgrade_ip_allocations_sqlite() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE ip_allocations_new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                address VARCHAR(45) NOT NULL,
                gateway_id INTEGER REFERENCES gateways(id) ON DELETE SET NULL,
                peer_id INTEGER REFERENCES peers(id) ON DELETE SET NULL,
                allocated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                UNIQUE (worker_id, address)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ip_allocations_new (id, worker_id, address, gateway_id, peer_id, allocated_at)
            SELECT id, 1, address, gateway_id, peer_id, allocated_at
            FROM ip_allocations
            """
        )
    )
    op.execute(sa.text("DROP TABLE ip_allocations"))
    op.execute(sa.text("ALTER TABLE ip_allocations_new RENAME TO ip_allocations"))


def _upgrade_table_with_worker(
    table: str,
    *,
    fk_name: str,
    old_unique_columns: list[str],
    new_unique_name: str,
    new_unique_columns: list[str],
    ondelete: str | None = None,
) -> None:
    with op.batch_alter_table(table) as batch_op:
        batch_op.add_column(sa.Column("worker_id", sa.Integer(), nullable=True))
    op.execute(sa.text(f"UPDATE {table} SET worker_id = 1 WHERE worker_id IS NULL"))
    with op.batch_alter_table(table) as batch_op:
        batch_op.alter_column("worker_id", nullable=False)
        fk_kwargs: dict = {}
        if ondelete:
            fk_kwargs["ondelete"] = ondelete
        batch_op.create_foreign_key(fk_name, "workers", ["worker_id"], ["id"], **fk_kwargs)
        old_name = _find_unique_constraint(table, old_unique_columns)
        if old_name:
            batch_op.drop_constraint(old_name, type_="unique")
        batch_op.create_unique_constraint(new_unique_name, new_unique_columns)


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("public_ip", sa.String(length=45), nullable=False),
        sa.Column("tailscale_hostname", sa.String(length=128), nullable=True),
        sa.Column("incus_remote", sa.String(length=64), nullable=True),
        sa.Column("incus_url", sa.String(length=512), nullable=True),
        sa.Column("incus_cert_path", sa.String(length=512), nullable=True),
        sa.Column("incus_key_path", sa.String(length=512), nullable=True),
        sa.Column("worker_token_hash", sa.String(length=128), nullable=False),
        sa.Column("port_pool_start", sa.Integer(), nullable=False),
        sa.Column("port_pool_end", sa.Integer(), nullable=False),
        sa.Column("ip_pool_network", sa.String(length=18), nullable=False),
        sa.Column("ip_pool_start", sa.String(length=45), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="offline"),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("memory_total_mb", sa.Integer(), nullable=True),
        sa.Column("memory_used_mb", sa.Integer(), nullable=True),
        sa.Column("memory_percent", sa.Float(), nullable=True),
        sa.Column("network_rx_bps", sa.Float(), nullable=True),
        sa.Column("network_tx_bps", sa.Float(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_workers_name"), "workers", ["name"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO workers (
                name, display_name, public_ip, worker_token_hash,
                port_pool_start, port_pool_end, ip_pool_network, ip_pool_start,
                enabled, status
            ) VALUES (
                'local', 'Local (control plane)', '127.0.0.1', 'unset-local-worker',
                51001, 52000, '10.10.0.0/16', '10.10.1.10',
                1, 'offline'
            )
            """
        )
    )

    if _is_sqlite():
        _upgrade_gateways_sqlite()
        _upgrade_port_allocations_sqlite()
        _upgrade_ip_allocations_sqlite()
        return

    _upgrade_table_with_worker(
        "gateways",
        fk_name="fk_gateways_worker_id",
        old_unique_columns=["udp_port"],
        new_unique_name="uq_gateway_worker_udp_port",
        new_unique_columns=["worker_id", "udp_port"],
    )
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.create_index("ix_gateways_worker_id", ["worker_id"])

    _upgrade_table_with_worker(
        "port_allocations",
        fk_name="fk_port_alloc_worker_id",
        old_unique_columns=["udp_port"],
        new_unique_name="uq_port_worker_udp",
        new_unique_columns=["worker_id", "udp_port"],
        ondelete="CASCADE",
    )
    _upgrade_table_with_worker(
        "ip_allocations",
        fk_name="fk_ip_alloc_worker_id",
        old_unique_columns=["address"],
        new_unique_name="uq_ip_worker_address",
        new_unique_columns=["worker_id", "address"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    raise NotImplementedError("002 downgrade not supported")
