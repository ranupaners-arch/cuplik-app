from alembic import context

from api.app.db import get_engine
from api.app.models import SQLModel

with get_engine().connect() as connection:
    # sqlite3's legacy transaction mode does not BEGIN for DDL. Start explicitly
    # so a failed migration rolls back schema changes together with its data.
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    context.configure(
        connection=connection, target_metadata=SQLModel.metadata, render_as_batch=True
    )
    try:
        with context.begin_transaction():
            context.run_migrations()
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
