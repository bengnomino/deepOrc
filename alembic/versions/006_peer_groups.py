"""Peer groups and gateway LAN / macvlan fields.

Revision ID: 006_peer_groups
Revises: 005_worker_enrollment_secrets
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_peer_groups"
down_revision: str | None = "005_worker_enrollment_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "peer_groups" not in inspector.get_table_names():
        op.create_table(
            "peer_groups",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("worker_id", sa.Integer(), nullable=False),
            sa.Column("lan_subnet", sa.String(length=18), nullable=False),
            sa.Column("lan_start_ip", sa.String(length=45), nullable=False),
            sa.Column("lan_gateway", sa.String(length=45), nullable=True),
            sa.Column("parent_iface", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index(op.f("ix_peer_groups_name"), "peer_groups", ["name"], unique=False)
        op.create_index(op.f("ix_peer_groups_worker_id"), "peer_groups", ["worker_id"], unique=False)

    gateway_cols = {col["name"] for col in inspector.get_columns("gateways")}
    if "peer_group_id" not in gateway_cols:
        if _is_sqlite():
            with op.batch_alter_table("gateways") as batch_op:
                batch_op.add_column(sa.Column("peer_group_id", sa.Integer(), nullable=True))
                batch_op.add_column(sa.Column("lan_ip", sa.String(length=45), nullable=True))
                batch_op.add_column(sa.Column("macvlan_slot", sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    "fk_gateways_peer_group_id",
                    "peer_groups",
                    ["peer_group_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                batch_op.create_index("ix_gateways_peer_group_id", ["peer_group_id"])
        else:
            op.add_column("gateways", sa.Column("peer_group_id", sa.Integer(), nullable=True))
            op.add_column("gateways", sa.Column("lan_ip", sa.String(length=45), nullable=True))
            op.add_column("gateways", sa.Column("macvlan_slot", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_gateways_peer_group_id",
                "gateways",
                "peer_groups",
                ["peer_group_id"],
                ["id"],
                ondelete="SET NULL",
            )
            op.create_index(op.f("ix_gateways_peer_group_id"), "gateways", ["peer_group_id"], unique=False)


def downgrade() -> None:
    if _is_sqlite():
        with op.batch_alter_table("gateways") as batch_op:
            batch_op.drop_index("ix_gateways_peer_group_id")
            batch_op.drop_constraint("fk_gateways_peer_group_id", type_="foreignkey")
            batch_op.drop_column("macvlan_slot")
            batch_op.drop_column("lan_ip")
            batch_op.drop_column("peer_group_id")
    else:
        op.drop_index(op.f("ix_gateways_peer_group_id"), table_name="gateways")
        op.drop_constraint("fk_gateways_peer_group_id", "gateways", type_="foreignkey")
        op.drop_column("gateways", "macvlan_slot")
        op.drop_column("gateways", "lan_ip")
        op.drop_column("gateways", "peer_group_id")
    op.drop_index(op.f("ix_peer_groups_worker_id"), table_name="peer_groups")
    op.drop_index(op.f("ix_peer_groups_name"), table_name="peer_groups")
    op.drop_table("peer_groups")
