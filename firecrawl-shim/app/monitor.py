"""P7 — /monitor: theo dõi thay đổi 1 URL theo chu kỳ (sweeper + diff). Không LLM.

Tái dùng scrape.scrape() (CF-bypass + egress P9 + cache). Nguồn bị chặn (blocked) KHÔNG
tính là thay đổi (giữ snapshot) — đúng tinh thần anti-bias của stack.
"""
import asyncio
import difflib
import hashlib
import logging
import re
import secrets
import time

from . import applog, egress, scrape as scrape_mod, store
from .config import (
    CRAWL_CONCURRENCY,
    MONITOR_DEFAULT_INTERVAL,
    MONITOR_MAX_EVENTS,
    MONITOR_MIN_INTERVAL,
    MONITOR_TICK,
)

log = logging.getLogger("shim.monitor")

# id -> monitor dict (cache RAM; nguồn bền vững là SQLite qua store)
MONITORS: dict[str, dict] = {}
_LOCKS: dict[str, asyncio.Lock] = {}  # khóa per-monitor: tránh check trùng (sweeper + /check)
_SWEEPER_TASK: asyncio.Task | None = None

_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUNS = re.compile(r"\n{3,}")


def now_iso() -> str:
    """Trả về thời gian hiện tại theo định dạng ISO 8601 với múi giờ UTC."""
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _normalize(md: str) -> str:
    """Chuẩn hóa markdown trước khi hash/diff để giảm nhiễu (trailing ws, dòng trống thừa)."""
    s = _TRAILING_WS.sub("", md or "")
    s = _BLANK_RUNS.sub("\n\n", s)
    return s.strip()


def _hash(md: str) -> str:
    """Tính hash SHA256 của markdown sau chuẩn hóa."""
    return hashlib.sha256(_normalize(md).encode("utf-8", "ignore")).hexdigest()


def _make_diff(old: str, new: str) -> str:
    """Unified diff giữa 2 bản (đã normalize). '' nếu giống nhau."""
    o = _normalize(old).splitlines()
    n = _normalize(new).splitlines()
    if o == n:
        return ""
    return "\n".join(difflib.unified_diff(o, n, fromfile="trước", tofile="sau", lineterm=""))


def _apply_check_result(mon: dict, markdown: str, blocked: bool, at: str) -> dict | None:
    """Cập nhật mon TẠI CHỖ theo kết quả 1 lần check. Trả change-event mới hoặc None.

    blocked → giữ snapshot (không 'đổi giả'); baseline → đặt snapshot, không event;
    hash giống → None; hash khác → tạo event (unified diff) + cập nhật snapshot/hash.
    """
    mon["lastCheckedAt"] = at
    mon["checkCount"] = mon.get("checkCount", 0) + 1
    if blocked:
        mon["lastBlocked"] = True
        return None
    mon["lastBlocked"] = False
    new_hash = _hash(markdown)
    if mon.get("currentHash") is None:            # baseline
        mon["snapshot"] = markdown
        mon["currentHash"] = new_hash
        return None
    if new_hash == mon["currentHash"]:            # không đổi
        return None
    event = {                                     # đổi
        "at": at,
        "fromHash": mon["currentHash"],
        "toHash": new_hash,
        "diff": _make_diff(mon.get("snapshot") or "", markdown),
    }
    mon["snapshot"] = markdown
    mon["currentHash"] = new_hash
    mon["lastChangedAt"] = at
    mon["changeCount"] = mon.get("changeCount", 0) + 1
    mon["events"] = (mon.get("events") or [])[-(MONITOR_MAX_EVENTS - 1):] + [event]
    return event


def _new_monitor(url: str, interval, scrape_options, egress_mode) -> dict:
    """Tạo monitor mới (đưa vào MONITORS). interval ép >= MONITOR_MIN_INTERVAL."""
    mon = {
        "id": secrets.token_hex(12),
        "url": url,
        "intervalSeconds": max(MONITOR_MIN_INTERVAL, int(interval or MONITOR_DEFAULT_INTERVAL)),
        "scrapeOptions": scrape_options or {"formats": ["markdown"], "onlyMainContent": True},
        "egress": egress_mode,
        "status": "active",
        "createdAt": now_iso(),
        "lastCheckedAt": None,
        "lastChangedAt": None,
        "checkCount": 0,
        "changeCount": 0,
        "lastBlocked": False,
        "currentHash": None,
        "snapshot": None,
        "events": [],
        "error": None,
        "_next_due": time.time(),
    }
    MONITORS[mon["id"]] = mon
    return mon


_SUMMARY_KEYS = (
    "id", "url", "status", "intervalSeconds", "lastCheckedAt", "lastChangedAt",
    "checkCount", "changeCount", "lastBlocked", "error",
)


def summary(mon: dict) -> dict:
    """Bản tóm tắt cho list (bỏ snapshot/events cho gọn)."""
    return {k: mon.get(k) for k in _SUMMARY_KEYS}


async def create_monitor(url: str, interval, scrape_options, egress_mode) -> str:
    """Tạo monitor + persist. Trả id."""
    mon = _new_monitor(url, interval, scrape_options, egress_mode)
    await store.save_monitor(mon)
    return mon["id"]


async def delete_monitor(mon_id: str) -> bool:
    """Xóa monitor khỏi RAM + SQLite. False nếu không tồn tại."""
    if mon_id not in MONITORS:
        return False
    MONITORS.pop(mon_id, None)
    _LOCKS.pop(mon_id, None)
    await store.delete_monitor(mon_id)
    return True


async def check_monitor(mon: dict) -> dict | None:
    """Scrape 1 lần, áp kết quả vào mon, persist. Trả event nếu đổi.

    Chạy dưới khóa per-monitor + dời _next_due NGAY ĐẦU để sweeper không phóng
    một check thứ hai trùng monitor khi scrape lâu (vd trang Cloudflare ~120s).
    """
    lock = _LOCKS.setdefault(mon["id"], asyncio.Lock())
    async with lock:
        mon["_next_due"] = time.time() + mon["intervalSeconds"]
        opts = mon.get("scrapeOptions") or {}
        formats = opts.get("formats") or ["markdown"]
        only_main = opts.get("onlyMainContent", True)
        event = None
        try:
            proxy = await egress.resolve_proxy(mon.get("egress"))
            data, _r, _ = await scrape_mod.scrape(
                mon["url"], formats, only_main, proxy=proxy, bypass_cache=True
            )
            markdown = data.get("markdown") or ""
            blocked = bool((data.get("metadata") or {}).get("blocked"))
            event = _apply_check_result(mon, markdown, blocked, now_iso())
            mon["error"] = None
        except Exception as exc:
            log.warning("monitor %s lỗi check %s: %s", mon.get("id"), mon.get("url"), exc)
            applog.event("monitor", "check lỗi", level=logging.WARNING,
                         monitor_id=mon.get("id"), url=mon.get("url"), error=str(exc))
            mon["lastCheckedAt"] = now_iso()
            mon["error"] = str(exc)
        else:
            applog.event("monitor", "check xong", monitor_id=mon.get("id"), url=mon.get("url"),
                         changed=event is not None, blocked=bool((data.get("metadata") or {}).get("blocked")))
        await store.save_monitor(mon)
        return event


async def _sweeper() -> None:
    """Vòng nền: mỗi MONITOR_TICK giây, check các monitor active đến hạn (song song)."""
    sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

    async def _run(mon: dict) -> None:
        async with sem:
            await check_monitor(mon)

    while True:
        now = time.time()
        due = [
            m for m in list(MONITORS.values())
            if m.get("status") == "active" and m.get("_next_due", 0) <= now
        ]
        if due:
            await asyncio.gather(*[_run(m) for m in due], return_exceptions=True)
        await asyncio.sleep(MONITOR_TICK)


async def start() -> None:
    """Gọi ở startup: nạp monitor từ SQLite vào RAM rồi chạy sweeper."""
    for mon in await store.load_monitors():
        mon.setdefault("_next_due", time.time())
        MONITORS[mon["id"]] = mon
    log.info("nạp lại %d monitor từ SQLite", len(MONITORS))
    applog.event("monitor", "nạp lại monitor từ SQLite", count=len(MONITORS))
    global _SWEEPER_TASK
    _SWEEPER_TASK = asyncio.create_task(_sweeper())
