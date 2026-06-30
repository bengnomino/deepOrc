"""Add egress public IP and country to gateway metrics."""

from alembic import op
import sqlalchemy as sa

revision = "007_gateway_egress_geo"
down_revision = "006_peer_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_metrics", sa.Column("egress_public_ip", sa.String(45), nullable=True))
    op.add_column("gateway_metrics", sa.Column("egress_country_code", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("gateway_metrics", "egress_country_code")
    op.drop_column("gateway_metrics", "egress_public_ip")
