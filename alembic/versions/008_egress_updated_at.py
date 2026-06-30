"""Track when egress geo was last refreshed."""

from alembic import op
import sqlalchemy as sa

revision = "008_egress_updated_at"
down_revision = "007_gateway_egress_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_metrics",
        sa.Column("egress_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateway_metrics", "egress_updated_at")
