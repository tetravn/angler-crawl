"""Activity log: mỗi quyết định/hoạt động → stdout (theo level) + bảng events (SQLite).

event() không bao giờ làm hỏng caller: enqueue không chặn, lỗi nuốt im. Ghi DB chạy
ở task nền theo lô. request_id lấy tự động từ contextvars nếu không truyền tay.
"""
import asyncio
import contextvars
import json
import logging
import time

from . import store
from .config import (
    LOG_BATCH_FLUSH_N, LOG_BATCH_FLUSH_SEC, LOG_DB_ENABLED, LOG_DB_LEVEL,
    LOG_FIELDS_MAX_CHARS, LOG_TTL_SECONDS,
)

log = logging.getLogger("shim.activity")

_request_id: contextvars.ContextVar = contextvars.ContextVar("request_id", default=None)
_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
_writer_task: asyncio.Task | None = None
_db_threshold = logging.getLevelName(LOG_DB_LEVEL)  # str→int; nếu lạ trả về str
if not isinstance(_db_threshold, int):
    _db_threshold = logging.INFO
_dropped = 0


def set_request_id(rid):
    _request_id.set(rid)


def get_request_id():
    return _request_id.get()


def event(kind, msg, *, level=logging.INFO, request_id=None, **fields):
    """Log một hoạt động. Ra stdout theo level; vào DB nếu level >= ngưỡng."""
    rid = request_id if request_id is not None else _request_id.get()
    # stdout (luôn, theo level của logger shim.activity)
    try:
        log.log(level, "[%s] %s %s", kind, msg, fields if fields else "")
    except Exception:
        pass
    if not LOG_DB_ENABLED or level < _db_threshold:
        return
    try:
        blob = json.dumps(fields, ensure_ascii=False, default=str) if fields else None
        if blob and len(blob) > LOG_FIELDS_MAX_CHARS:
            blob = blob[:LOG_FIELDS_MAX_CHARS]
        row = {"ts": time.time(), "level": logging.getLevelName(level),
               "kind": kind, "request_id": rid, "msg": msg, "fields": blob}
        _queue.put_nowait(row)
    except asyncio.QueueFull:
        global _dropped
        _dropped += 1
    except Exception:
        pass


async def _drain_once(rows):
    """Lấy tối đa LOG_BATCH_FLUSH_N row, chờ tối đa LOG_BATCH_FLUSH_SEC cho row đầu."""
    try:
        first = await asyncio.wait_for(_queue.get(), timeout=LOG_BATCH_FLUSH_SEC)
        rows.append(first)
    except asyncio.TimeoutError:
        return
    while len(rows) < LOG_BATCH_FLUSH_N:
        try:
            rows.append(_queue.get_nowait())
        except asyncio.QueueEmpty:
            break


async def _writer_loop():
    last_purge = time.time()
    while True:
        rows: list = []
        await _drain_once(rows)
        if rows:
            try:
                await store.append_events(rows)
            except Exception as exc:
                log.warning("ghi events lỗi (bỏ qua lô %d): %s", len(rows), exc)
        # dọn event cũ mỗi ~1h
        now = time.time()
        if now - last_purge > 3600:
            last_purge = now
            try:
                await store.purge_events(LOG_TTL_SECONDS, now)
            except Exception:
                pass


async def start_writer():
    global _writer_task
    if _writer_task is None:
        _writer_task = asyncio.create_task(_writer_loop())


async def stop_writer():
    global _writer_task
    task = _writer_task
    _writer_task = None
    if task is not None:
        task.cancel()
        try:
            await task  # chờ task thật sự dừng trước khi flush tránh race trên lock
        except asyncio.CancelledError:
            pass
    # flush phần còn lại
    rows = []
    while not _queue.empty():
        try:
            rows.append(_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    if rows:
        try:
            await store.append_events(rows)
        except Exception:
            pass
