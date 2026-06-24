import asyncio

from app import sse


def _drain(resp):
    async def go():
        return [c async for c in resp.body_iterator]
    return asyncio.run(go())


def test_sse_emits_events_then_ends():
    async def factory(emit):
        await emit({"type": "phase", "phase": "a"})
        await emit({"type": "done", "data": {"x": 1}})

    resp = asyncio.run(sse.sse_response(factory))
    chunks = _drain(resp)
    body = "".join(chunks)
    assert 'data: {"type": "phase", "phase": "a"}' in body
    assert '"type": "done"' in body
    assert body.endswith("\n\n")


def test_sse_factory_error_emits_error_event():
    async def factory(emit):
        await emit({"type": "phase", "phase": "a"})
        raise RuntimeError("boom")

    resp = asyncio.run(sse.sse_response(factory))
    body = "".join(_drain(resp))
    assert '"type": "error"' in body and "boom" in body
