
import asyncio
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from bot import main as run_bot


def get_database_url():
    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError("DATABASE_URL киритилмаган!")

    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if key not in ("sslmode", "channel_binding")
    ]

    scheme = parts.scheme.replace("postgresql", "postgresql+asyncpg")

    return urlunsplit((
        scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment
    ))


engine = create_async_engine(
    get_database_url(),
    connect_args={"ssl": "require", "statement_cache_size": 0}
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS transactions (
                id BIGSERIAL PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                entry_type VARCHAR(20) NOT NULL,
                item_name TEXT NOT NULL,
                amount NUMERIC(14, 2) NOT NULL,
                category TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

    bot_task = asyncio.create_task(run_bot())

    yield

    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()


app = FastAPI(title="Family Money", lifespan=lifespan)


@app.get("/")
async def home():
    return {
        "project": "Family Money",
        "status": "working",
        "message": "Оилавий молия тизими ишга тушди!"
    }


@app.get("/health")
async def health():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected"
    }
