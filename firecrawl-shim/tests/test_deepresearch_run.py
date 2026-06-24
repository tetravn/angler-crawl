import asyncio

from app import deepresearch as dr
from app import crawl_jobs


def _noop_persist(monkeypatch):
    async def fake(job):
        return None
    monkeypatch.setattr(crawl_jobs, "_persist", fake)


def _wire(monkeypatch, *, confidences, search_results, scrape_blocked=False):
    """confidences: list trả về tuần tự cho mỗi lần check_answers (giá trị gán cho mọi sub)."""
    _noop_persist(monkeypatch)
    calls = {"alt": 0, "synth": 0, "check": 0}

    async def fake_plan(query):
        return ([{"question": "q0", "search_query": "sq0", "answered": False,
                  "confidence": 0.0, "sources": []}], [])

    async def fake_check(subs, sources):
        calls["check"] += 1
        c = confidences[min(calls["check"] - 1, len(confidences) - 1)]
        for sq in subs:
            if c > sq["confidence"]:
                sq["confidence"] = c
                sq["answered"] = c >= dr.MIN_CONF
        return subs, []

    async def fake_alt(pending):
        calls["alt"] += 1
        return (["altq"], [])

    async def fake_search(q, *, limit=10, lang=None, categories=None):
        return search_results

    async def fake_scrape(url, formats, omc, **kw):
        meta = {"blocked": True} if scrape_blocked else {}
        return ({"markdown": f"md of {url}", "metadata": meta}, {}, False)

    async def fake_synth(query, sources):
        calls["synth"] += 1
        return "answer [1]"

    async def fake_proxy(e):
        return None

    async def fake_intent(q):
        return None

    monkeypatch.setattr(dr.query_intent, "analyze_intent", fake_intent)
    monkeypatch.setattr(dr, "plan_subqueries", fake_plan)
    monkeypatch.setattr(dr, "check_answers", fake_check)
    monkeypatch.setattr(dr, "alt_queries", fake_alt)
    monkeypatch.setattr(dr, "synthesize", fake_synth)
    monkeypatch.setattr(dr.clients, "searxng_search", fake_search)
    monkeypatch.setattr(dr.scrape_mod, "scrape", fake_scrape)
    monkeypatch.setattr(dr.egress_mod, "resolve_proxy", fake_proxy)
    return calls


def _params(**kw):
    p = {"query": "Q", "maxIterations": 3, "maxQueries": 4,
         "maxSourcesPerQuery": 5, "maxScrapePerIteration": 6, "egress": None}
    p.update(kw)
    return p


def test_run_early_termination(monkeypatch):
    calls = _wire(monkeypatch, confidences=[0.9],
                  search_results=[{"url": "http://a", "title": "A"}])
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params()))
    assert job["status"] == "completed"
    assert calls["check"] == 1            # dừng sau vòng đầu (confidence ≥ EARLY_TERM)
    assert calls["alt"] == 0              # không cần query thay thế
    assert job["data"]["iterations"] == 1
    assert job["data"]["answer"] == "answer [1]"
    assert job["data"]["sources"][0] == {"n": 1, "url": "http://a", "title": "A"}


def test_run_maxiterations_zero_clamp_ve_1(monkeypatch):
    """Regression A3: maxIterations=0 → clamp về 1 vòng (vẫn gather nguồn + synthesize, iterations≥1)."""
    calls = _wire(monkeypatch, confidences=[0.9],
                  search_results=[{"url": "http://a", "title": "A"}])
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params(maxIterations=0)))
    assert job["status"] == "completed"
    assert calls["check"] == 1              # chạy ≥1 vòng, không phải 0
    assert calls["synth"] == 1
    assert job["data"]["iterations"] == 1   # KHÔNG báo 0


def test_run_loops_to_maxiterations_and_uses_alt(monkeypatch):
    calls = _wire(monkeypatch, confidences=[0.0],   # luôn thấp → không bao giờ đủ
                  search_results=[{"url": "http://a", "title": "A"}])
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params(maxIterations=3)))
    assert job["status"] == "completed"
    assert calls["check"] == 3            # chạy đủ 3 vòng
    assert calls["alt"] == 2              # vòng 2,3 dùng alt_queries
    assert job["data"]["iterations"] == 3


def test_run_skips_blocked_sources(monkeypatch):
    _wire(monkeypatch, confidences=[0.9],
          search_results=[{"url": "http://a", "title": "A"}], scrape_blocked=True)
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params()))
    assert job["data"]["sources"] == []   # nguồn blocked bị bỏ


def test_run_filters_low_value_and_ranks(monkeypatch):
    """B: nguồn rác (social/chat/từ điển) bị loại; nguồn còn lại scrape theo thứ hạng chất lượng."""
    results = [
        {"url": "https://facebook.com/some/post", "title": "FB post"},
        {"url": "https://chatgpt.com/share/x", "title": "Chat"},
        {"url": "https://nature.com/articles/x", "title": "Nature"},
        {"url": "https://someblog.wordpress.com/p", "title": "Blog"},
    ]
    _wire(monkeypatch, confidences=[0.9], search_results=results)
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params()))
    urls = [s["url"] for s in job["data"]["sources"]]
    assert not any("facebook.com" in u or "chatgpt.com" in u for u in urls)  # rác bị loại
    assert "https://nature.com/articles/x" in urls                          # nguồn tốt giữ lại
    # nature (academic, prestigious) xếp trên blog cá nhân
    assert urls.index("https://nature.com/articles/x") < urls.index("https://someblog.wordpress.com/p")


def test_run_rerenders_js_for_numeric_query(monkeypatch):
    """#3: query cần số + trang scrape về không có số → scrape lại có chờ JS, dùng bản render."""
    _noop_persist(monkeypatch)
    calls = {"wait": 0}

    async def fake_plan(query):
        return ([{"question": "unemployment rate", "search_query": "sq", "answered": False,
                  "confidence": 0.0, "sources": []}], [])

    async def fake_check(subs, sources):
        for sq in subs:
            sq["confidence"] = 0.9
            sq["answered"] = True
        return subs, []

    async def fake_search(q, *, limit=10, lang=None, categories=None):
        return [{"url": "http://dash", "title": "Dash"}]

    async def fake_scrape(url, formats, omc, **kw):
        if kw.get("wait_for_ms"):
            calls["wait"] += 1
            return ({"markdown": "Unemployment rate was 38% in 2026", "metadata": {}}, {}, False)
        return ({"markdown": "navigation menu home about contact, no figures", "metadata": {}}, {}, False)

    captured = {}

    async def fake_synth(query, sources):
        captured["md"] = sources[0]["markdown"]                     # sources nội bộ còn giữ markdown
        return "ans [1]"

    async def fake_proxy(e):
        return None

    async def fake_intent(q):
        return None

    monkeypatch.setattr(dr.query_intent, "analyze_intent", fake_intent)
    monkeypatch.setattr(dr, "plan_subqueries", fake_plan)
    monkeypatch.setattr(dr, "check_answers", fake_check)
    monkeypatch.setattr(dr, "synthesize", fake_synth)
    monkeypatch.setattr(dr.clients, "searxng_search", fake_search)
    monkeypatch.setattr(dr.scrape_mod, "scrape", fake_scrape)
    monkeypatch.setattr(dr.egress_mod, "resolve_proxy", fake_proxy)
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params(query="What is the unemployment rate in 2026")))
    assert calls["wait"] == 1                                        # đã render JS đúng 1 lần
    assert captured["md"] == "Unemployment rate was 38% in 2026"     # dùng bản render


def test_run_orders_data_rich_sources_first_for_numeric(monkeypatch):
    """#1: query cần số → nguồn giàu số liệu được đưa lên đầu trước khi synthesize."""
    _noop_persist(monkeypatch)

    async def fake_plan(query):
        return ([{"question": "approval", "search_query": "sq", "answered": False,
                  "confidence": 0.0, "sources": []}], [])

    async def fake_check(subs, sources):
        for sq in subs:
            sq["confidence"] = 0.9
            sq["answered"] = True
        return subs, []

    async def fake_search(q, *, limit=10, lang=None, categories=None):
        return [{"url": "http://poor", "title": "Poor"}, {"url": "http://rich", "title": "Rich"}]

    async def fake_scrape(url, formats, omc, **kw):
        body = ("Approval was 40%, disapproval 59%, with 12 swing seats."
                if "rich" in url else "general background prose with no figures at all")
        return ({"markdown": body, "metadata": {}}, {}, False)

    captured = {}

    async def fake_synth(query, sources):
        captured["urls"] = [s["url"] for s in sources]
        return "ans [1]"

    async def fake_proxy(e):
        return None

    async def fake_intent(q):
        return None

    monkeypatch.setattr(dr.query_intent, "analyze_intent", fake_intent)
    monkeypatch.setattr(dr, "plan_subqueries", fake_plan)
    monkeypatch.setattr(dr, "check_answers", fake_check)
    monkeypatch.setattr(dr, "synthesize", fake_synth)
    monkeypatch.setattr(dr.clients, "searxng_search", fake_search)
    monkeypatch.setattr(dr.scrape_mod, "scrape", fake_scrape)
    monkeypatch.setattr(dr.egress_mod, "resolve_proxy", fake_proxy)
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params(query="What is Trump approval rating percentage")))
    assert captured["urls"][0] == "http://rich"      # nguồn giàu số liệu lên đầu


def test_run_no_rerender_for_nonnumeric_query(monkeypatch):
    """Query không cần số → không render JS dù trang thiếu số."""
    calls = _wire(monkeypatch, confidences=[0.9],
                  search_results=[{"url": "http://a", "title": "A"}])
    extra = {"wait": 0}
    base = dr.scrape_mod.scrape

    async def spy(url, formats, omc, **kw):
        if kw.get("wait_for_ms"):
            extra["wait"] += 1
        return await base(url, formats, omc, **kw)
    monkeypatch.setattr(dr.scrape_mod, "scrape", spy)
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params(query="who is the president of France")))
    assert extra["wait"] == 0


def test_run_synthesize_error_fails_job(monkeypatch):
    _wire(monkeypatch, confidences=[0.9],
          search_results=[{"url": "http://a", "title": "A"}])

    async def boom(query, sources):
        raise RuntimeError("synth down")
    monkeypatch.setattr(dr, "synthesize", boom)
    job = crawl_jobs.new_job()
    asyncio.run(dr._run(job["id"], _params()))
    assert job["status"] == "failed"
    assert "synth down" in job["error"]


def test_run_cancelled_skips_synth(monkeypatch):
    calls = _wire(monkeypatch, confidences=[0.0],
                  search_results=[{"url": "http://a", "title": "A"}])
    job = crawl_jobs.new_job()
    job["status"] = "cancelled"
    asyncio.run(dr._run(job["id"], _params()))
    assert calls["synth"] == 0            # thoát trước synthesize


def test_synthesize_raises_on_llm_error(monkeypatch):
    async def fake(messages, **kw):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(dr.clients, "llm_chat", fake)
    try:
        asyncio.run(dr.synthesize("Q", [{"url": "http://a", "title": "A", "markdown": "m"}]))
        assert False, "phải raise"
    except RuntimeError:
        pass


def test_create_job_returns_id(monkeypatch):
    _noop_persist(monkeypatch)
    ran = {}

    async def fake_run(job_id, params):
        ran["id"] = job_id
    monkeypatch.setattr(dr, "_run", fake_run)

    async def go():
        jid = dr.create_deep_research_job(_params())
        await asyncio.sleep(0)        # nhường để task _run chạy
        return jid

    jid = asyncio.run(go())
    assert jid in crawl_jobs.JOBS
    assert crawl_jobs.JOBS[jid]["data"] == {}
    assert ran["id"] == jid           # _run thực sự được spawn
