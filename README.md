# Angler

> **Cổng nghiên cứu search + crawl, chạy local — *"thả query, kéo nguồn về."***
> Nói "tiếng Firecrawl" để AI agent cắm-là-chạy, nhưng bản sắc là một cổng **search +
> crawl hướng nghiên cứu, chống bias — **local hay cloud là lựa chọn của bạn**.

Như **cá câu (anglerfish)** thả mồi phát sáng kéo con mồi lên từ biển sâu — **Angler**
nhận một truy vấn và kéo về **nội dung sạch** từ khắp web, kể cả các trang núp sau
Cloudflare. Tất cả service nằm sau một gateway Caddy, chỉ mở đúng một port (mặc định `17300`,
đổi được qua `ANGLER_PORT`). Mặc định không cần API key và không giới hạn tần suất, vì chạy
local cho một người dùng. Khi cần mở ra ngoài thì bật cổng API key, xem
[Cấu hình qua `.env`](#cấu-hình-qua-env) và [Ghi chú thiết kế](#ghi-chú-thiết-kế).

> Dự án tên **Angler** (docker compose project `angler`). Tên service bên trong
> (`searxng`, `crawl4ai`, `flaresolverr`, `firecrawl-shim`, `gateway`) giữ nguyên vì
> chúng mô tả vai trò kỹ thuật.

**Tài liệu:** [Giới thiệu sản phẩm](docs/GIOI-THIEU-SAN-PHAM.md) (pitch, use-case, ROI),
[Thiết kế kỹ thuật](docs/THIET-KE-KY-THUAT.md) (kiến trúc, bất biến, thiết kế từng tính năng),
[Roadmap](docs/ROADMAP.md) (định hướng),
[Chọn model LLM](docs/CHON-MODEL-LLM.md) (tham khảo chọn model + eval). Tham chiếu API: phần dưới + Swagger tại `/docs`.

**Vì sao dùng Angler thay vì Firecrawl cloud:**
- **Local hay cloud — bạn chọn** (không thiên bên nào): có hardware và cần riêng tư thì **full local**,
  không rời máy; không có hardware thì dùng **cloud** (free-tier/dịch vụ) vẫn chơi đầy đủ. Chọn theo từng
  request (egress VPN/proxy, fallback nguồn, LLM); stack **báo rõ giới hạn** mỗi lựa chọn (xem bảng dưới).
- **CF-bypass tích hợp sẵn** (FlareSolverr) + phát hiện **stub/blocked** (chống "bias do công cụ").
- **`/research` đa nguồn chống bias** — Firecrawl đã khai tử Deep Research API của họ.
- **Tiết kiệm & bảo vệ IP**: cache kết quả, giãn nhịp theo domain, nhớ "domain cần CF",
  bỏ giải-CF vô ích với trang paywall, phát hiện trang chặn **đa ngôn ngữ** (xem §4.1).
- **Search (SearXNG) + crawl gộp 1 port**; đã có **video ra transcript**, **/monitor**, **egress VPN/proxy**.

**Local hay cloud — chọn sao? (biết rõ đánh đổi trước khi chọn)**

| | Local | Cloud (opt-in) |
|---|---|---|
| **Riêng tư** | dữ liệu **không rời máy** | chia sẻ bên thứ ba (free tier hay log/train) |
| **Hardware** | cần GPU/VRAM (cho LLM) | **không cần** — máy yếu vẫn chơi đầy đủ |
| **Năng lực / tốc độ** | tuỳ máy; model lớn khó | nhanh, model mạnh sẵn |
| **Chi phí / quota** | miễn phí, không quota | free-tier có rate-limit; bản trả phí tốn tiền |
| **Phụ thuộc** | tự chủ, chạy offline được | cần mạng + dịch vụ sống |

> **Chọn theo từng request** (egress, fallback nguồn, LLM), hoặc đặt mặc định qua env. Stack
> **báo rõ khi vướng giới hạn** (chưa cấu hình / hết quota / nguồn bị chặn) — không im lặng degrade.

> Tương thích là *cổng vào*, không phải superset tuyệt đối — vài chỗ Firecrawl cloud
> còn mạnh hơn (`/extract` cần LLM, `/map` phủ kém hơn). Xem **Ghi chú thiết kế** cuối file.

```
                         ┌──────────────────────────────────────────────┐
   AI agent ──:17300──►  │  gateway (Caddy)  — reverse proxy theo path   │
                         └───┬───────────┬───────────┬───────────┬──────┘
                             │           │           │           │
                       /searxng/*   /crawl4ai/*  /flaresolverr/* /v1,/v2,/firecrawl
                             ▼           ▼           ▼           ▼
                          searxng    crawl4ai   flaresolverr  firecrawl-shim
                          (8080)     (11235)      (8191)         (8000)
                                                                  │
                                                   gọi nội bộ ──►  crawl4ai + flaresolverr
```

| Service | Vai trò | Nội bộ | Truy cập qua gateway |
|---|---|---|---|
| **searxng** | Metasearch (JSON API) | `8080` | `/searxng/...` |
| **crawl4ai** | Crawl/scrape ra markdown | `11235` | `/crawl4ai/...` |
| **flaresolverr** | Bypass Cloudflare | `8191` | `/flaresolverr/...` |
| **firecrawl-shim** | API **tương thích Firecrawl**, dịch sang Crawl4AI (+FlareSolverr) | `8000` | `/v1/*`, `/v2/*` (và `/firecrawl/*`) |
| **gateway** | Caddy reverse proxy | `80` | publish `17300` (đổi qua `ANGLER_PORT`) |

---

## Bắt đầu

**Yêu cầu:** Docker + Docker Compose. Không cần gì khác (không API key, không LLM cho
phần lõi).

### 1. Dựng stack
```bash
docker compose up -d          # dựng toàn bộ 5 service
docker compose ps             # kiểm tra (chờ tất cả "healthy")
```

### 2. Kiểm tra hoạt động
```bash
# Search (SearXNG):
curl "http://localhost:17300/searxng/search?q=docker&format=json"

# Scrape qua API tương thích Firecrawl:
curl -X POST "http://localhost:17300/v1/scrape" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","formats":["markdown"]}'
```
Thấy JSON trả về là chạy được. Trỏ AI agent vào `http://localhost:17300` (xem §4).

### Khám phá API (tự mô tả)
Stack tự liệt kê được "có API gì, gọi thế nào" — cho cả người lẫn agent:

| Đường dẫn | Cho ai | Là gì |
|---|---|---|
| `GET /` (trình duyệt) | người | Landing page liệt kê service + link tài liệu |
| [`/docs`](http://localhost:17300/docs) | người | **Swagger UI** — bấm-thử mọi endpoint |
| [`/redoc`](http://localhost:17300/redoc) | người | Bản tài liệu đọc đẹp |
| [`/openapi.json`](http://localhost:17300/openapi.json) | agent/SDK | Đặc tả máy-đọc đầy đủ (schema mọi endpoint) |
| [`/llms.txt`](http://localhost:17300/llms.txt) | LLM agent | Mô tả ngắn dạng markdown |
| `GET /` + `Accept: application/json` | agent | Trả [`/manifest.json`](http://localhost:17300/manifest.json) — mục lục máy-đọc toàn stack |

```bash
# Agent tự khám phá: vào gốc, xin JSON thì nhận manifest chỉ tới openapi của từng service
curl -H "Accept: application/json" "http://localhost:17300/"
```

Mỗi service backend cũng tự-mô-tả riêng (manifest trỏ tới hết):
- **Crawl4AI**: [`/crawl4ai/docs`](http://localhost:17300/crawl4ai/docs) (Swagger), `/crawl4ai/redoc`, `/crawl4ai/openapi.json`
- **SearXNG**: [`/searxng/`](http://localhost:17300/searxng/) (UI), `/searxng/search?...&format=json`, `/searxng/opensearch.xml` — *không có OpenAPI*
- **FlareSolverr**: không có OpenAPI — mọi lệnh là `POST /flaresolverr/v1` với body `{cmd: ...}`

### Vận hành thường ngày
```bash
docker compose logs -f firecrawl-shim   # xem log 1 service
docker compose down                     # dừng (GIỮ volume: job + cache)
docker compose down -v                  # dừng + XOÁ volume (mất job SQLite + cache searxng)
```

### Cấu hình qua `.env`

Mọi tuỳ chọn gom trong một file `.env` ở thư mục gốc. Docker Compose tự đọc file này và thay các
biến `${VAR}` trong compose. Tạo file từ mẫu rồi điền phần cần dùng:

```bash
cp .env.example .env        # điền phần cần, để trống phần không dùng
```

File mẫu chia sẵn ba nhóm: Gateway (port và API key), LLM (P1) và VPN (P9). Hai biến hay dùng nhất:

| Biến | Mặc định | Tác dụng |
|---|---|---|
| `ANGLER_PORT` | `17300` | port duy nhất mở ra ngoài; đổi khi trùng cổng khác |
| `ANGLER_API_KEY` | (trống) | đặt giá trị để bật cổng API key cho cả stack; để trống là mở, chỉ dùng trong mạng local |

Riêng `searxng/.env` là file của riêng container searxng (cơ chế `env_file:`), chỉ chứa
`SEARXNG_VERSION` và `SEARXNG_PORT`, không phải chỗ để secret. Không gộp nó vào `.env` gốc.

#### Đổi port

Sửa `ANGLER_PORT` trong `.env` rồi chạy `docker compose up -d gateway`. Phải dùng `up` chứ không
phải `restart`, vì port chỉ gắn vào lúc tạo lại container.

#### Bật API key

Đặt `ANGLER_API_KEY` rồi nạp lại gateway:

```bash
docker compose up -d gateway && docker compose restart gateway
```

Sinh một key ngẫu nhiên cho tiện: `echo "angler_$(openssl rand -hex 24)"`.

Khi đã bật, request thiếu key hoặc sai key đều nhận `401` kèm thông điệp báo cần key, kể cả các
đường dẫn tài liệu như `/docs`, `/openapi.json`, `/` và `/manifest.json`. Nghĩa là agent không có
key thì cũng không tự dò ra được API. Request hợp lệ gửi kèm header `Authorization: Bearer <key>`
thì dùng bình thường.

```bash
# Với Firecrawl SDK chỉ cần đặt FIRECRAWL_API_KEY=<key>, SDK tự gửi header Bearer.
curl -H "Authorization: Bearer <key>" "http://localhost:17300/v1/search" ...
```

### Hai quy tắc khi sửa cấu hình
| Sửa gì | Phải làm | Vì sao |
|---|---|---|
| `gateway/Caddyfile` | `docker compose restart gateway` | caddy reload qua exec **không** áp dụng đáng tin cậy ở đây |
| code Python trong `firecrawl-shim/` | `docker compose up -d --build firecrawl-shim` | code được `COPY` vào image, **không** bind-mount |

> Không có test suite / linter — **verify bằng `curl`** vào gateway đang chạy (như §2).

---

## 1. SearXNG — Search

`GET /searxng/search`

```bash
curl "http://localhost:17300/searxng/search?q=docker&format=json"
```

| Tham số | Mô tả |
|---|---|
| `q` | từ khoá (bắt buộc) |
| `format` | `json` hoặc `html` |
| `categories`, `engines`, `pageno`, `language`, `time_range` | tuỳ chọn |

Khác: `GET /searxng/healthz` (health), `GET /searxng/config`.

---

## 2. Crawl4AI — Crawl (API gốc)

`POST /crawl4ai/crawl`

```bash
curl -X POST "http://localhost:17300/crawl4ai/crawl" \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://example.com"]}'
```

Trả `{"success":true,"results":[{markdown,html,cleaned_html,links,metadata,status_code,...}]}`.
Hỗ trợ `raw://<html>` thay cho URL, và `crawler_config`/`browser_config` dạng
`{"type":"...","params":{...}}`. Health: `GET /crawl4ai/health`.

---

## 3. FlareSolverr — Bypass Cloudflare

`POST /flaresolverr/v1`

```bash
curl -X POST "http://localhost:17300/flaresolverr/v1" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"request.get","url":"https://nowsecure.nl","maxTimeout":60000}'
```

Trả `{"status":"ok","solution":{response:<HTML>,status,cookies,userAgent,...}}`.

---

## 4. Firecrawl-shim — API tương thích Firecrawl

Cho agent **chỉ biết Firecrawl** dùng được stack mà không sửa code. Bên trong:
dịch sang Crawl4AI, **tự bypass Cloudflare qua FlareSolverr** (kể cả khi Crawl4AI
lỗi hẳn vì challenge), và `search` đấu sang SearXNG.

Phủ gần trọn API Firecrawl: **scrape, search, map, crawl, batch/scrape, extract**,
cộng thêm **`/v1/research`** (gom nguồn đa-trục, chống bias) và **`/v1/transcript`**
(video ra caption, caption-only) — phần mở rộng cho nghiên cứu.

### Cấu hình agent
```
FIRECRAWL_API_URL = http://localhost:17300      # trỏ vào GỐC gateway
FIRECRAWL_API_KEY = bất kỳ (bị bỏ qua)
```
```python
from firecrawl import FirecrawlApp
app = FirecrawlApp(api_url="http://localhost:17300", api_key="dummy")
app.scrape_url("https://example.com", formats=["markdown"])
app.map_url("https://example.com")
app.crawl_url("https://example.com", limit=10)
```
> Dùng **root** `/v1`,`/v2` (không phải `/firecrawl/v1`) vì SDK Firecrawl build
> absolute path và drop base path. `/firecrawl/*` chỉ để gọi tay/debug.

### 4.1 `POST /v1/scrape`
```bash
curl -X POST "http://localhost:17300/v1/scrape" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","formats":["markdown","html","links"]}'
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `url` | — | bắt buộc |
| `formats` | `["markdown"]` | `markdown`,`html`,`rawHtml`,`links`,`screenshot` |
| `onlyMainContent` | `true` | lọc nav/header/footer (PruningContentFilter) |
| `waitFor` | `0` | delay (ms) trước khi lấy HTML |
| `timeout` | `30000` | timeout trang (ms) |
| `headers` | — | custom request headers |
| `egress` | `null` | chọn đường ra: `"direct"` / `"vpn"` / `"proxy"` — xem §4 bảng env; chưa cấu hình thì **fail-open** (đi direct, không lỗi) |
| `fallback` | `null` | **opt-in** escalate sang dịch vụ public khi local bó tay (chặn/stub): `"jina"` (free) hoặc `"firecrawl"` (cần key). Nội dung gắn `metadata.source`. Mặc định tắt (chỉ dùng local) |

Response:
```json
{ "success": true, "data": {
  "markdown": "...", "html": "...", "links": ["..."],
  "metadata": { "title":"...", "description":"...", "sourceURL":"...",
                "url":"...", "statusCode":200 } } }
```
**Chuỗi fallback (trong suốt với agent):** thử Crawl4AI trực tiếp; nếu Cloudflare chặn
hoặc Crawl4AI lỗi thì giải qua FlareSolverr rồi render markdown; nếu vẫn **stub** (200
nhưng rỗng) thì gắn `data.metadata.blocked = true` để nguồn không âm thầm bị tính là
"có nội dung".

**Tối ưu & bảo vệ IP** (đều tự động):
- **Stub do paywall/login** thì gắn `blocked` luôn, **bỏ qua FlareSolverr** (giải-CF không
  trả phí/đăng nhập hộ nên vô ích). Stub do **anti-bot** mới thử FlareSolverr.
- Phát hiện Cloudflare / anti-bot / paywall **đa ngôn ngữ** (vi, fr, de, es, pt…).
- **Cache RAM** kết quả (mặc định 600s) + **nhớ "domain cần FlareSolverr"** để lần sau đi
  thẳng + **giãn nhịp per-domain**, giảm hit lặp ra site đích, đỡ bị chặn IP.
  (Tinh chỉnh qua biến môi trường — xem bảng cuối §4.)

### 4.2 `POST /v1/map`
```bash
curl -X POST "http://localhost:17300/v1/map" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","limit":100}'
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `url` | — | bắt buộc |
| `limit` | `0` (không giới hạn) | số link tối đa |
| `includeSubdomains` | `false` | gồm subdomain |
| `search` | — | lọc link chứa chuỗi |

Nguồn link: link trên trang seed **+ sitemap đệ quy** (robots.txt tới sitemap index
lồng nhau rồi `.xml.gz`). Response: `{"success":true,"links":["..."]}`.

### 4.3 `POST /v1/crawl` (async) + `GET /v1/crawl/{id}`
```bash
# Bắt đầu job
curl -X POST "http://localhost:17300/v1/crawl" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","limit":10,"maxDepth":2}'
# trả về {"success":true,"id":"<job_id>","url":".../v1/crawl/<job_id>"}

# Poll
curl "http://localhost:17300/v1/crawl/<job_id>"
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `url` | — | seed (bắt buộc) |
| `limit` | `10` | số trang tối đa |
| `maxDepth` | `2` | độ sâu BFS |
| `includePaths`/`excludePaths` | — | regex lọc path |
| `allowExternalLinks` | `false` | cho ra ngoài domain |
| `scrapeOptions` | — | `{formats, onlyMainContent}` cho mỗi trang |
| `egress` | `null` | `"vpn"`/`"proxy"`/`"direct"` — áp dụng cho toàn bộ scrape trong job |

Status response:
```json
{ "success": true, "status": "completed",   // scraping|completed|failed
  "total": 10, "completed": 10, "creditsUsed": 10,
  "expiresAt": "...", "data": [ { markdown, metadata, ... } ] }
```
Dùng **deep-crawl native** của Crawl4AI (nhanh, discovery tốt); trang bị Cloudflare
được re-fetch qua FlareSolverr. Job lưu **SQLite** (volume `firecrawl-jobs`) nên sống
sót qua restart; tự dọn sau `JOB_TTL_SECONDS` (mặc định 24h).

Thêm: `DELETE /v1/crawl/{id}` (huỷ job, trả về `{status:"cancelled"}`),
`GET /v1/crawl/{id}/errors` (`{errors, robotsBlocked}`).

### 4.4 `POST /v1/search` (qua SearXNG)
```bash
curl -X POST "http://localhost:17300/v1/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"docker compose","limit":5,"scrapeOptions":{"formats":["markdown"]}}'
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `query` | — | từ khoá (bắt buộc) |
| `limit` | `10` | số kết quả |
| `lang` | — | ngôn ngữ (vd `vi`) |
| `scrapeOptions` | — | nếu có thì **scrape luôn nội dung** mỗi kết quả |
| `egress` | `null` | chọn đường ra khi scrape kết quả (`vpn`/`proxy`/`direct`); **SearXNG query đi server-wide** (chỉnh ở tầng infra) |

Search đẩy sang SearXNG; có `scrapeOptions` thì mỗi kết quả được scrape (kèm CF bypass).
Response: `v1` trả về `{"success":true,"data":[{url,title,description,markdown?}]}`;
`v2` trả về `{"success":true,"data":{"web":[...]}}` (đúng model SDK Firecrawl v4).

### 4.5 `POST /v1/batch/scrape` (async) + `GET /v1/batch/scrape/{id}`
```bash
curl -X POST "http://localhost:17300/v1/batch/scrape" \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://a.com","https://b.com"],"formats":["markdown"]}'
# trả về {"success":true,"id":"<job_id>","url":".../v1/batch/scrape/<job_id>"}
```
Scrape song song một danh sách URL cố định (kèm CF bypass). Status giống `/crawl`.

### 4.6 `POST /v1/extract` (LLM) + `GET /v1/extract/{id}`
```bash
curl -X POST "http://localhost:17300/v1/extract" \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://example.com"],"prompt":"Lấy tiêu đề và mô tả","schema":{...}}'
```
Scrape các URL rồi gửi nội dung cho **LLM (OpenAI-compatible)** trích xuất JSON.
**Cần cấu hình LLM** (`LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`); chưa cấu hình thì
job `failed` với thông báo rõ ràng. Status: `data` là object JSON đã trích xuất.

### 4.7 `POST /v1/research` — gom nguồn đa-trục (chống bias, mở rộng)
Dành cho **nghiên cứu**: đa dạng hóa nguồn trên nhiều trục để tránh thiên lệch, không
chỉ "hai phe".
```bash
curl -X POST "http://localhost:17300/v1/research" \
  -H "Content-Type: application/json" \
  -d '{"query":"microplastics health effects","limit":18,"maxPerDomain":2}'
# Đa quan điểm theo nguồn cụ thể:
curl -X POST "http://localhost:17300/v1/research" -H "Content-Type: application/json" \
  -d '{"query":"Russia Ukraine war","categories":["news"],
       "sites":["tass.com","kyivindependent.com","aljazeera.com","bbc.com"]}'
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `query` | — | chủ đề (bắt buộc) |
| `categories` | `["general","news","science"]` | **đa loại nguồn**: báo chí/học thuật/bách khoa/chính thức/cộng đồng |
| `languages` | `[null]` | quét **đa ngôn ngữ** — khi có LLM, query được **dịch** sang từng ngôn ngữ trước khi search (đa ngôn ngữ thật); không LLM thì dùng query gốc + cảnh báo trong `warnings` |
| `sites` | — | danh sách domain **buộc gồm** (đa quan điểm, vd các phía) |
| `maxPerDomain` | `2` | **cap mỗi domain**, diệt thế áp đảo 1 nguồn |
| `limit` | `24` | tổng nguồn (cân bằng round-robin theo loại) |
| `scrape` | `false` | `true` thì scrape nội dung mỗi nguồn (+ cờ `blocked`) |
| `analyze` | `false` | `true` thì **so chéo nguồn bằng LLM** (#9): đồng thuận/bất đồng/outlier gắn URL. Tự bật `scrape` |
| `egress` | `null` | `"vpn"`/`"proxy"`/`"direct"` — áp dụng khi scrape nguồn (có `scrape:true`) |

Response: `{"success":true,"query":..,"stats":{byType,byDomain,blocked},"translations":{lang:query}|null,"analysis":{consensus,disagreements,outliers}|null,"warnings":[..],"sources":[{url,title,domain,sourceType,markdown?,blocked?}]}`.
`sourceType` là một trong academic / news / reference / official / community / aggregator / web.
`translations` (khi truyền `languages`) cho thấy query thực đã dùng mỗi ngôn ngữ. `analysis`
(khi `analyze:true`) là so chéo nguồn có **gắn URL** chống bịa. `warnings` báo rõ khi LLM
thiếu/lỗi hoặc cắt bớt nguồn — **fail-open**, không im lặng degrade.
Cơ chế chống bias: đa-category + **đa-ngôn-ngữ (dịch query)** + sites đa phía + dedupe + cap
domain + cân bằng theo loại + loại stub + **so chéo nguồn**. Stub gắn `blocked` để không "tàng hình".

### 4.7b `POST /v1/deep-research` — nghiên cứu sâu có trích dẫn (mở rộng, cần LLM)
Vòng lặp tự động: bẻ câu hỏi rồi tìm, scrape (CF-bypass), chấm độ-tự-tin từng ý, lặp với
truy vấn thay thế, sau đó **tổng hợp câu trả lời có trích dẫn `[n]`**. Là **async job** (model local
có thể chạy vài phút — ai cần nhanh dùng cloud).
```bash
# 1) Tạo job
curl -X POST "http://localhost:17300/v1/deep-research" -H "Content-Type: application/json" \
  -d '{"query":"Ai sáng lập công ty Anthropic và trụ sở ở đâu?"}'
# trả về {"success":true,"id":"<jobId>","url":".../v1/deep-research/<jobId>"}
# 2) Poll kết quả
curl "http://localhost:17300/v1/deep-research/<jobId>"
# 3) Hủy (tùy chọn)
curl -X DELETE "http://localhost:17300/v1/deep-research/<jobId>"
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `query` | — | câu hỏi nghiên cứu (bắt buộc) |
| `maxIterations` | `3` | số vòng tìm-kiếm tối đa (dừng sớm khi đủ tự tin) |
| `maxQueries` | `4` | số truy vấn mỗi vòng |
| `maxSourcesPerQuery` | `5` | số kết quả lấy mỗi truy vấn |
| `maxScrapePerIteration` | `6` | trần số trang scrape mỗi vòng |
| `egress` | `null` | `"vpn"`/`"proxy"`/`"direct"` — áp khi scrape nguồn |

Kết quả (`data` khi `status:"completed"`): `{query, answer (markdown + [n]), sources:[{n,url,title}],
subQuestions:[{question,answered,confidence}], iterations, warnings}`.
**Cần LLM** (LiteLLM — xem mục bật LLM): thiếu LLM thì job `failed` rõ ràng. Trong vòng lặp,
mọi bước phụ **fail-open** (ghi `warnings`); nguồn bị chặn (`blocked`) bị loại khỏi trích dẫn.

### 4.8 `POST /v1/agent` — browser agent tự lái (mở rộng, cần LLM)
Cho `url` + `prompt`; agent **tự lái trình duyệt** (LLM lặp quan sát rồi chọn phần tử **theo số thứ tự**
để click/gõ/cuộn) qua crawl4ai session rồi trả nội dung sau tương tác. **Async job**. Có **chống kẹt
(loop detection)**, **hậu kiểm hoàn thành (done-verify)** và **fail-closed** (báo rõ khi chưa đạt).
```bash
curl -X POST "http://localhost:17300/v1/agent" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","prompt":"Mở trang Pricing và lấy bảng giá"}'
# trả về {"success":true,"id":"<jobId>","url":".../v1/agent/<jobId>"}
curl "http://localhost:17300/v1/agent/<jobId>"           # poll
curl -X DELETE "http://localhost:17300/v1/agent/<jobId>"  # hủy
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `url` | — | trang bắt đầu (bắt buộc) |
| `prompt` | — | mục tiêu cho agent (bắt buộc) |
| `maxSteps` | `15` | trần số bước tương tác |
| `egress` | `null` | `"vpn"`/`"proxy"`/`"direct"` |

Kết quả (`data` khi `completed`): `{url, prompt, result, verified, stopReason, steps:[{action,index?,ok,changed?,verified?}], iterations, warnings}`.
`stopReason` là một trong `done` (đã verify) / `maxSteps` / `stuck`. **`verified:false` + `stopReason!="done"` = minh
bạch CHƯA đạt mục tiêu** (không giả vờ thành công). Agent ground hành động theo **số thứ tự phần tử**
(không đoán selector). **Cần LLM**; thiếu thì job `failed`. Model local nhỏ điều hướng kém tin cậy hơn —
cần mạnh hơn thì dùng cloud.

### 4.8b Streaming (SSE) — xem token/tiến độ live (cần LLM)
Hai job LLM dài có bản **streaming** (Server-Sent Events) song song với bản poll:
```bash
curl -N -X POST "http://localhost:17300/v1/deep-research/stream" \
  -H "Content-Type: application/json" -d '{"query":"..."}'
curl -N -X POST "http://localhost:17300/v1/agent/stream" \
  -H "Content-Type: application/json" -d '{"url":"...","prompt":"..."}'
```
Trả `text/event-stream`, mỗi dòng `data: {json}`. Loại event: `phase`, `iteration`, `step`,
`token` (mảnh câu trả lời), `done` (`{data:...}`), `error`. Ngắt kết nối thì job tự hủy.

**Guard chống generation hỏng** (áp cho MỌI call LLM, kể cả bản poll): cắt sớm khi **treo**
(`STREAM_STALL_TIMEOUT`), **quá chậm** (`STREAM_SLOW_SEC_PER_WORD`, mặc định 5s/word), **degenerate**
(cả trăm từ không ngắt câu `STREAM_MAX_WORDS_NO_PUNCT`, token khổng lồ không khoảng trắng, hoặc lặp từ
`STREAM_MAX_REPEAT`). Tắt bằng `LLM_STREAM=0`.

| Env | Mặc định | |
|---|---|---|
| `LLM_STREAM` | `1` | bật streaming + guards |
| `STREAM_STALL_TIMEOUT` | `30` | quá số giây này không có token thì cắt |
| `STREAM_SLOW_SEC_PER_WORD` | `5` | chậm hơn ngưỡng thì cắt |
| `STREAM_MAX_WORDS_NO_PUNCT` | `200` | vượt số từ không ngắt câu thì cắt |
| `STREAM_MAX_CHARS_NO_SPACE` | `2000` | token không khoảng trắng vượt ngưỡng thì cắt |
| `STREAM_MAX_REPEAT` | `12` | lặp từ quá ngưỡng thì cắt |

### 4.9 `POST /v1/monitor` — theo dõi thay đổi trang (mở rộng)

Tự động **phát hiện khi nội dung trang thay đổi**: đặt monitor một lần, sweeper nền sẽ
định kỳ scrape và so sánh hash — khi đổi thì sinh **change-event có unified diff**.
Nguồn bị chặn (`blocked`) không tạo đổi-giả (giữ snapshot cũ — đúng tinh thần anti-bias).

**5 endpoint:**

```bash
# Tạo monitor
curl -X POST "http://localhost:17300/v1/monitor" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","intervalSeconds":3600}'
# trả về {"success":true,"id":"<mon_id>","monitor":{...}}

# Kiểm tra ngay (thủ công, ngoài chu kỳ)
curl -X POST "http://localhost:17300/v1/monitor/<mon_id>/check"
# trả về {"success":true,"changed":true/false,"event":{at,diff,...} or null}

# Liệt kê tất cả monitor
curl "http://localhost:17300/v1/monitor"
# trả về {"success":true,"monitors":[{id,url,status,changeCount,...}]}

# Xem chi tiết (gồm events + snapshot)
curl "http://localhost:17300/v1/monitor/<mon_id>"
# trả về {"success":true,"monitor":{..., "events":[{at,diff,fromHash,toHash}], "snapshot":"..."}}

# Xóa monitor
curl -X DELETE "http://localhost:17300/v1/monitor/<mon_id>"
# trả về {"success":true,"status":"deleted"}
```

| Field request | Mặc định | Mô tả |
|---|---|---|
| `url` | — | bắt buộc |
| `intervalSeconds` | `3600` (env `MONITOR_DEFAULT_INTERVAL`) | chu kỳ kiểm tự động; tối thiểu theo `MONITOR_MIN_INTERVAL` |
| `scrapeOptions` | `{formats:["markdown"],onlyMainContent:true}` | tùy chọn scrape (giống `/v1/scrape`) |
| `egress` | `null` | `"vpn"`/`"proxy"`/`"direct"` — đường ra khi scrape |

- **Sweeper nền** kiểm các monitor đến hạn mỗi `MONITOR_TICK` giây (song song, giới hạn `CRAWL_CONCURRENCY`).
- **Change-event** có unified diff (định dạng `--- trước / +++ sau`), hash cũ/mới, thời điểm.
- **Lịch sử** giữ tối đa `MONITOR_MAX_EVENTS` event gần nhất.
- **Bền vững:** monitor lưu SQLite (volume `firecrawl-jobs`) — sống sót qua restart.
- **Blocked không đổi giả:** nếu scrape trả `blocked:true`, snapshot giữ nguyên (không nhầm là "trang đổi").
- Mọi endpoint có cả tiền tố `/v2/*`.

### 4.10 `POST /v1/transcript` — video ra transcript (caption-only, mở rộng)
Biến **nguồn video** thành text scrape được, chỉ lấy **caption có sẵn** (không ASR/Whisper,
không `ffmpeg`, không LLM). YouTube thử `youtube-transcript-api` trước, không được thì fallback `yt-dlp`
(xương sống, phủ 1000+ site); site khác đi thẳng `yt-dlp`.
```bash
curl -X POST "http://localhost:17300/v1/transcript" \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://www.youtube.com/watch?v=jNQXAC9IVRw"],"languages":["en","vi"]}'
```
| Field | Mặc định | Mô tả |
|---|---|---|
| `urls` | — | danh sách URL video (bắt buộc) |
| `languages` | `["en","vi"]` (env `TRANSCRIPT_LANGS`) | ngôn ngữ caption ưu tiên; ưu tiên manual > auto, **không có thì lấy bất kỳ** |
| `egress` | `null` | `"vpn"`/`"proxy"`/`"direct"` — đường ra khi tải caption (yt-dlp/youtube-transcript-api) |

Response: `{"success":true,"data":[{url,text,language,segments,source:"caption",blocked?}]}`.
Clip **không có caption nào** thì `blocked:true`, `text:""` (không "tàng hình", giống stub-detection).

**Trong suốt với `/scrape`, `/search`, `/research`:** URL video tự được nhận diện theo **mẫu
URL video thật** (vd `youtube.com/watch`, `/shorts/`, `youtu.be/…`, `vimeo.com/<số>`…) thì transcript
đổ vào field `markdown`. Trang **không phải video** trên cùng host (kênh/playlist/tìm-kiếm/about)
vẫn scrape như web bình thường. Host tùy biến (vd PeerTube) thêm qua env `VIDEO_HOSTS`. Agent
chỉ-biết-Firecrawl dùng được mà không cần biết đây là video; clip không caption gắn `blocked`.

### Biến môi trường (service `firecrawl-shim`)
| Biến | Mặc định | Mô tả |
|---|---|---|
| `CRAWL4AI_URL` | `http://crawl4ai:11235` | địa chỉ nội bộ Crawl4AI |
| `FLARESOLVERR_URL` | `http://flaresolverr:8191` | địa chỉ nội bộ FlareSolverr |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG cho `/v1/search` |
| `JOBS_DB_PATH` | `/data/jobs.db` | SQLite job store (trên volume) |
| `JOB_TTL_SECONDS` | `86400` | hạn sống của job (24h) |
| `CRAWL_CONCURRENCY` | `3` | số trang scrape/re-fetch song song |
| `CRAWL4AI_CACHE_MODE` | `ENABLED` | cache của Crawl4AI (`BYPASS` = luôn tải mới) |
| `SCRAPE_CACHE_TTL` | `600` | TTL (giây) cache RAM kết quả scrape; `0` = tắt |
| `SCRAPE_CACHE_MAX` | `128` | số entry tối đa của cache RAM |
| `PER_DOMAIN_DELAY_MS` | `500` | giãn nhịp (ms) giữa 2 request **cùng** domain; `0` = tắt |
| `FS_DOMAIN_TTL` | `1800` | nhớ "domain cần FlareSolverr" (giây); `0` = tắt |
| `SITEMAP_MAX_FILES` | `50` | giới hạn sitemap đệ quy |
| `TRANSCRIPT_LANGS` | `en,vi` | ngôn ngữ caption ưu tiên cho `/v1/transcript` |
| `VIDEO_HOSTS` | — | host video bổ sung (ngoài built-in) cho nhận diện video, ngăn cách bằng `,` |
| `TRANSCRIPT_TIMEOUT` | `60` | trần thời gian (giây) lấy transcript 1 video (chặn yt-dlp treo) |
| `SHIM_HTTP_TIMEOUT` | `180` | timeout (giây) httpx gọi backend |
| `FLARESOLVERR_MAX_TIMEOUT` | `120000` | maxTimeout (ms) giải CF (site nặng cần khoảng 120s) |
| `LLM_BASE_URL` | `http://litellm:4000/v1` | endpoint LLM OpenAI-compatible (mặc định trỏ service LiteLLM nội bộ) |
| `LLM_API_KEY` | — | API key LLM (litellm internal không cần; để rỗng) |
| `LLM_MODEL` | `angler-smart` | tên **model-group** trong `litellm/config.yaml` (`angler-fast`/`angler-smart`) |
| `VPN_PROXY_URL` | — | URL proxy khi `egress:"vpn"` (vd `http://gluetun:8888`); chưa set thì fail-open về direct |
| `RESIDENTIAL_PROXY_URL` | — | URL proxy khi `egress:"proxy"` (residential/datacenter); chưa set thì fail-open về direct |
| `DEFAULT_EGRESS` | `direct` | egress mặc định khi request không truyền field `egress` (`direct`/`vpn`/`proxy`) |
| `MONITOR_TICK` | `30` | chu kỳ (giây) sweeper quét monitor đến hạn |
| `MONITOR_MIN_INTERVAL` | `60` | khoảng cách kiểm tối thiểu (giây) — ép với intervalSeconds từ request |
| `MONITOR_DEFAULT_INTERVAL` | `3600` | intervalSeconds mặc định khi request không truyền |
| `MONITOR_MAX_EVENTS` | `50` | số change-event tối đa giữ lại trên mỗi monitor |

### 4.11 `GET /v1/logs` và `GET /v1/stats` — nhật ký hoạt động

Stack tự ghi lại hoạt động vào bảng `events` trong cùng file SQLite (`/data/jobs.db`) với TTL mặc định 7 ngày. Mỗi sự kiện có trường `ts` (epoch), `level`, `kind`, `request_id` (từ middleware HTTP hoặc job_id với job nền), `msg` và `fields` (JSON tự do).

```bash
# Xem 50 sự kiện scrape gần nhất
curl "http://localhost:17300/v1/logs?kind=scrape&limit=50"

# Lọc theo request_id (tương quan cùng một request)
curl "http://localhost:17300/v1/logs?request_id=abc123def"

# Thống kê 24h gần nhất
curl "http://localhost:17300/v1/stats?window=24h"

# Thống kê 90 phút gần nhất
curl "http://localhost:17300/v1/stats?window=90m"
```

**`GET /v1/logs`** — truy vấn sự kiện

| Tham số | Mặc định | Mô tả |
|---|---|---|
| `kind` | — | lọc theo loại: `scrape`, `search`, `crawl`, `http`, `research`, `extract`… |
| `level` | — | lọc theo mức: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `request_id` | — | lọc theo request-id (tương quan sự kiện cùng một request hoặc job) |
| `since` | — | từ mốc thời gian (epoch giây) |
| `until` | — | đến mốc thời gian (epoch giây) |
| `limit` | `200` | tối đa kết quả trả về (tối đa `1000`) |

Response: `{"success":true,"events":[{ts,level,kind,request_id,msg,fields}],"count":N}`.

**`GET /v1/stats`** — tổng hợp theo cửa sổ thời gian

| Tham số | Mặc định | Mô tả |
|---|---|---|
| `window` | `24h` | cửa sổ tính ngược từ hiện tại; chấp nhận `24h`, `90m`, `7d`, hoặc số giây thô |

Response: `{"success":true,"stats":{windowSeconds,total,byKind,byLevel,scrapeOutcomes,topDomains:[{domain,blocked,stub,total}]}}`.

**Biến môi trường liên quan (service `firecrawl-shim`):**

| Biến | Mặc định | Mô tả |
|---|---|---|
| `LOG_DB_ENABLED` | `1` | bật ghi sự kiện vào SQLite |
| `LOG_DB_LEVEL` | `INFO` | chỉ ghi sự kiện từ mức này trở lên |
| `LOG_TTL_SECONDS` | `604800` | hạn sống sự kiện (7 ngày); tự dọn khi khởi động và ~mỗi giờ |
| `LOG_FIELDS_MAX_CHARS` | — | cắt bớt nội dung fields nếu vượt ngưỡng |
| `LOG_BATCH_FLUSH_N` | — | gộp ghi theo số sự kiện |
| `LOG_BATCH_FLUSH_SEC` | — | gộp ghi theo thời gian (giây) |

Cả `/v1/logs` và `/v1/stats` cũng có tiền tố `/v2/*`. Khi `ANGLER_API_KEY` được đặt, hai endpoint này nằm sau cùng cổng như toàn bộ stack — gửi `Authorization: Bearer $ANGLER_API_KEY`; khi key để trống thì mở như bình thường.

---

### Bật VPN egress (tuỳ chọn — gluetun + NordVPN)
Mặc định mọi egress đi thẳng IP host. Muốn cho mỗi request chọn đi qua VPN:

```bash
cp .env.example .env              # (nếu chưa có) rồi điền WIREGUARD_PRIVATE_KEY (NordVPN NordLynx)
docker compose -f docker-compose.yml -f docker-compose.vpn.yml up -d
```
- Thêm container **gluetun** = HTTP proxy (`http://gluetun:8888`) tunnel qua NordVPN
  (WireGuard), kill-switch bật (VPN rớt thì chặn, không rò IP thật).
- **Per-request:** field `"egress": "vpn"` (hoặc `"proxy"` với `RESIDENTIAL_PROXY_URL`).
  Mặc định `direct`. Chưa cấu hình hoặc proxy không reachable thì **fail-open** (log cảnh báo,
  đi direct, request vẫn chạy).
- **SearXNG (giới hạn):** query metasearch **không** per-request. Muốn query SearXNG cũng qua
  VPN: sửa [`searxng/core-config/settings.yml`](searxng/core-config/settings.yml) thêm
  `outgoing: { proxies: { all://: http://gluetun:8888 } }` (chỉ khi chạy override VPN) rồi
  `docker compose ... restart searxng`. Bước **scrape** trong `/search`,`/research` thì đã
  per-request qua field `egress`.
- Tắt VPN: chạy lại chỉ với `docker compose up -d`.

### Fallback nguồn ngoài (public services) — opt-in

Khi đường **local** (Crawl4AI + FlareSolverr) bó tay (site chặn cứng/stub), bạn có thể **chủ động**
cho phép escalate sang một dịch vụ public để lấy nội dung — đổi lại **chia sẻ URL với bên thứ ba**
(nên **mặc định tắt**). Bật per-request bằng field `fallback` ở `/scrape`, hoặc đặt `DEFAULT_FALLBACK`.
Nội dung lấy từ ngoài luôn gắn `metadata.source` để bạn biết đây **không** phải nguồn local trung lập.
**Fail-open:** provider chưa cấu hình hoặc lỗi thì giữ `blocked`, không vỡ request.

| Provider | Cần key? | Env |
|---|---|---|
| `jina` (Jina Reader) | không (key tùy chọn) | `JINA_API_KEY` (tùy chọn), `JINA_BASE_URL` |
| `firecrawl` (Firecrawl cloud) | có | `FIRECRAWL_CLOUD_API_KEY`, `FIRECRAWL_CLOUD_URL` |

`DEFAULT_FALLBACK` (rỗng = tắt) đặt provider mặc định cho mọi request không nêu `fallback`.

### Bật LLM (LiteLLM router — local hay cloud, bạn chọn)
Stack có service **`litellm`** làm cổng LLM duy nhất (OpenAI-compatible), **luôn chạy nhưng inert**
tới khi bạn cấu hình provider. Bật `/v1/extract` và `/v1/deep-research`:

```bash
cp .env.example .env              # (nếu chưa có) điền GROQ/GEMINI/OPENROUTER_API_KEY (cái nào dùng) + OLLAMA_BASE_URL
# sửa litellm/config.yaml thành tên model Ollama BẠN chạy (ollama/<model>) trong 2 group
docker compose up -d              # litellm đọc key + cắm Ollama local
```
> `litellm/config.yaml` có **model mặc định generic** (mỗi user tự chọn model của mình — repo không
> giữ model cá nhân). Endpoint Ollama qua `OLLAMA_BASE_URL` trong `.env` (local hoặc remote). Để khỏi
> lỡ commit lựa chọn model cá nhân: `git update-index --skip-worktree litellm/config.yaml`.
- **2 model-group**: `angler-fast` (việc cơ học), `angler-smart` (suy luận khó). Shim mặc định
  gọi `angler-smart`. Router tự **fallback + cooldown** khi 1 deployment 429/hết-quota.
- **Local hay cloud do bạn chọn**: sắp lại thứ tự deployment trong group ở `litellm/config.yaml`
  = đổi ưu tiên (cloud-trước hay local-trước). Máy yếu thì full cloud; trọng riêng tư thì full local.
- **Minh bạch**: log shim ghi `LLM trả lời: group=… → model=<backend thực>`. Chưa cấu hình hoặc
  hết quota thì `/extract` job `failed` với thông báo rõ (không im lặng).

### Endpoint phụ
- `GET /health` trả về `{"status":"ok"}` (healthcheck)
- `GET /` trả về thông tin service + danh sách endpoint
- Mọi endpoint có cả tiền tố `/v2/*` (schema giống `/v1/*`)

### Eval harness — đo chất lượng bằng số (cần LLM)

Đo trên **chính dữ liệu stack** (chạy in-process trong container):
```bash
docker compose exec firecrawl-shim python -m app.eval.run all
# hoặc riêng từng phép đo:
docker compose exec firecrawl-shim python -m app.eval.run extraction
docker compose exec firecrawl-shim python -m app.eval.run faithfulness --out /tmp/eval.json
```
- **extraction accuracy** — `/extract` trích đúng field mong đợi tới đâu (LLM-judge so với `expected`).
- **synthesis faithfulness** — mỗi câu trong câu trả lời `/deep-research` có **nguồn thật chống lưng**
  hay **bịa** (adversarial verify; câu không trích nguồn bị tính là không-faithful).

Dataset built-in nhỏ ở `firecrawl-shim/app/eval/datasets/*.json` — thêm case của bạn (cùng định dạng)
hoặc trỏ `--dataset <file>`. Cần LLM (LiteLLM); model local chậm nên một lần chạy có thể vài phút.

Hướng dẫn chọn model cho từng tier và từng size xem [Chọn model LLM](docs/CHON-MODEL-LLM.md).

---

## Ghi chú thiết kế

- **Một người dùng, không auth mặc định** (về triển khai) — stack chạy cho riêng chủ máy, không
  định chia sẻ thành dịch vụ. `CRAWL4AI_API_KEY` để rỗng, limiter của SearXNG tắt (khỏi cần redis).
  Đừng thêm rate-limit hay multi-tenant trừ khi bạn chủ động mở ra ngoài mạng tin cậy. (Khác với
  "local hay cloud" ở trên: cái đó nói về đường ra egress, nguồn, LLM, không phải mô hình deploy.)
- **Cổng API key (opt-in)** — đặt `ANGLER_API_KEY` để gateway chặn mọi request thiếu hoặc sai
  `Authorization: Bearer <key>`, kể cả các đường dẫn tài liệu. Một secret tĩnh là đủ cho một người
  dùng; để trống thì giữ nguyên mặc định mở. Chi tiết ở mục Cấu hình qua `.env`.
- **Bảo vệ IP (bằng code):** cache + giãn nhịp per-domain + nhớ domain-cần-CF + bỏ giải-CF
  cho paywall, nhờ đó giảm hit lặp ra site đích. Đây là lớp "lịch sự", **không che IP**.
- **Che IP thật (VPN/proxy egress):** đã có — bật override `docker-compose.vpn.yml` (gluetun +
  NordVPN) và chọn `"egress":"vpn"`/`"proxy"` theo từng request, **fail-open** về direct khi
  chưa cấu hình. Xem mục **Bật VPN egress** ở trên.
- **Mọi service internal-only** trừ gateway — chỉ `17300` ra ngoài.
- **`/v1/extract` cần LLM** — mặc định trỏ service **LiteLLM** (`angler-smart`); cấu hình ít nhất 1 provider
  (cloud key hoặc Ollama local) là chạy. Xem mục **Bật LLM (LiteLLM)** ở trên.
- **CF nặng (vd thuvienphapluat.vn):** đã verify lấy được **toàn văn** qua firecrawl —
  cần `FLARESOLVERR_MAX_TIMEOUT` khoảng 120s. `onlyMainContent=true` có **lưới an toàn**: nếu
  PruningContentFilter cắt quá tay (fit < 30% raw) thì tự trả bản đầy đủ (không mất nội dung).
- **Giới hạn đã biết:** `map` không phủ bằng Firecrawl cloud (dựa link trang + sitemap);
  `onlyMainContent` là heuristic (PruningContentFilter + lưới an toàn), không phải readability/LLM.

## Cấu trúc repo

```
docker-compose.yml          # định nghĩa 5 service + volume
docker-compose.vpn.yml      # override opt-in: egress qua VPN (gluetun + NordVPN)
.env.example                # mẫu cấu hình (port, API key, LLM, VPN) — cp thành .env
gateway/Caddyfile           # route theo path-prefix + cổng API key
searxng/
  ├── .env
  └── core-config/settings.yml
firecrawl-shim/             # FastAPI shim Firecrawl sang Crawl4AI(+FlareSolverr+SearXNG)
  ├── Dockerfile, requirements.txt
  └── app/{main,scrape,search,research,crawl_jobs,extract,clients,transform,models,store,config,cache,domains}.py
```
