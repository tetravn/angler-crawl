"""Lưu job crawl vào SQLite (trên volume) để sống sót qua restart.

Job vẫn được giữ trong RAM (crawl_jobs.JOBS) để cập nhật nhanh; mỗi lần đổi
trạng thái thì ghi đè cả job (dạng JSON) xuống SQLite. Khi khởi động, nạp lại
các job chưa hết hạn vào RAM.
"""
import asyncio
import json
import os
import sqlite3
import time

from .config import JOBS_DB_PATH

_lock = asyncio.Lock()  # tuần tự hoá ghi


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(JOBS_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(JOBS_DB_PATH) or ".", exist_ok=True)
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            "  id TEXT PRIMARY KEY,"
            "  payload TEXT NOT NULL,"
            "  expires REAL NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS monitors ("
            "  id TEXT PRIMARY KEY,"
            "  payload TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  ts REAL NOT NULL,"
            "  level TEXT NOT NULL,"
            "  kind TEXT NOT NULL,"
            "  request_id TEXT,"
            "  msg TEXT NOT NULL,"
            "  fields TEXT)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_req ON events(request_id)")


def _save_sync(job: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO jobs(id, payload, expires) VALUES (?, ?, ?)",
            (job["id"], json.dumps(job), job.get("_expires_ts", time.time() + 86400)),
        )


async def save_job(job: dict) -> None:
    async with _lock:
        await asyncio.to_thread(_save_sync, job)


def _load_all_sync() -> list[dict]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM jobs WHERE expires > ?", (time.time(),)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]
    except Exception:
        return []


async def load_all() -> list[dict]:
    return await asyncio.to_thread(_load_all_sync)


def _purge_sync() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE expires < ?", (time.time(),))


async def purge_expired() -> None:
    async with _lock:
        await asyncio.to_thread(_purge_sync)


def _save_monitor_sync(mon: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO monitors(id, payload) VALUES (?, ?)",
            (mon["id"], json.dumps(mon)),
        )


async def save_monitor(mon: dict) -> None:
    async with _lock:
        await asyncio.to_thread(_save_monitor_sync, mon)


def _load_monitors_sync() -> list[dict]:
    try:
        with _connect() as conn:
            rows = conn.execute("SELECT payload FROM monitors").fetchall()
        return [json.loads(r[0]) for r in rows]
    except Exception:
        return []


async def load_monitors() -> list[dict]:
    return await asyncio.to_thread(_load_monitors_sync)


def _delete_monitor_sync(mon_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM monitors WHERE id = ?", (mon_id,))


async def delete_monitor(mon_id: str) -> None:
    async with _lock:
        await asyncio.to_thread(_delete_monitor_sync, mon_id)


# ─── Activity events ──────────────────────────────────────────────────────
def append_events_sync(rows: list[dict]) -> None:
    """Ghi 1 lô event (gọi trong thread). Mỗi row có ts/level/kind/request_id/msg/fields."""
    if not rows:
        return
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO events(ts, level, kind, request_id, msg, fields) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(r["ts"], r["level"], r["kind"], r.get("request_id"), r["msg"], r.get("fields"))
             for r in rows],
        )


def _query_events_sync(kind, level, request_id, since, until, limit) -> list[dict]:
    sql = "SELECT ts, level, kind, request_id, msg, fields FROM events WHERE 1=1"
    params: list = []
    if kind:
        sql += " AND kind = ?"; params.append(kind)
    if level:
        sql += " AND level = ?"; params.append(level.upper())
    if request_id:
        sql += " AND request_id = ?"; params.append(request_id)
    if since is not None:
        sql += " AND ts >= ?"; params.append(since)
    if until is not None:
        sql += " AND ts <= ?"; params.append(until)
    sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for ts, lvl, knd, rid, msg, fields in rows:
        out.append({"ts": ts, "level": lvl, "kind": knd, "request_id": rid,
                    "msg": msg, "fields": json.loads(fields) if fields else None})
    return out


async def query_events(kind=None, level=None, request_id=None,
                       since=None, until=None, limit=200) -> list[dict]:
    return await asyncio.to_thread(
        _query_events_sync, kind, level, request_id, since, until, limit)


def _stats_events_sync(window_seconds: float, now: float) -> dict:
    floor = now - window_seconds
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM events WHERE ts >= ?", (floor,)).fetchone()[0]
        by_kind = dict(conn.execute(
            "SELECT kind, COUNT(*) FROM events WHERE ts >= ? GROUP BY kind", (floor,)).fetchall())
        by_level = dict(conn.execute(
            "SELECT level, COUNT(*) FROM events WHERE ts >= ? GROUP BY level", (floor,)).fetchall())
        # Outcome scrape: đếm theo json_extract(fields,'$.outcome') và '$.domain'.
        outcomes = dict(conn.execute(
            "SELECT json_extract(fields,'$.outcome') AS o, COUNT(*) FROM events "
            "WHERE ts >= ? AND kind='scrape' AND o IS NOT NULL GROUP BY o", (floor,)).fetchall())
        by_domain = conn.execute(
            "SELECT json_extract(fields,'$.domain') AS d, "
            "  SUM(CASE WHEN json_extract(fields,'$.outcome')='blocked' THEN 1 ELSE 0 END), "
            "  SUM(CASE WHEN json_extract(fields,'$.stub')=1 THEN 1 ELSE 0 END), "
            "  COUNT(*) "
            "FROM events WHERE ts >= ? AND kind='scrape' AND d IS NOT NULL "
            "GROUP BY d ORDER BY COUNT(*) DESC LIMIT 20", (floor,)).fetchall()
    return {
        "windowSeconds": window_seconds,
        "total": total,
        "byKind": by_kind,
        "byLevel": by_level,
        "scrapeOutcomes": outcomes,
        "topDomains": [{"domain": d, "blocked": b, "stub": s, "total": t}
                       for d, b, s, t in by_domain],
    }


async def stats_events(window_seconds: float, now: float) -> dict:
    return await asyncio.to_thread(_stats_events_sync, window_seconds, now)


def purge_events_sync(ttl_seconds: float, now: float) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM events WHERE ts < ?", (now - ttl_seconds,))


async def append_events(rows: list[dict]) -> None:
    """Ghi lô event (async, tuần tự qua _lock)."""
    async with _lock:
        await asyncio.to_thread(append_events_sync, rows)


async def purge_events(ttl_seconds: float, now: float) -> None:
    """Xoá event cũ (async, tuần tự qua _lock)."""
    async with _lock:
        await asyncio.to_thread(purge_events_sync, ttl_seconds, now)
