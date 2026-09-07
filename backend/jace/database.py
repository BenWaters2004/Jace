from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from jace.config import (
    DATABASE_PATH,
    DATA_DIRECTORY,
)
from jace.db.models import Base


DATA_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True,
)


DATABASE_URL = (
    "sqlite+aiosqlite:///"
    + DATABASE_PATH.as_posix()
)


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@event.listens_for(
    engine.sync_engine,
    "connect",
)
def set_sqlite_pragmas(
    dbapi_connection,
    connection_record,
):
    del connection_record

    cursor = dbapi_connection.cursor()

    cursor.execute(
        "PRAGMA foreign_keys=ON"
    )

    cursor.close()


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all
        )

        await connection.exec_driver_sql(
            "PRAGMA journal_mode=WAL"
        )


async def close_database() -> None:
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session