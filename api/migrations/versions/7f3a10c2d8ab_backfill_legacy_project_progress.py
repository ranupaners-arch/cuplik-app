"""Backfill progress for completed/failed projects created before project events."""

import sqlalchemy as sa
from alembic import op

revision = "7f3a10c2d8ab"
down_revision = "da02ca9a37f1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            "UPDATE project SET stage='done', progress=1, note='Sumber dan transkrip tersimpan; cache siap digunakan' WHERE transcript_status='done' AND stage='queued'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE project SET stage='failed', note='Proses sebelumnya gagal; coba ulang ingest/transkripsi' WHERE transcript_status='failed' AND stage='queued'"
        )
    )


def downgrade():
    # Historical progress cannot be reconstructed. Keep the accurate data on downgrade.
    pass
