from alembic import context

from backend.app.db.models import Base
from backend.app.db.session import engine

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
