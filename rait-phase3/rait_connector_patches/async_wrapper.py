"""Async wrapper for synchronous rait_connector calls (Phase 4 prep).

Phase 3 driver scripts are synchronous and do not need this.
Use in Phase 4 if the portal ever calls RAITClient internally from async context.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

_executor = ThreadPoolExecutor(max_workers=4)


async def async_evaluate(client, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, partial(client.evaluate, **kwargs))


async def async_evaluate_batch(client, prompts, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, partial(client.evaluate_batch, prompts, **kwargs)
    )
