"""Keep visual evidence alongside speech and visual beats."""

import sqlalchemy as sa
from alembic import op

revision = "e6a248cf0912"
down_revision = "d58107a2c930"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("beat", sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("beat", "evidence")
