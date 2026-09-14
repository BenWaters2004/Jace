from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jace.config import DATABASE_PATH, DATA_DIRECTORY
from jace.db.models import Base


DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
DATABASE_URL = "sqlite+aiosqlite:///" + DATABASE_PATH.as_posix()
engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record):
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def _ensure_step4a5_columns(connection) -> None:
    result = await connection.exec_driver_sql(
        "PRAGMA table_info(tool_audit_log)"
    )
    columns = {str(row[1]) for row in result.fetchall()}

    additions = {
        "provider_id": "VARCHAR(80)",
        "connection_id": "VARCHAR(36)",
        "capability_id": "VARCHAR(160)",
        "account_hint": "VARCHAR(300)",
    }

    for name, sql_type in additions.items():
        if name not in columns:
            await connection.exec_driver_sql(
                f"ALTER TABLE tool_audit_log ADD COLUMN {name} {sql_type}"
            )

    await connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_tool_audit_log_provider_id "
        "ON tool_audit_log (provider_id)"
    )
    await connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_tool_audit_log_connection_id "
        "ON tool_audit_log (connection_id)"
    )
    await connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_tool_audit_log_capability_id "
        "ON tool_audit_log (capability_id)"
    )


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _ensure_step4a5_columns(connection)
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")


async def close_database() -> None:
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
