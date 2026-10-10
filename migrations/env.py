from alembic import context
from backend.db import Base, engine
from backend import models

if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        sqlite = connection.dialect.name == 'sqlite'
        if sqlite:
            connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
            connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            violations = connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall()
            if violations:
                raise RuntimeError('Migration left invalid foreign keys')
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
