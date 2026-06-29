"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gateways",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("incus_instance", sa.String(length=128), nullable=False),
        sa.Column("vm_ip", sa.String(length=45), nullable=False),
        sa.Column("udp_port", sa.Integer(), nullable=False),
        sa.Column("wg_subnet", sa.String(length=18), nullable=False),
        sa.Column("wg_server_pubkey", sa.String(length=64), nullable=False),
        sa.Column("wg_server_privkey_enc", sa.Text(), nullable=False),
        sa.Column("exit_node_id", sa.String(length=128), nullable=False),
        sa.Column("tailscale_auth_key_enc", sa.Text(), nullable=False),
        sa.Column("tailscale_hostname", sa.String(length=128), nullable=False),
        sa.Column("agent_token_hash", sa.String(length=128), nullable=False),
        sa.Column("agent_token_enc", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROVISIONING",
                "READY",
                "ERROR",
                "DELETING",
                name="gatewaystatus",
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("udp_port"),
    )
    op.create_index(op.f("ix_gateways_name"), "gateways", ["name"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("type", sa.Enum("CREATE_GATEWAY", "DELETE_GATEWAY", name="jobtype"), nullable=False),
        sa.Column("gateway_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", name="jobstatus"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "peers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gateway_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("private_key_enc", sa.Text(), nullable=False),
        sa.Column("allowed_ip", sa.String(length=45), nullable=False),
        sa.Column("suspended", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_key"),
    )

    op.create_table(
        "port_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("udp_port", sa.Integer(), nullable=False),
        sa.Column("gateway_id", sa.Integer(), nullable=True),
        sa.Column("allocated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("udp_port"),
    )

    op.create_table(
        "ip_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("gateway_id", sa.Integer(), nullable=True),
        sa.Column("peer_id", sa.Integer(), nullable=True),
        sa.Column("allocated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["peer_id"], ["peers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address"),
    )

    op.create_table(
        "gateway_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gateway_id", sa.Integer(), nullable=False),
        sa.Column("vm_status", sa.String(length=32), nullable=True),
        sa.Column("tailscale_online", sa.Boolean(), nullable=True),
        sa.Column("wg_online", sa.Boolean(), nullable=True),
        sa.Column("exit_node_reachable", sa.Boolean(), nullable=True),
        sa.Column("polled_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_gateway_metrics_gateway_id"), "gateway_metrics", ["gateway_id"], unique=False)

    op.create_table(
        "peer_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("peer_id", sa.Integer(), nullable=False),
        sa.Column("last_handshake", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rx_bytes", sa.BigInteger(), nullable=True),
        sa.Column("tx_bytes", sa.BigInteger(), nullable=True),
        sa.Column("polled_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["peer_id"], ["peers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_peer_metrics_peer_id"), "peer_metrics", ["peer_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_peer_metrics_peer_id"), table_name="peer_metrics")
    op.drop_table("peer_metrics")
    op.drop_index(op.f("ix_gateway_metrics_gateway_id"), table_name="gateway_metrics")
    op.drop_table("gateway_metrics")
    op.drop_table("ip_allocations")
    op.drop_table("port_allocations")
    op.drop_table("peers")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_gateways_name"), table_name="gateways")
    op.drop_table("gateways")
