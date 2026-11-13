
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.bot import main as run_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_task = asyncio.create_task(run_bot())
    yield
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Family Money",
    lifespan=lifespan
)


@app.get("/")
async def home():
    return {
        "project": "Family Money",
        "status": "working",
        "message": "Оилавий молия тизими ишга тушди!"
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
