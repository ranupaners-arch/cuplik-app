"""Preserve selection provenance and rerank notes alongside each clip."""

import sqlalchemy as sa
from alembic import op

revision = "a937e1c42f60"
down_revision = "7f3a10c2d8ab"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clip", sa.Column("selection", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("clip", "selection")
