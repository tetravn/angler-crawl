# Angler — Giới thiệu sản phẩm

> **"Thả query, kéo nguồn về."**
> Cổng search + crawl chạy local, biến web thành dữ liệu sạch — đa nguồn, chống thiên lệch.

Tài liệu này gồm 6 phần:
1. [Pitch 1 trang](#1-pitch-1-trang) — đọc 1 phút nắm ý.
2. [Bài giới thiệu đầy đủ](#2-bài-giới-thiệu-đầy-đủ) — Google thủ công vs. Angler.
3. [Toàn bộ năng lực & endpoint](#3-toàn-bộ-năng-lực--endpoint) — bảng tra cứu đầy đủ.
4. [Use-case kèm lệnh curl](#4-use-case-kèm-lệnh-curl) — kịch bản dùng thật.
5. [Đo lường giá trị (ROI)](#5-đo-lường-giá-trị-roi) — tiết kiệm bao nhiêu.
6. [Hướng phát triển & giới hạn đã biết](#6-hướng-phát-triển--giới-hạn-đã-biết) — nói thẳng.

---

## 1. Pitch 1 trang

### Angler là gì?
Một **cổng search + crawl chạy hoàn toàn trên máy bạn**, gói 5 service sau **một cổng duy nhất `17300`**. Gửi vào một truy vấn hoặc một URL — Angler trả về **nội dung sạch dạng markdown**, kể cả từ trang núp sau Cloudflare.

### Giải quyết nỗi đau gì?
Thu thập thông tin từ web bằng Google thủ công hiện rất tốn công: mở từng tab, lọc quảng cáo/menu bằng mắt, gặp trang chặn thì bó tay, và dễ chỉ đọc vài nguồn "top SEO" cùng một góc nhìn.

### Khác biệt cốt lõi (3 thứ Google không cho)
- **Web thành dữ liệu cho máy**: trả markdown sạch để agent/quy trình tự động dùng ngay, không copy-paste.
- **Chống thiên lệch có chủ đích**: `/research` đa loại nguồn, đa ngôn ngữ, ép nhiều phía, giới hạn mỗi domain.
- **Chủ quyền & riêng tư**: chạy local, không API key, không rate-limit, **query không rời máy bạn**.

### Một câu chốt
> Google trả cho bạn **đường link**; Angler trả cho bạn **nội dung đã sạch, đa nguồn, chống thiên lệch — tự động, miễn phí, ngay trên máy bạn.**

### Dành cho ai
Nhà nghiên cứu/phân tích, người xây AI agent, người cần bóc nội dung trang khó (Cloudflare, anti-bot).

---

## 2. Bài giới thiệu đầy đủ

### 2.1. Vấn đề: tìm và "bóc" thông tin từ Internet đang tốn công thế nào?

Quy trình thủ công với Google hôm nay thường là:

1. Gõ từ khóa rồi đọc 10 link xanh.
2. Mở từng tab, lướt qua quảng cáo, popup, banner cookie, menu.
3. Copy thủ công đoạn cần rồi dán vào ghi chú.
4. Gặp trang chặn (Cloudflare "checking your browser…", paywall, đăng nhập) thì bỏ cuộc hoặc loay hoay.
5. Lặp lại cho từng nguồn.

Bốn điểm đau mà bản thân Google **không** giải quyết:

| Điểm đau | Thực tế với Google thủ công |
|---|---|
| **Thủ công, không tự động hóa** | Mỗi nguồn là một lần copy-paste. Không có cách "lấy 18 nguồn về dưới dạng văn bản sạch" trong một lệnh. |
| **Nội dung bẩn** | Trang đầy nav/footer/quảng cáo/script. Phải tự lọc lấy phần "ruột". |
| **Bị chặn** | Trang sau Cloudflare/anti-bot/paywall nên Google đưa link nhưng bạn không vào đọc tự động được. |
| **Thiên lệch nguồn (bias)** | Google xếp hạng theo SEO/thuật toán. Dễ chỉ đọc vài nguồn "top", cùng một góc nhìn, cùng một ngôn ngữ. |

### 2.2. Angler là gì?

Tên gọi lấy từ **cá câu (anglerfish)** — thả mồi phát sáng kéo con mồi từ biển sâu lên. Angler nhận query và "kéo" nội dung sạch về từ khắp web.

Bên trong gồm 5 service sau một gateway Caddy, chỉ mở port `17300`:

| Service | Vai trò |
|---|---|
| **searxng** | Metasearch (tìm kiếm, trả JSON) |
| **crawl4ai** | Crawl/scrape trang ra markdown |
| **flaresolverr** | Vượt Cloudflare |
| **firecrawl-shim** | API **tương thích Firecrawl** (agent cắm-là-chạy) + `/research` chống bias |
| **gateway** | Caddy reverse proxy, gộp tất cả vào 1 port |

### 2.3. So sánh trực tiếp: Google thủ công vs. Angler

| Tiêu chí | Google + thao tác tay | Angler |
|---|---|---|
| **Đầu ra** | Danh sách link, tự mở, tự đọc | **Văn bản sạch (markdown)** sẵn để dùng/lưu/đưa vào agent |
| **Tự động hóa** | Không — copy-paste từng trang | **Một lệnh** lấy về N nguồn đã bóc nội dung |
| **Lọc nội dung** | Tự bỏ quảng cáo/menu/footer bằng mắt | **Tự lọc** phần chính (`onlyMainContent`), có lưới an toàn không cắt nhầm |
| **Trang bị Cloudflare** | Thường tắc | **Tự vượt** qua FlareSolverr, lấy được toàn văn |
| **Trang paywall/login** | Tưởng có nội dung nhưng thực ra trống | **Gắn cờ `blocked`** nên không tính nhầm là "có nội dung" |
| **Chống thiên lệch** | Phụ thuộc xếp hạng Google | **`/research` đa trục**: nhiều loại nguồn, đa ngôn ngữ, ép nhiều phía, cap mỗi domain |
| **Đa ngôn ngữ** | Phải tự đổi từ khóa, tự tìm | Quét **nhiều ngôn ngữ** trong một truy vấn |
| **Quét sâu một site** | Bất khả thi bằng tay | **Crawl** theo độ sâu, theo sitemap, chạy nền (async) |
| **Nguồn video** | Tự mở xem, không có text | **`/transcript`**: lấy phụ đề thành text scrape được như trang web |
| **Theo dõi thay đổi** | Tự mở lại, tự so bằng mắt | **`/monitor`**: sweeper nền theo chu kỳ, cho ra **unified diff** + lịch sử |
| **Chi phí** | Miễn phí nhưng tốn **thời gian người** | **Miễn phí, không API key**, tốn thời gian máy |
| **Riêng tư / che IP** | Query đi qua Google, bị log/hồ sơ hóa | **Query không rời máy bạn**; egress chọn theo request qua **VPN/proxy** (che IP thật) |
| **Cho AI agent** | Cần dịch vụ trả phí (Firecrawl cloud…) | **Tương thích Firecrawl SDK**, trỏ vào `localhost:17300` là dùng |

### 2.4. Ba khác biệt cốt lõi — vì sao không chỉ là "Google nhanh hơn"

**a) Biến "web cho người đọc" thành "dữ liệu cho máy dùng."**
Google trả link để *mắt người* đọc. Angler trả **markdown sạch** để *quy trình tự động* và *AI agent* dùng ngay — bỏ hẳn khâu copy-paste giữa.

**b) Chống thiên lệch nguồn một cách có chủ đích (`/research`).**
Thay vì để thuật toán xếp hạng quyết định bạn đọc gì, Angler chủ động đa dạng hóa: nhiều **loại nguồn** (báo chí/học thuật/bách khoa/chính thức/cộng đồng), nhiều **ngôn ngữ**, ép gồm **nhiều phía** (ví dụ một sự kiện địa chính trị buộc lấy cả tass.com lẫn kyivindependent.com lẫn bbc.com), **giới hạn mỗi domain** để không nguồn nào áp đảo. Mục tiêu: bức tranh đầy đủ, không phải "góc nhìn top SEO".

**c) Chủ quyền & riêng tư.**
Chạy local, không API key, không rate-limit, query không rời máy — đối lập với việc gửi mọi truy vấn nghiên cứu lên một dịch vụ cloud bên thứ ba.

### 2.5. Khi nào *chưa* nên dùng Angler (nói thẳng)

- Bạn chỉ cần tra một câu hỏi nhanh, đọc một trang thì mở Google nhanh hơn.
- `/extract` (bóc theo schema) cần cấu hình thêm một LLM local.
- `/map` (liệt kê toàn bộ URL của site) phủ chưa bằng Firecrawl cloud.
- Đây là công cụ **một người dùng, chạy local** — không phải dịch vụ chia sẻ nhiều người.

---

## 3. Toàn bộ năng lực & endpoint

### 3.1. Bản đồ năng lực

Angler phủ gần trọn API Firecrawl, **cộng** các mở rộng riêng (research chống bias, video sang transcript, monitor). Tất cả qua một cổng `17300`.

| Năng lực | Endpoint | Đồng bộ? | Tóm tắt |
|---|---|---|---|
| **Search** | `POST /v1/search` | sync | Tìm qua SearXNG; có `scrapeOptions` thì bóc luôn nội dung mỗi kết quả |
| **Scrape** | `POST /v1/scrape` | sync | Bóc 1 URL thành markdown/html/links; tự CF-bypass; gắn cờ `blocked` |
| **Map** | `POST /v1/map` | sync | Liệt kê URL của site (link trang seed + sitemap đệ quy) |
| **Crawl** | `POST /v1/crawl` rồi `GET /v1/crawl/{id}` | async | Quét sâu BFS theo `limit`/`maxDepth`; lưu SQLite |
| **Batch scrape** | `POST /v1/batch/scrape` rồi `GET /v1/batch/scrape/{id}` | async | Bóc song song một danh sách URL cố định |
| **Extract** | `POST /v1/extract` rồi `GET /v1/extract/{id}` | async | Bóc rồi cho **LLM** trích JSON theo schema — qua **LiteLLM** (local Ollama **hoặc** cloud free-tier, bạn chọn) |
| **Research** (mở rộng) | `POST /v1/research` | sync | Gom nguồn **đa trục chống bias** (mở rộng riêng của Angler) |
| **Deep research** (mở rộng) | `POST /v1/deep-research` | async job | Nghiên cứu sâu: bẻ câu hỏi, tìm/scrape, lặp, rồi **trả lời có trích dẫn** (mở rộng riêng; cần LLM) |
| **Transcript** (mở rộng) | `POST /v1/transcript` | sync | **Video thành transcript** (caption-only, yt-dlp); clip không caption thì `blocked` |
| **Monitor** (mở rộng) | `POST /v1/monitor` (+list/get/check/delete) | async (nền) | **Theo dõi thay đổi trang** theo chu kỳ, cho ra unified diff; nguồn blocked không tính "đổi giả" |
| **Activity log** (mở rộng) | `GET /v1/logs`, `GET /v1/stats` | sync | Ghi nhận sự kiện scrape ra stdout + SQLite; endpoint tra log và thống kê chất lượng crawl (tỉ lệ blocked/stub, FlareSolverr, fallback ngoài) theo cửa sổ thời gian |

> Mọi endpoint có cả tiền tố `/v1/*` và `/v2/*` (schema giống nhau; chỉ `/search` khác: `v1` trả `data` là list phẳng, `v2` trả `data.web` đúng model SDK Firecrawl v4).

**Ba mở rộng riêng (Firecrawl không có), đều code thuần — không phụ thuộc LLM:**
- **`/v1/transcript`** — biến nguồn **video** thành text scrape được (lấy phụ đề có sẵn qua `yt-dlp` + `youtube-transcript-api`); tự nhận diện URL video trong scrape/search/research; clip không phụ đề gắn `blocked` (không "tàng hình").
- **`/v1/monitor`** — đăng ký một URL, một sweeper nền **theo dõi thay đổi** theo chu kỳ, trả **unified diff** + lịch sử; bền vững qua restart (SQLite); nguồn bị chặn không tạo "thay đổi giả".
- **Egress chọn theo request** (`"egress": "direct" | "vpn" | "proxy"`) — đẩy traffic qua **VPN (NordVPN/gluetun) hoặc proxy** để **che IP thật**, bật bằng override `docker-compose.vpn.yml`. **Fail-open**: chưa cấu hình/không reachable thì tự đi thẳng, không lỗi.

### 3.2. Service truy cập trực tiếp (debug/nâng cao)

| Service | Đường dẫn qua gateway | Dùng khi |
|---|---|---|
| SearXNG | `GET /searxng/search?q=...&format=json` | Tìm kiếm thô, không qua lớp shim |
| Crawl4AI | `POST /crawl4ai/crawl` | Gọi crawler gốc, cần tham số nâng cao |
| FlareSolverr | `POST /flaresolverr/v1` | Tự giải Cloudflare một URL cụ thể |
| Health | `GET /health` | Kiểm tra shim sống |

### 3.3. Cơ chế chống thiên lệch của `/research` (chi tiết)

`/research` đa dạng hóa nguồn trên **nhiều trục cùng lúc**, không chỉ "hai phe":

- **Đa loại nguồn** (`categories`): báo chí / học thuật / bách khoa / chính thức / cộng đồng.
- **Đa ngôn ngữ** (`languages`): quét chủ đề ở nhiều ngôn ngữ — khi có LLM, query được **dịch** sang từng ngôn ngữ trước khi search (xem gạch đầu dòng "Dịch query đa ngôn ngữ" bên dưới); không LLM thì fallback query gốc + cảnh báo.
- **Ép nhiều phía** (`sites`): buộc gồm các domain bạn chỉ định (ví dụ các bên đối lập).
- **Cap mỗi domain** (`maxPerDomain`, mặc định 2): diệt thế áp đảo của một nguồn.
- **Cân bằng round-robin theo `sourceType`** + **dedupe** + **loại stub** (gắn `blocked`).
- **Dịch query đa ngôn ngữ** (cần LLM): query được dịch sang từng ngôn ngữ trước khi search
  nên thật sự gom nguồn nhiều thứ tiếng (không chỉ một ngôn ngữ của query gốc).
- **So chéo nguồn** (`analyze:true`, cần LLM): tổng hợp **đồng thuận / bất đồng / quan điểm
  lệch** giữa các nguồn, **mỗi luận điểm gắn URL** — thấy ngay chỗ các nguồn mâu thuẫn.

`sourceType` thuộc nhóm academic / news / reference / official / community / aggregator / web. Response kèm thống kê `stats.byType`, `byDomain`, `blocked` để bạn *thấy được* độ đa dạng của tập nguồn.

### 3.4. Cơ chế bảo vệ IP & tối ưu (tự động, "lịch sự")

Để giảm bị site đích chặn và đỡ tải lặp, Angler có sẵn (đều bật mặc định, tinh chỉnh qua biến môi trường):

| Cơ chế | Biến môi trường | Tác dụng |
|---|---|---|
| **Cache RAM kết quả scrape** | `SCRAPE_CACHE_TTL` (600s) | Không tải lại cùng URL trong TTL |
| **Giãn nhịp per-domain** | `PER_DOMAIN_DELAY_MS` (500ms) | Không bắn dồn request vào cùng một domain |
| **Nhớ "domain cần Cloudflare"** | `FS_DOMAIN_TTL` (1800s) | Lần sau đi thẳng FlareSolverr, đỡ thử-rồi-lỗi |
| **Bỏ giải-CF cho paywall** | (tự động) | Không tốn công giải Cloudflare cho trang vốn cần trả phí/đăng nhập |

> Đây là lớp "lịch sự" giảm hit lặp, **không che IP**. Phần che IP thật (proxy pool / VPN egress) nằm ở [phần 6](#6-hướng-phát-triển--giới-hạn-đã-biết).

### 3.5. Chuỗi fallback khi scrape (vì sao "bóc được trang khó")

Trong suốt với người gọi:

1. Thử **Crawl4AI** trực tiếp.
2. Nếu bị **Cloudflare chặn** hoặc Crawl4AI lỗi thì giải qua **FlareSolverr** rồi render lại HTML thành markdown.
3. Nếu vẫn là **stub** (HTTP 200 nhưng rỗng do anti-bot/paywall/JS-shell) thì gắn `metadata.blocked = true`.
4. **Lưới an toàn `onlyMainContent`**: nếu bộ lọc cắt quá tay (còn dưới 30% bản gốc) thì tự trả bản đầy đủ, tránh mất nội dung trang dài (vd văn bản pháp luật).

---

## 4. Use-case kèm lệnh curl

> Mọi lệnh giả định stack đã chạy: `docker compose up -d`. Cổng vào: `http://localhost:17300`.

### Use-case A — "Tìm rồi đọc luôn": tra cứu + bóc nội dung trong một lệnh
**Bối cảnh:** cần 5 nguồn về "docker compose", có sẵn nội dung markdown để đọc/tổng hợp, không phải mở 5 tab.

```bash
curl -X POST "http://localhost:17300/v1/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"docker compose best practices","limit":5,
       "scrapeOptions":{"formats":["markdown"]}}'
```
Trả về danh sách kết quả, **mỗi kết quả kèm `markdown` đã bóc sạch**. So với Google: bỏ qua bước mở từng tab và copy-paste.

### Use-case B — Bóc một trang khó (sau Cloudflare)
**Bối cảnh:** cần toàn văn một trang mà mở bằng tay thì gặp "checking your browser…".

```bash
curl -X POST "http://localhost:17300/v1/scrape" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://thuvienphapluat.vn/...","formats":["markdown"]}'
```
Angler tự thử Crawl4AI, nếu bị Cloudflare chặn thì **tự giải qua FlareSolverr** rồi render markdown. Nếu vẫn trống (paywall/login) thì gắn cờ `metadata.blocked = true` để bạn biết nguồn này không có nội dung thật — thay vì âm thầm tính là "đã lấy được".

### Use-case C — Nghiên cứu chống thiên lệch (điểm mạnh nhất)
**Bối cảnh:** một chủ đề nhạy cảm bias, cần nhiều phía, nhiều loại nguồn.

```bash
# Chủ đề khoa học — đa loại nguồn, cap mỗi domain 2 kết quả:
curl -X POST "http://localhost:17300/v1/research" \
  -H "Content-Type: application/json" \
  -d '{"query":"microplastics health effects","limit":18,"maxPerDomain":2}'

# Sự kiện địa chính trị — ép gồm nhiều phía:
curl -X POST "http://localhost:17300/v1/research" \
  -H "Content-Type: application/json" \
  -d '{"query":"Russia Ukraine war","categories":["news"],
       "sites":["tass.com","kyivindependent.com","aljazeera.com","bbc.com"]}'
```
Trả về danh sách nguồn đã **cân bằng theo loại** (academic/news/reference/official/community), kèm thống kê `byType`, `byDomain`, `blocked`. Đây là thứ Google **không** làm: chủ động đa dạng hóa thay vì xếp hạng theo SEO.

### Use-case D — Quét sâu cả một website (chạy nền)
**Bối cảnh:** cần gom nhiều trang trong một site (tài liệu, blog) về một mối.

```bash
# Khởi tạo job:
curl -X POST "http://localhost:17300/v1/crawl" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","limit":10,"maxDepth":2}'
# trả về {"success":true,"id":"<job_id>", ...}

# Theo dõi tiến độ:
curl "http://localhost:17300/v1/crawl/<job_id>"
```
Crawl theo độ sâu + sitemap, chạy async, job lưu SQLite nên sống sót qua restart. Thủ công bằng tay thì gần như bất khả thi.

### Use-case E — Cắm vào AI agent (không sửa code)
**Bối cảnh:** đã có agent dùng SDK Firecrawl, muốn chuyển sang local.

```python
from firecrawl import FirecrawlApp
app = FirecrawlApp(api_url="http://localhost:17300", api_key="dummy")  # key bị bỏ qua

app.scrape_url("https://example.com", formats=["markdown"])
app.search("docker compose", limit=5)
app.crawl_url("https://example.com", limit=10)
```
Chỉ đổi `api_url` về `localhost:17300`. Agent "chỉ biết Firecrawl" vẫn chạy, nhưng giờ **local, miễn phí, có CF-bypass và `/research`**.

### Use-case F — Liệt kê toàn bộ URL của một site (`/map`)
**Bối cảnh:** muốn biết một site có những trang nào trước khi quyết định crawl.

```bash
curl -X POST "http://localhost:17300/v1/map" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","limit":100,"search":"blog"}'
```
Gom link từ trang seed **+ sitemap đệ quy** (robots.txt tới sitemap index lồng nhau rồi tới `.xml.gz`); `search` lọc link chứa chuỗi. Lưu ý: phủ chưa bằng Firecrawl cloud (xem [phần 6](#6-hướng-phát-triển--giới-hạn-đã-biết)).

### Use-case G — Trích xuất dữ liệu có cấu trúc bằng LLM (`/extract`)
**Bối cảnh:** cần bóc đúng các trường (tên, giá, mô tả…) ra JSON, không phải cả trang markdown.

```bash
curl -X POST "http://localhost:17300/v1/extract" \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://example.com"],
       "prompt":"Lấy tiêu đề và mô tả",
       "schema":{"type":"object","properties":{
         "title":{"type":"string"},"description":{"type":"string"}}}}'
```
Scrape URL rồi gửi nội dung cho **LLM (OpenAI-compatible)** trích JSON theo schema. **Cần cấu hình** `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` (vd Ollama local); chưa cấu hình thì job `failed` với thông báo rõ ràng.

---

## 5. Đo lường giá trị (ROI)

> Con số dưới đây là **ước lượng khung tham chiếu** để định lượng giá trị — hãy thay bằng số đo thực tế của bạn khi triển khai.

### 4.1. Tiết kiệm thời gian người (so với làm tay bằng Google)

| Thao tác | Google thủ công (ước tính) | Angler | Tiết kiệm |
|---|---|---|---|
| Mở 1 trang + lọc nội dung sạch bằng mắt | khoảng 2–4 phút/trang | khoảng vài giây (1 lệnh) | khoảng 95% |
| Gom 18 nguồn cho 1 báo cáo | khoảng 60–90 phút | khoảng 1–2 phút (`/research`) | khoảng 95% |
| Vượt 1 trang Cloudflare | thường **bất khả thi** bằng tay | tự động | từ "không làm được" thành "làm được" |
| Quét 10 trang trong 1 site | khoảng 20–40 phút | khoảng 1 lệnh + chờ nền | khoảng 90% |

**Phép tính minh họa:** một báo cáo nghiên cứu cần khoảng 18 nguồn. Thủ công khoảng 75 phút thu thập + lọc. Với Angler khoảng 3 phút thao tác. **Tiết kiệm khoảng 72 phút/báo cáo.** Làm 3 báo cáo/tuần khoảng **3,6 giờ/tuần, tức khoảng 15 giờ/tháng** được giải phóng.

### 4.2. Tiết kiệm chi phí công cụ

| Khoản | Dịch vụ cloud (vd Firecrawl cloud) | Angler |
|---|---|---|
| API key / phí theo lượt | Có, tính theo credit | **0đ** — không API key |
| Rate-limit | Có | Không |
| Hạ tầng | Của nhà cung cấp | Máy của bạn (Docker) |

Chi phí biên cho mỗi truy vấn về **khoảng 0** (chỉ tốn tài nguyên máy). Càng dùng nhiều, ROI càng cao.

### 4.3. Giá trị khó quy ra tiền (nhưng quan trọng nhất)

- **Chất lượng nghiên cứu**: `/research` chống bias nên kết luận dựa trên bức tranh đa chiều, giảm rủi ro quyết định sai vì đọc lệch nguồn.
- **Độ trung thực dữ liệu**: cờ `blocked` đảm bảo nguồn rỗng không bị tính nhầm là "có nội dung" nên số liệu thống kê nguồn đáng tin hơn.
- **Riêng tư & chủ quyền dữ liệu**: query nghiên cứu không gửi ra cloud bên thứ ba.
- **Khả năng tự động hóa**: mở ra các quy trình mà thủ công không kham nổi (theo dõi định kỳ, nuôi dữ liệu cho agent).

### 4.4. Cách tự đo ROI của bạn

1. Đo thời gian trung bình bạn đang tốn cho 1 lần "tìm + đọc + lọc" 1 nguồn bằng tay.
2. Nhân với số nguồn/tuần.
3. So với thời gian thao tác Angler (gần như cố định, rất nhỏ).
4. Cộng thêm: số trang **trước đây không lấy được** (Cloudflare/paywall) mà giờ lấy được — đây là giá trị "mới", không chỉ là tiết kiệm.

---

## 6. Hướng phát triển & giới hạn đã biết

### 6.1. Trên roadmap (định hướng)

Tinh thần: công cụ nghiên cứu ưu tiên **đa dạng nguồn / chống bias**, và **local hay cloud là lựa chọn của user**. Hướng đang nhắm:

- **Deep research** (xong) — vòng lặp native: bẻ câu hỏi, tìm/scrape (CF-bypass), chấm độ-tự-tin, lặp, rồi **tổng hợp có trích dẫn `[n]`**; `/v1/deep-research` (async job, cần LLM).
- **Chống-bias nâng cao** — dịch query đa ngôn ngữ, so-chéo / phát hiện bất đồng nguồn (cần LLM).
- **Fallback nguồn ngoài** (xong, opt-in): khi local bị chặn, có thể cho phép dùng dịch vụ public
  (Jina/Firecrawl cloud) để lấy bằng được — nội dung gắn `source`, mặc định tắt (riêng tư trước).

> *Đã hoàn thành gần đây (không còn ở roadmap):* **LLM qua LiteLLM router (local/cloud) + `/extract`**,
> video sang transcript, `/monitor`, egress VPN/proxy, **`/deep-research` (native loop có trích dẫn)**,
> **fallback nguồn ngoài (Jina + Firecrawl cloud, opt-in)** — xem §3.

### 6.2. Giới hạn đã biết (nói thẳng)

| Giới hạn | Chi tiết |
|---|---|
| **`/extract` và `/deep-research` cần LLM** | Phải cấu hình LLM (local **hoặc** cloud) qua LiteLLM; chưa có thì job `failed` với thông báo rõ. `/deep-research` trên model local có thể chạy vài phút — dùng cloud nếu cần nhanh. |
| **`/map` phủ chưa bằng cloud** | Dựa trên link trang + sitemap, không bằng độ phủ của Firecrawl cloud. |
| **`onlyMainContent` là heuristic** | Lọc bằng PruningContentFilter + lưới an toàn, không phải readability/LLM. |
| **Đa-ngôn-ngữ `/research` cần LLM** | Khi có LLM, query được dịch sang từng ngôn ngữ (đa ngôn ngữ thật); không có LLM thì dùng query gốc, cảnh báo trong `warnings`. |
| **Một người dùng, không auth** | Stack chạy cho chủ máy; **đừng** expose ra mạng không tin cậy nếu chưa thêm auth/rate-limit. |

### 6.3. Định vị (nhắc lại để không hiểu nhầm)

Angler **không** cố thay Google ở việc "tra nhanh một câu", cũng **không** là superset tuyệt đối của Firecrawl cloud. Nó là **cổng vào** tương thích — bản sắc: **search + crawl hướng nghiên cứu, chống bias, và local hay cloud là lựa chọn của bạn** (mỗi đường có đánh đổi, stack luôn nói rõ giới hạn).

---

> **Tóm lại:** Angler không thay Google ở việc "tra nhanh một câu". Nó thay thế **toàn bộ quy trình thu thập + làm sạch + đa dạng hóa nguồn** — phần tốn công nhất, dễ sai lệch nhất, và khó tự động hóa nhất khi làm tay.
