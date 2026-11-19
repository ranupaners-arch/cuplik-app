"""Versioned human annotations and opt-in visual focus; preserve legacy rendering defaults."""

import sqlalchemy as sa
from alembic import op

revision = "d58107a2c930"
down_revision = "c841b29d1104"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("output", sa.Column("provenance", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("clip", sa.Column("visual_focus", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "annotation",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("dataset_kind", sa.String(), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("source_fingerprint", sa.String(), nullable=False),
        sa.Column("transcript_fingerprint", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "mode", name="uq_annotation_project_mode"),
    )
    op.create_index("ix_annotation_project_id", "annotation", ["project_id"])


def downgrade():
    op.drop_index("ix_annotation_project_id", table_name="annotation")
    op.drop_table("annotation")
    op.drop_column("clip", "visual_focus")
    op.drop_column("output", "provenance")
