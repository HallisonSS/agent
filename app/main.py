import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import close_pool, ensure_schema
from app.redis_client import close_redis, get_redis
from app.routers import admin, chat, events, system, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await get_redis().ping()
    await ensure_schema()
    yield
    await close_pool()
    await close_redis()


# app é criado ANTES de qualquer include_router (o código antigo fazia o contrário => NameError)
app = FastAPI(title="Mona Lisa", lifespan=lifespan)

app.include_router(system.public)
app.include_router(system.router)
app.include_router(events.router)
app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(voice.router)
