"""Require explicit review before speeding visual beats beyond narration limits."""

import sqlalchemy as sa
from alembic import op

revision = "f0714a6d932b"
down_revision = "e6a248cf0912"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "beat", sa.Column("timelapse_approved", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade():
    op.drop_column("beat", "timelapse_approved")
