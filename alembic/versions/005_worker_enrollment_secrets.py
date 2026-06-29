"""Persist worker enrollment secrets for modal re-open.

Revision ID: 005_worker_enrollment_secrets
Revises: 004_worker_enrollment
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_worker_enrollment_secrets"
down_revision: str | None = "004_worker_enrollment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "worker_enrollments",
        sa.Column("enroll_token_enc", sa.Text(), nullable=True),
    )
    op.add_column(
        "worker_enrollments",
        sa.Column("headscale_auth_key_enc", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("worker_enrollments", "headscale_auth_key_enc")
    op.drop_column("worker_enrollments", "enroll_token_enc")
