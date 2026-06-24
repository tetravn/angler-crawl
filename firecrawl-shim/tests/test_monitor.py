from app import monitor


def test_normalize_strips_trailing_ws_and_blank_runs():
    assert monitor._normalize("a  \nb\t\n\n\n\nc") == "a\nb\n\nc"


def test_hash_ignores_trailing_whitespace():
    assert monitor._hash("hello  \nworld") == monitor._hash("hello\nworld")
    assert monitor._hash("hello") != monitor._hash("hello!")


def test_make_diff_empty_when_same():
    assert monitor._make_diff("a\nb", "a\nb  ") == ""  # khác mỗi trailing ws → giống sau normalize


def test_make_diff_shows_changes():
    d = monitor._make_diff("a\nb\nc", "a\nB\nc")
    assert "-b" in d and "+B" in d


def test_now_iso_format():
    s = monitor.now_iso()
    assert s.endswith("Z") and "T" in s and len(s) == 24


def _fresh(**kw):
    m = {"id": "x", "currentHash": None, "snapshot": None, "checkCount": 0,
         "changeCount": 0, "events": []}
    m.update(kw)
    return m


def test_apply_baseline_sets_snapshot_no_event():
    m = _fresh()
    ev = monitor._apply_check_result(m, "hello", False, "T1")
    assert ev is None
    assert m["snapshot"] == "hello" and m["currentHash"] is not None
    assert m["checkCount"] == 1


def test_apply_unchanged_returns_none():
    m = _fresh()
    monitor._apply_check_result(m, "hello", False, "T1")
    ev = monitor._apply_check_result(m, "hello", False, "T2")
    assert ev is None and m["changeCount"] == 0 and m["checkCount"] == 2


def test_apply_changed_creates_event():
    m = _fresh()
    monitor._apply_check_result(m, "hello", False, "T1")
    ev = monitor._apply_check_result(m, "hello world", False, "T2")
    assert ev is not None and ev["at"] == "T2" and "+hello world" in ev["diff"]
    assert m["snapshot"] == "hello world" and m["changeCount"] == 1
    assert m["events"][-1] is ev and m["lastChangedAt"] == "T2"


def test_apply_blocked_keeps_snapshot_no_event():
    m = _fresh()
    monitor._apply_check_result(m, "hello", False, "T1")
    ev = monitor._apply_check_result(m, "", True, "T2")   # blocked, markdown rỗng
    assert ev is None and m["snapshot"] == "hello"        # KHÔNG đổi snapshot
    assert m["lastBlocked"] is True and m["changeCount"] == 0


def test_apply_trims_events_to_max(monkeypatch):
    monkeypatch.setattr(monitor, "MONITOR_MAX_EVENTS", 3)
    m = _fresh()
    monitor._apply_check_result(m, "v0", False, "T0")     # baseline
    for i in range(1, 6):
        monitor._apply_check_result(m, f"v{i}", False, f"T{i}")
    assert len(m["events"]) == 3
    assert m["events"][-1]["at"] == "T5"   # giữ mới nhất


def test_new_monitor_floors_interval_and_defaults():
    m = monitor._new_monitor("https://x.com", 5, None, None)  # 5 < MIN(60)
    assert m["intervalSeconds"] == monitor.MONITOR_MIN_INTERVAL
    assert m["scrapeOptions"]["formats"] == ["markdown"]
    assert m["status"] == "active" and m["currentHash"] is None
    assert m["id"] in monitor.MONITORS
    m2 = monitor._new_monitor("https://x.com", None, None, None)
    assert m2["intervalSeconds"] == monitor.MONITOR_DEFAULT_INTERVAL


def test_summary_excludes_snapshot_and_events():
    m = monitor._new_monitor("https://x.com", 100, None, None)
    s = monitor.summary(m)
    assert "snapshot" not in s and "events" not in s
    assert s["url"] == "https://x.com" and s["id"] == m["id"]


def test_concurrent_checks_serialize_single_event(monkeypatch):
    import asyncio
    from app import monitor

    m = monitor._new_monitor("https://x.com", 100, None, None)
    m["currentHash"] = monitor._hash("old")
    m["snapshot"] = "old"

    async def slow_scrape(url, formats, only_main, *, proxy=None, bypass_cache=False):
        await asyncio.sleep(0.05)
        return ({"markdown": "new", "metadata": {}}, {}, False)

    async def noop_save(mon):
        pass

    async def noop_resolve(mode):
        return None

    monkeypatch.setattr(monitor.scrape_mod, "scrape", slow_scrape)
    monkeypatch.setattr(monitor.store, "save_monitor", noop_save)
    monkeypatch.setattr(monitor.egress, "resolve_proxy", noop_resolve)

    async def run():
        await asyncio.gather(monitor.check_monitor(m), monitor.check_monitor(m))

    asyncio.run(run())
    assert m["changeCount"] == 1 and len(m["events"]) == 1   # lock serial hóa → 1 event
