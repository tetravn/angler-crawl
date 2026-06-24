"""P3 — runner eval (in-process). Chạy: python -m app.eval.run [extraction|faithfulness|all].

Đo extraction accuracy (/extract) + synthesis faithfulness (/deep-research) bằng LLM-judge,
trên chính dữ liệu stack scrape. LLM-gated; 1 case lỗi không sập run.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from .. import clients, crawl_jobs, deepresearch, extract, scrape as scrape_mod
from . import grade

_DATA_DIR = Path(__file__).parent / "datasets"
_JUDGE_CONCURRENCY = 3


async def _llm_ok() -> bool:
    return await clients.llm_available()


async def _scrape_text(url: str) -> str | None:
    """Re-scrape 1 nguồn để lấy nội dung cho judge. blocked/lỗi → None."""
    try:
        data, _r, _ = await scrape_mod.scrape(url, ["markdown"], True)
        if (data.get("metadata") or {}).get("blocked"):
            return None
        return data.get("markdown")
    except Exception:
        return None


async def _run_extraction(cases: list[dict]) -> dict:
    rows: list[dict] = []
    tot_c = tot_n = 0
    for case in cases:
        try:
            job = crawl_jobs.new_job()
            job["data"] = {}
            await extract._run(job["id"], [case["url"]], case.get("prompt"), case.get("schema"))
            if job["status"] != "completed":
                raise RuntimeError(job.get("error") or "extract failed")
            nc, nn, wrong = await grade.judge_extraction(case["expected"], job["data"])
            tot_c += nc
            tot_n += nn
            rows.append({"url": case["url"], "correct": nc, "total": nn, "wrong": wrong})
        except Exception as exc:
            tot_n += len(case.get("expected") or {})   # judge lỗi → tính cả-sai, giữ mẫu số đầy đủ
            rows.append({"url": case.get("url"), "error": str(exc)})
    accuracy = (tot_c / tot_n) if tot_n else 0.0
    return {"accuracy": accuracy, "correct": tot_c, "total": tot_n, "cases": rows}


async def _run_faithfulness(cases: list[dict]) -> dict:
    rows: list[dict] = []
    tot_sup = tot_cited = tot_substantial = 0
    sem = asyncio.Semaphore(_JUDGE_CONCURRENCY)
    for case in cases:
        try:
            job = crawl_jobs.new_job()
            job["data"] = {}
            params = {"query": case["query"], "maxIterations": case.get("maxIterations", 2),
                      "maxQueries": 4, "maxSourcesPerQuery": 5, "maxScrapePerIteration": 6,
                      "egress": None}
            await deepresearch._run(job["id"], params)
            if job["status"] != "completed":
                raise RuntimeError(job.get("error") or "deep-research failed")
            answer = job["data"].get("answer") or ""
            by_n = {s["n"]: s["url"] for s in (job["data"].get("sources") or [])}
            claims = grade.split_claims(answer)
            cited = [c for c in claims if c["citations"]]
            uncited = [c["text"] for c in claims if not c["citations"]]
            text_cache: dict[str, str | None] = {}

            # Pre-populate cache for all cited URLs trước asyncio.gather để tránh race + dupe scrape.
            cited_urls = {by_n.get(n) for c in cited for n in c["citations"] if by_n.get(n)}
            for cited_url in cited_urls:
                text_cache[cited_url] = await _scrape_text(cited_url)

            async def judge(c: dict) -> bool:
                texts: list[str] = []
                for n in c["citations"]:
                    url = by_n.get(n)
                    if not url:
                        continue
                    if text_cache.get(url):
                        texts.append(text_cache[url])
                async with sem:
                    return await grade.judge_claim(c["text"], texts)

            verdicts = list(await asyncio.gather(*[judge(c) for c in cited])) if cited else []
            sup = sum(1 for v in verdicts if v)
            tot_sup += sup
            tot_cited += len(cited)
            # câu không trích nguồn tính là không-faithful → vào mẫu số
            tot_substantial += len(cited) + len(uncited)
            rows.append({"query": case["query"], "claims": len(claims), "cited": len(cited),
                         "supported": sup, "uncited": uncited,
                         "fabricated": [c["text"] for c, v in zip(cited, verdicts) if not v]})
        except Exception as exc:
            rows.append({"query": case.get("query"), "error": str(exc)})
    faith = (tot_sup / tot_substantial) if tot_substantial else 0.0
    return {"faithfulness": faith, "supported": tot_sup, "cited": tot_cited,
            "substantial": tot_substantial, "cases": rows}


def _load(name: str, override: str | None) -> list[dict]:
    path = Path(override) if override else (_DATA_DIR / f"{name}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _print_report(report: dict) -> None:
    if "extraction" in report:
        e = report["extraction"]
        print(f"[extraction] accuracy={e['accuracy']:.0%} ({e['correct']}/{e['total']})")
    if "faithfulness" in report:
        f = report["faithfulness"]
        n_uncited = f["substantial"] - f["cited"]
        print(f"[faithfulness] {f['faithfulness']:.0%} "
              f"(supported {f['supported']}/{f['substantial']} câu; "
              f"{n_uncited} câu không trích nguồn)")


async def main_async(args) -> int:
    if not await _llm_ok():
        print("Eval cần LLM — đặt LLM_BASE_URL/LLM_MODEL (LiteLLM).", file=sys.stderr)
        return 2
    report: dict = {}
    if args.mode in ("extraction", "all"):
        cases = _load("extraction", args.dataset if args.mode == "extraction" else None)
        report["extraction"] = await _run_extraction(cases[:args.limit] if args.limit else cases)
    if args.mode in ("faithfulness", "all"):
        cases = _load("faithfulness", args.dataset if args.mode == "faithfulness" else None)
        report["faithfulness"] = await _run_faithfulness(cases[:args.limit] if args.limit else cases)
    _print_report(report)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Angler eval harness")
    ap.add_argument("mode", choices=["extraction", "faithfulness", "all"], nargs="?", default="all")
    ap.add_argument("--dataset", help="đường dẫn dataset JSON (override built-in)")
    ap.add_argument("--limit", type=int, help="giới hạn số case")
    ap.add_argument("--out", help="ghi report JSON ra file")
    raise SystemExit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
