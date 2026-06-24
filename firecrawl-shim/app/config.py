"""Cấu hình từ biến môi trường (có default cho docker-compose nội bộ)."""
import os

CRAWL4AI_URL = os.environ.get("CRAWL4AI_URL", "http://crawl4ai:11235").rstrip("/")
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/")
# SearXNG cho endpoint /v1/search.
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080").rstrip("/")

# LLM qua LiteLLM router (OpenAI-compatible). Mặc định trỏ vào service litellm nội bộ.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://litellm:4000/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "angler-smart")  # tên model-group trong litellm/config.yaml

# Timeout (giây) cho httpx gọi crawl4ai/flaresolverr — crawl có thể chậm.
HTTP_TIMEOUT = float(os.environ.get("SHIM_HTTP_TIMEOUT", "180"))
# maxTimeout (ms) FlareSolverr giải challenge Cloudflare. Site nặng (vd
# thuvienphapluat.vn) cần ~120s mới giải xong + render toàn văn; 60s là quá ngắn.
FLARESOLVERR_MAX_TIMEOUT = int(os.environ.get("FLARESOLVERR_MAX_TIMEOUT", "120000"))

# Số trang crawl song song trong 1 job (re-fetch CF).
CRAWL_CONCURRENCY = int(os.environ.get("CRAWL_CONCURRENCY", "3"))

# cache_mode truyền cho Crawl4AI. "ENABLED" = tận dụng cache của Crawl4AI để bớt
# request lặp ra site đích (đỡ bị chặn IP); "BYPASS" = luôn tải mới (tươi nhất).
CRAWL4AI_CACHE_MODE = os.environ.get("CRAWL4AI_CACHE_MODE", "ENABLED")

# Cache RAM của shim cho kết quả scrape (giảm hit lặp ra site đích + giảm độ trễ).
# TTL=0 để tắt. MAX = số entry tối đa (bounded RAM).
SCRAPE_CACHE_TTL = int(os.environ.get("SCRAPE_CACHE_TTL", "600"))
SCRAPE_CACHE_MAX = int(os.environ.get("SCRAPE_CACHE_MAX", "128"))

# Giãn nhịp tối thiểu giữa 2 request tới CÙNG một domain (ms) — lịch sự, đỡ bị
# rate-limit/block. 0 để tắt. Domain khác nhau KHÔNG ảnh hưởng lẫn nhau.
PER_DOMAIN_DELAY_MS = int(os.environ.get("PER_DOMAIN_DELAY_MS", "500"))

# Nhớ "domain này cần FlareSolverr" trong bao lâu (giây) để lần sau đi thẳng,
# bỏ cú thử Crawl4AI trực tiếp chắc-chắn-thất-bại. Tự hết hạn.
FS_DOMAIN_TTL = int(os.environ.get("FS_DOMAIN_TTL", "1800"))

# SQLite lưu job crawl (trên volume để sống sót qua restart).
JOBS_DB_PATH = os.environ.get("JOBS_DB_PATH", "/data/jobs.db")
# Job sống bao lâu (giây) trước khi bị dọn.
JOB_TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS", "86400"))

# Giới hạn an toàn khi đọc sitemap đệ quy.
SITEMAP_MAX_FILES = int(os.environ.get("SITEMAP_MAX_FILES", "50"))

# ─── P8 — Video transcript (caption-only) ───────────────────────────────
# Ngôn ngữ caption ưu tiên (thử theo thứ tự); ngoài list vẫn fallback bất kỳ caption nào có.
TRANSCRIPT_LANGS = [
    s.strip() for s in os.environ.get("TRANSCRIPT_LANGS", "en,vi").split(",") if s.strip()
]
# Host video bổ sung ngoài built-in (vd instance PeerTube), ngăn cách bởi dấu phẩy.
# Khớp theo chuỗi-con của netloc (vd "tube.example.org").
VIDEO_HOSTS = [
    s.strip().lower() for s in os.environ.get("VIDEO_HOSTS", "").split(",") if s.strip()
]
# Trần thời gian (giây) lấy transcript 1 video — chặn yt-dlp/youtube-transcript-api treo.
# Dùng cho cả socket_timeout của yt-dlp và asyncio.wait_for quanh mỗi backend.
TRANSCRIPT_TIMEOUT = int(os.environ.get("TRANSCRIPT_TIMEOUT", "60"))

# ─── P9 — Bảo vệ egress (VPN/proxy chọn theo request) ────────────────────
# HTTP proxy của gluetun (tunnel qua VPN), vd "http://gluetun:8888". Rỗng = chưa cấu hình.
VPN_PROXY_URL = os.environ.get("VPN_PROXY_URL", "").strip()
# Proxy residential, vd "http://user:pass@host:port". Rỗng = chưa cấu hình.
RESIDENTIAL_PROXY_URL = os.environ.get("RESIDENTIAL_PROXY_URL", "").strip()
# Egress mặc định khi request không nêu: "direct" | "vpn" | "proxy".
DEFAULT_EGRESS = os.environ.get("DEFAULT_EGRESS", "direct").strip() or "direct"

# ─── P5 — Chống bias nâng cao (LLM: dịch query đa ngôn ngữ + so chéo nguồn) ───
# Tên model-group trong litellm/config.yaml. fast = việc cơ học (dịch query);
# smart = suy luận khó (so chéo nguồn).
LLM_MODEL_FAST = os.environ.get("LLM_MODEL_FAST", "angler-fast")
LLM_MODEL_SMART = os.environ.get("LLM_MODEL_SMART", "angler-smart")
# Timeout (giây) RIÊNG cho đường LLM — model local có thể chậm; ai cần nhanh dùng cloud.
LLM_HTTP_TIMEOUT = float(os.environ.get("LLM_HTTP_TIMEOUT", "300"))
# So chéo nguồn (#9): số nguồn tối đa đưa vào LLM + số ký tự truncate mỗi nguồn.
CROSS_CHECK_MAX = int(os.environ.get("CROSS_CHECK_MAX", "8"))
CROSS_CHECK_CHARS = int(os.environ.get("CROSS_CHECK_CHARS", "4000"))
# Deep-research render JS (#3): câu hỏi cần số mà trang scrape về không có số (dashboard render
# bằng JS) → thử scrape lại với chờ JS. Tốn ~ms nên chỉ làm có điều kiện và giới hạn số lần/job.
DR_RENDER_WAIT_MS = int(os.environ.get("DR_RENDER_WAIT_MS", "4000"))
DR_MAX_RENDER = int(os.environ.get("DR_MAX_RENDER", "3"))
# Đoạn liên quan có ÍT HƠN ngần này con số thì coi là "nghèo số liệu" → đáng render JS (vd trang
# chỉ có một nhãn trục biểu đồ). 2 để một nhãn trục lẻ không che mất việc render.
DR_MIN_NUMERIC = int(os.environ.get("DR_MIN_NUMERIC", "2"))

# ─── /search: kéo thêm nguồn khoa học + xếp hạng qua lớp ranking chung ──
# Category SearXNG mà /search quét (mặc định thêm "science" để gồm arxiv/scholar/pubmed...).
SEARCH_CATEGORIES = os.environ.get("SEARCH_CATEGORIES", "general,science")

# ─── P7 — /monitor (theo dõi thay đổi trang) ─────────────────────────────
MONITOR_TICK = int(os.environ.get("MONITOR_TICK", "30"))                 # chu kỳ sweeper (giây)
MONITOR_MIN_INTERVAL = int(os.environ.get("MONITOR_MIN_INTERVAL", "60")) # interval tối thiểu/monitor
MONITOR_DEFAULT_INTERVAL = int(os.environ.get("MONITOR_DEFAULT_INTERVAL", "3600"))
MONITOR_MAX_EVENTS = int(os.environ.get("MONITOR_MAX_EVENTS", "50"))     # số change-event giữ lại

# ─── P10 — Fallback nguồn ngoài (public scrape services, opt-in) ─────────
# Provider mặc định khi request không nêu (rỗng = TẮT — chỉ dùng local).
DEFAULT_FALLBACK = os.environ.get("DEFAULT_FALLBACK", "").strip()
# Jina Reader: free, không cần key (key tùy chọn để tăng rate-limit).
JINA_BASE_URL = os.environ.get("JINA_BASE_URL", "https://r.jina.ai").rstrip("/")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "").strip()
# Firecrawl cloud: cần key.
FIRECRAWL_CLOUD_URL = os.environ.get("FIRECRAWL_CLOUD_URL", "https://api.firecrawl.dev").rstrip("/")
FIRECRAWL_CLOUD_API_KEY = os.environ.get("FIRECRAWL_CLOUD_API_KEY", "").strip()

# ─── P6 — /agent (browser agent tự lái) ─────────────────────────────
AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "15"))       # trần số bước (research: 8 quá thấp)
AGENT_PAGE_CHARS = int(os.environ.get("AGENT_PAGE_CHARS", "4000"))   # truncate PAGE TEXT trong observation
AGENT_MAX_ELEMENTS = int(os.environ.get("AGENT_MAX_ELEMENTS", "60")) # cap số phần tử tương tác liệt kê
AGENT_STUCK_LIMIT = int(os.environ.get("AGENT_STUCK_LIMIT", "3"))    # số bước lặp giống nhau → coi là kẹt

# ─── Streaming LLM + abort guards ───────────────────────────────────────
LLM_STREAM = os.environ.get("LLM_STREAM", "1") not in ("0", "false", "")
# Gửi response_format=json_object (Ollama format:json) khi json_mode? Mặc định bật. ĐẶT =0 cho model
# "thinking" (vd Qwen3 reasoning): format:json ép constrained-decoding làm content RỖNG — thay vào đó
# dựa vào prompt (caller đã yêu cầu JSON) + model trả JSON sạch (thinking đi field reasoning riêng).
LLM_JSON_NATIVE = os.environ.get("LLM_JSON_NATIVE", "1") not in ("0", "false", "")
STREAM_STALL_TIMEOUT = float(os.environ.get("STREAM_STALL_TIMEOUT", "30"))        # giây, gap token tối đa
STREAM_SLOW_SEC_PER_WORD = float(os.environ.get("STREAM_SLOW_SEC_PER_WORD", "5")) # quá chậm → cắt
STREAM_MAX_WORDS_NO_PUNCT = int(os.environ.get("STREAM_MAX_WORDS_NO_PUNCT", "200"))
STREAM_MAX_CHARS_NO_SPACE = int(os.environ.get("STREAM_MAX_CHARS_NO_SPACE", "2000"))
STREAM_MAX_REPEAT = int(os.environ.get("STREAM_MAX_REPEAT", "12"))
STREAM_WARMUP_WORDS = int(os.environ.get("STREAM_WARMUP_WORDS", "15"))

# ─── Ranking (dùng chung /search và /research) ──────────────────────────
# Trọng số từng tín hiệu trong "quality" (tổng có trọng số). Đặt 0 để tắt tín hiệu.
RANK_W_TRUST = float(os.environ.get("RANK_W_TRUST", "1.0"))
RANK_W_RECENCY = float(os.environ.get("RANK_W_RECENCY", "0.7"))
RANK_W_ENGINE = float(os.environ.get("RANK_W_ENGINE", "0.5"))
RANK_W_INSTITUTIONAL = float(os.environ.get("RANK_W_INSTITUTIONAL", "0.5"))
RANK_W_GLOBAL_LOCAL = float(os.environ.get("RANK_W_GLOBAL_LOCAL", "0.4"))
RANK_W_LANGUAGE = float(os.environ.get("RANK_W_LANGUAGE", "0.6"))
RANK_W_GEO = float(os.environ.get("RANK_W_GEO", "0.4"))
# Cân giữa relevance gốc (SearXNG) và quality khi gộp điểm point-wise.
RANK_RELEVANCE_WEIGHT = float(os.environ.get("RANK_RELEVANCE_WEIGHT", "1.0"))
# MMR: lambda càng nhỏ càng ép đa dạng. Cap số kết quả mỗi domain.
RANK_MMR_LAMBDA = float(os.environ.get("RANK_MMR_LAMBDA", "0.7"))
RANK_DOMAIN_CAP = int(os.environ.get("RANK_DOMAIN_CAP", "3"))

# ─── Query-intent: phân tích ý định truy vấn (ngôn ngữ/địa lý các bên) ────
# Dùng LLM phân tích intent, fail-open về heuristic.
INTENT_USE_LLM = os.environ.get("INTENT_USE_LLM", "1") not in ("0", "false", "")
INTENT_TIMEOUT = float(os.environ.get("INTENT_TIMEOUT", "8"))

# ─── Activity log (ghi mọi hoạt động xuống SQLite + stdout) ───────────────
# Bật ghi event xuống bảng `events` (cùng /data/jobs.db). =0 để chỉ ra stdout.
LOG_DB_ENABLED = os.environ.get("LOG_DB_ENABLED", "1") not in ("0", "false", "")
# Ngưỡng level để GHI DB (stdout vẫn nhận đủ theo level riêng của logger).
LOG_DB_LEVEL = os.environ.get("LOG_DB_LEVEL", "INFO").upper()
# Giữ event bao lâu (giây) trước khi dọn. Mặc định 7 ngày.
LOG_TTL_SECONDS = int(os.environ.get("LOG_TTL_SECONDS", "604800"))
# Cắt JSON `fields` mỗi event cho gọn (tránh blob khổng lồ).
LOG_FIELDS_MAX_CHARS = int(os.environ.get("LOG_FIELDS_MAX_CHARS", "4000"))
# Ghi DB theo lô: flush khi đủ N event HOẶC mỗi LOG_BATCH_FLUSH_SEC giây.
LOG_BATCH_FLUSH_N = int(os.environ.get("LOG_BATCH_FLUSH_N", "50"))
LOG_BATCH_FLUSH_SEC = float(os.environ.get("LOG_BATCH_FLUSH_SEC", "1.0"))
