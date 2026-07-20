#!/usr/bin/env python3
"""Sinh litellm/config.yaml: primary Google Gemini free → fallback free OpenRouter → Ollama local.

App luôn gọi tên ảo `angler-fast`/`angler-smart` (OpenAI-compatible). LiteLLM route sang model
thật + tự switch khi lỗi/rate-limit; app không bao giờ đổi.

Lịch sử: trước đây primary là free OpenRouter. Từ 2026-07 OpenRouter siết free xuống ~50 req/ngày
cho tài khoản 0 credit (429 free-models-per-day) + gỡ vài model → không đủ tin cậy làm primary.
Nay: nếu có GEMINI_API_KEY thì Gemini (AI Studio free, hạn mức ngày cao) làm PRIMARY, free
OpenRouter tụt xuống fallback (vẫn thêm ~50 req/ngày), Ollama local là chốt chặn cuối.

Dùng:  GEMINI_API_KEY=... OPENROUTER_API_KEY=... python3 scripts/refresh-litellm-free.py
       (cả hai key đọc tự động từ .env ở gốc repo)
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
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


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

# Gemini AI Studio free — thứ tự ưu tiên. gemma-* hạn mức ngày CAO (~14k/ngày) → workhorse;
# gemini-*-flash-lite chất lượng hơn nhưng ít req/ngày. ⚠️ Tài khoản MỚI bị chặn model đời cũ
# (gemini-2.5-flash → 404 "no longer available to new users") nên chỉ để model đời mới ở đây.
PREF_GEMINI = ["gemma-4-31b-it", "gemma-4-26b-a4b-it", "gemini-3.1-flash-lite",
               "gemini-flash-lite-latest", "gemini-3.5-flash"]


def _http_json(url, key, body=None, timeout=20):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def list_free(key):
    """Trả id mọi free model OpenRouter (prompt=completion=0)."""
    d = _http_json(f"{OR_BASE}/models", key, timeout=30)["data"]
    out = []
    for m in d:
        p = m.get("pricing", {})
        if p.get("prompt") == "0" and p.get("completion") == "0":
            out.append(m["id"])
    return out


def ping(key, model_id):
    """OpenRouter: True nếu model trả content KHÁC RỖNG trong timeout (sống + không thinking-null)."""
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
    except urllib.error.HTTPError as e:
        # 429 = rate-limited (free-per-day cạn) chứ KHÔNG chết → giữ làm fallback,
        # sẽ dùng được khi quota reset hoặc khi primary Gemini hết lượt.
        return e.code == 429
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def gemini_alive(key, model):
    """Gemini: True nếu generateContent trả candidates (model tồn tại + gọi được).
    Budget token rộng vì Gemini là reasoning model (tiêu token 'thinking' trước khi ra text)."""
    try:
        body = {"contents": [{"parts": [{"text": "Return ONLY JSON {\"ok\":true}"}]}],
                "generationConfig": {"maxOutputTokens": 300}}
        req = urllib.request.Request(
            f"{GEMINI_BASE}/models/{model}:generateContent?key={key}",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        return bool(d.get("candidates"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return False


def gemini_pick(key):
    """Trả list 'gemini/<model>' sống theo thứ tự ưu tiên. [] nếu thiếu key / không con nào sống."""
    if not key:
        return []
    alive = []
    for m in PREF_GEMINI:
        ok = gemini_alive(key, m)
        print(f"  {'✓' if ok else '✗'} gemini/{m}")
        if ok:
            alive.append(f"gemini/{m}")
    return alive


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


def deployment(name, model, key_env):
    return (f"  - model_name: {name}\n"
            f"    litellm_params:\n"
            f"      model: {model}\n"
            f"      api_key: os.environ/{key_env}\n")


def build_config(smart_chain, fast_chain, gemini_models):
    """Sinh YAML. smart_chain/fast_chain = model_id OpenRouter đã xếp hạng.
    gemini_models = list 'gemini/<m>' sống ([] nếu không có → giữ hành vi cũ OR-primary)."""
    lines = [
        "# litellm/config.yaml — TỰ SINH bởi scripts/refresh-litellm-free.py (skip-worktree, local-only).",
        "# App gọi tên ảo angler-fast/angler-smart; primary Gemini free → fallback free OpenRouter → local.",
        "# ĐỪNG sửa tay — chạy lại script để cập nhật pool.",
        "model_list:",
    ]
    seen = {}  # or model_id -> model_name (slug), tránh trùng deployment

    if gemini_models:
        # Gemini làm primary; toàn bộ chuỗi OpenRouter tụt xuống fallback.
        g_smart = gemini_models[0]
        g_fast = gemini_models[1] if len(gemini_models) > 1 else gemini_models[0]
        lines.append(deployment("angler-smart", g_smart, "GEMINI_API_KEY").rstrip("\n"))
        lines.append(deployment("angler-fast", g_fast, "GEMINI_API_KEY").rstrip("\n"))
        smart_or, fast_or = smart_chain, fast_chain            # cả chuỗi là fallback
    else:
        # Không có Gemini → hành vi cũ: OpenRouter free làm primary.
        smart_best, fast_best = smart_chain[0], fast_chain[0]
        lines.append(deployment("angler-smart", f"openrouter/{smart_best}", "OPENROUTER_API_KEY").rstrip("\n"))
        lines.append(deployment("angler-fast", f"openrouter/{fast_best}", "OPENROUTER_API_KEY").rstrip("\n"))
        seen[smart_best] = "angler-smart"
        seen[fast_best] = "angler-fast"
        smart_or, fast_or = smart_chain[1:], fast_chain[1:]    # bỏ primary khỏi fallback

    # deployment cho mỗi free OpenRouter model trong chuỗi fallback (dùng chung 2 chuỗi)
    for mid in smart_chain + fast_chain:
        if mid not in seen:
            nm = slug(mid)
            seen[mid] = nm
            lines.append(deployment(nm, f"openrouter/{mid}", "OPENROUTER_API_KEY").rstrip("\n"))

    # local fallback (chốt chặn cuối)
    lines.append(f"  - model_name: angler-smart-local\n    litellm_params:\n      model: {OLLAMA_MODEL}\n      api_base: {OLLAMA_BASE}".rstrip("\n"))
    lines.append(f"  - model_name: angler-fast-local\n    litellm_params:\n      model: {OLLAMA_MODEL}\n      api_base: {OLLAMA_BASE}".rstrip("\n"))

    smart_fb = [seen[m] for m in smart_or] + ["angler-smart-local"]
    fast_fb = [seen[m] for m in fast_or] + ["angler-fast-local"]
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
    or_key = _env("OPENROUTER_API_KEY")
    gem_key = _env("GEMINI_API_KEY")
    if not or_key and not gem_key:
        sys.exit("Thiếu cả OPENROUTER_API_KEY lẫn GEMINI_API_KEY (env hoặc .env).")

    print("Ping Gemini (primary)…")
    gemini_models = gemini_pick(gem_key)
    if not gemini_models:
        print("  (không có Gemini sống — dùng OpenRouter free làm primary)")

    smart_chain, fast_chain = [], []
    if or_key:
        print("Dò catalog OpenRouter (fallback pool)…")
        free = list_free(or_key)
        cands = sorted({m for m in free if any(p in m for p in PREF_SMART + PREF_FAST)})
        print(f"  {len(free)} free model, {len(cands)} ứng viên → ping thử…")
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = dict(zip(cands, ex.map(lambda m: ping(or_key, m), cands)))
        survivors = [m for m in cands if results[m]]
        for m in cands:
            print(f"  {'✓' if results[m] else '✗'} {m}")
        smart_chain = rank(survivors, PREF_SMART)
        fast_chain = rank(survivors, PREF_FAST)

    if not gemini_models and (not smart_chain or not fast_chain):
        sys.exit("Không có primary nào (Gemini trống + OpenRouter free không con nào sống) — giữ config cũ.")

    if gemini_models:
        print(f"\n  angler-smart: {gemini_models[0]} → {' → '.join(smart_chain) or '(no OR)'} → local")
        print(f"  angler-fast : {gemini_models[1] if len(gemini_models) > 1 else gemini_models[0]} → {' → '.join(fast_chain) or '(no OR)'} → local")
    else:
        print(f"\n  angler-smart: {' → '.join(smart_chain)} → local")
        print(f"  angler-fast : {' → '.join(fast_chain)} → local")

    CONFIG_PATH.write_text(build_config(smart_chain, fast_chain, gemini_models))
    print(f"\nĐã ghi {CONFIG_PATH}")
    print("Chạy:  docker compose up -d litellm   # nạp config mới")


if __name__ == "__main__":
    main()
