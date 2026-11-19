"""Keep delivery intent explicit without relabeling existing landscape clips as Shorts."""

import sqlalchemy as sa
from alembic import op

revision = "c841b29d1104"
down_revision = "a937e1c42f60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "clip", sa.Column("purpose", sa.String(), nullable=False, server_default="discovery")
    )
    op.add_column(
        "clip", sa.Column("platform", sa.String(), nullable=False, server_default="youtube")
    )


def downgrade():
    op.drop_column("clip", "platform")
    op.drop_column("clip", "purpose")
