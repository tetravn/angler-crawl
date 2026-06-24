"""SSE: chạy một coroutine với callback `emit`, phát event ra text/event-stream."""
import asyncio
import contextlib
import json

from fastapi.responses import StreamingResponse


async def sse_response(factory) -> StreamingResponse:
    """factory(emit) là coroutine; emit(ev: dict) async đẩy event. Trả StreamingResponse SSE.

    factory lỗi → phát event {"type":"error",...}. Client ngắt (generator đóng) → cancel task."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)

    async def emit(ev: dict) -> None:
        await q.put(ev)

    async def runner() -> None:
        try:
            await factory(emit)
        except Exception as exc:
            await q.put({"type": "error", "error": str(exc)})
        finally:
            await q.put(None)   # sentinel

    task = asyncio.create_task(runner())

    async def gen():
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    return StreamingResponse(gen(), media_type="text/event-stream")
