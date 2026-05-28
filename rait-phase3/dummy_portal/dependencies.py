"""FastAPI dependency factories for the Dummy Portal."""
from collections.abc import AsyncGenerator

from fastapi import Request

from .database import get_db
from .decryption import DecryptionEngine


async def db_dependency(request: Request) -> AsyncGenerator:
    async for conn in get_db(request.app.state.db_path):
        yield conn


def get_decryption_engine(request: Request) -> DecryptionEngine:
    return request.app.state.decryption_engine
