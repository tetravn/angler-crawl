#!/usr/bin/env python3
"""Tự khám phá free model OpenRouter còn sống → sinh litellm/config.yaml (chuỗi fallback + local).

App luôn gọi tên ảo `angler-fast`/`angler-smart` (OpenAI-compatible). Script này dò catalog
OpenRouter, lọc model FREE (pricing=0), ping thử để loại model chết / thinking-trả-rỗng, xếp hạng,
rồi viết config với chuỗi fallback: free tốt → free kém → Ollama local. LiteLLM tự switch khi
một con lỗi/rate-limit; app không bao giờ đổi.

Dùng:  OPENROUTER_API_KEY=... python3 scripts/refresh-litellm-free.py
       (key cũng đọc tự động từ .env ở gốc repo)
Sau đó: docker compose up -d litellm   # nạp config mới
"""
import json
import os
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "litellm" / "config.yaml"
OR_BASE = "https://openrouter.ai/api/v1"


def _env(name, default=""):
    """Đọc biến từ env, fallback sang .env ở gốc repo (giữ giá trị thật local-only)."""
    v = os.environ.get(name, "").strip()
    if not v:
        envf = ROOT / ".env"
        if envf.exists():
            for line in envf.read_text().splitlines():
                if line.startswith(f"{name}="):
                    v = line.split("=", 1)[1].strip()
                    break
    return v or default


# Default generic (an toàn commit); giá trị thật lấy từ .env qua _env.
OLLAMA_BASE = _env("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = _env("OLLAMA_FALLBACK_MODEL", "ollama/qwen3.5:9b")

# Ưu tiên (instruct/JSON-friendly, NON-thinking). Chỉ ping model khớp các pattern này
# → bỏ qua audio/vision/safety/thinking. Thứ tự = mức ưu tiên.
PREF_SMART = ["gpt-oss-120b", "llama-3.3-70b", "hermes-3-llama-3.1-405b",
              "nemotron-3-super-120b", "nemotron-3-ultra", "qwen3-next-80b",
              "gemma-4-31b", "gpt-oss-20b", "gemma-4-26b", "nemotron-nano-30b"]
PREF_FAST = ["gpt-oss-20b", "gemma-4-31b", "gemma-4-26b", "nemotron-nano-9b",
             "nemotron-nano-12b", "llama-3.2-3b", "gpt-oss-120b"]


def _key() -> str:
    k = _env("OPENROUTER_API_KEY")
    if not k:
        sys.exit("Thiếu OPENROUTER_API_KEY (env hoặc .env).")
    return k


def _http_json(url, key, body=None, timeout=20):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def list_free(key):
    """Trả id mọi free model (prompt=completion=0)."""
    d = _http_json(f"{OR_BASE}/models", key, timeout=30)["data"]
    out = []
    for m in d:
        p = m.get("pricing", {})
        if p.get("prompt") == "0" and p.get("completion") == "0":
            out.append(m["id"])
    return out


def ping(key, model_id):
    """True nếu model trả content KHÁC RỖNG trong timeout (sống + không phải thinking-null)."""
    try:
        d = _http_json(
            f"{OR_BASE}/chat/completions", key,
            body={"model": model_id,
                  "messages": [{"role": "user", "content": "Return ONLY JSON {\"ok\":true}"}],
                  "max_tokens": 30},
            timeout=25,
        )
        if "error" in d:
            return False
        c = (d.get("choices") or [{}])[0].get("message", {}).get("content")
        return bool(c and c.strip())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return False


def rank(survivors, pref):
    """Xếp survivors theo thứ tự ưu tiên (khớp pattern sớm hơn = tốt hơn)."""
    def score(mid):
        for i, pat in enumerate(pref):
            if pat in mid:
                return i
        return len(pref)
    return sorted([s for s in survivors if score(s) < len(pref)], key=score)


def slug(model_id):
    return "or-" + model_id.replace("openrouter/", "").replace("/", "-").replace(":", "-").replace(".", "-")


def build_config(smart_chain, fast_chain):
    """Sinh YAML. smart_chain/fast_chain = list model_id OpenRouter đã xếp hạng."""
    seen = {}  # model_id -> model_name (slug), tránh trùng deployment
    lines = [
        "# litellm/config.yaml — TỰ SINH bởi scripts/refresh-litellm-free.py (skip-worktree, local-only).",
        "# App gọi tên ảo angler-fast/angler-smart; litellm route sang free model thật + fallback local,",
        "# trả response dán nhãn đúng tên ảo. ĐỪNG sửa tay — chạy lại script để cập nhật pool.",
        "model_list:",
    ]

    def deployment(name, or_id):
        return (f"  - model_name: {name}\n"
                f"    litellm_params:\n"
                f"      model: openrouter/{or_id}\n"
                f"      api_key: os.environ/OPENROUTER_API_KEY\n")

    # primary alias
    smart_best, fast_best = smart_chain[0], fast_chain[0]
    lines.append(deployment("angler-smart", smart_best).rstrip("\n"))
    lines.append(deployment("angler-fast", fast_best).rstrip("\n"))
    seen[smart_best] = "angler-smart"
    seen[fast_best] = "angler-fast"

    # deployment cho mỗi free model còn lại (dùng chung cho cả 2 chuỗi fallback)
    for mid in smart_chain + fast_chain:
        if mid not in seen:
            nm = slug(mid)
            seen[mid] = nm
            lines.append(deployment(nm, mid).rstrip("\n"))

    # local fallback
    lines.append(f"  - model_name: angler-smart-local\n    litellm_params:\n      model: {OLLAMA_MODEL}\n      api_base: {OLLAMA_BASE}".rstrip("\n"))
    lines.append(f"  - model_name: angler-fast-local\n    litellm_params:\n      model: {OLLAMA_MODEL}\n      api_base: {OLLAMA_BASE}".rstrip("\n"))

    smart_fb = [seen[m] for m in smart_chain[1:]] + ["angler-smart-local"]
    fast_fb = [seen[m] for m in fast_chain[1:]] + ["angler-fast-local"]
    fb = [{"angler-smart": smart_fb}, {"angler-fast": fast_fb}]

    lines += [
        "",
        "router_settings:",
        "  num_retries: 2",
        "  allowed_fails: 3",
        "  cooldown_time: 30",
        "  timeout: 25            # cắt con treo → kích hoạt fallback (free model hay hang)",
        f"  fallbacks: {json.dumps(fb)}",
        "",
        "litellm_settings:",
        "  drop_params: true",
        "",
    ]
    return "\n".join(lines)


def main():
    key = _key()
    print("Dò catalog OpenRouter…")
    free = list_free(key)
    cands = sorted({m for m in free if any(p in m for p in PREF_SMART + PREF_FAST)})
    print(f"  {len(free)} free model, {len(cands)} ứng viên (instruct/non-thinking) → ping thử…")

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(zip(cands, ex.map(lambda m: ping(key, m), cands)))
    survivors = [m for m in cands if results[m]]
    for m in cands:
        print(f"  {'✓' if results[m] else '✗'} {m}")
    if not survivors:
        sys.exit("Không free model nào sống — giữ config cũ.")

    smart_chain = rank(survivors, PREF_SMART)
    fast_chain = rank(survivors, PREF_FAST)
    if not smart_chain or not fast_chain:
        sys.exit("Survivors không khớp ưu tiên — kiểm tra PREF_*.")

    print(f"\n  angler-smart: {' → '.join(smart_chain)} → local")
    print(f"  angler-fast : {' → '.join(fast_chain)} → local")

    CONFIG_PATH.write_text(build_config(smart_chain, fast_chain))
    print(f"\nĐã ghi {CONFIG_PATH}")
    print("Chạy:  docker compose up -d litellm   # nạp config mới")


if __name__ == "__main__":
    main()
