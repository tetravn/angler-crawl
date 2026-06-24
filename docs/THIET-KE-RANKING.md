# Angler — Kiến trúc xếp hạng (ranking)

Tài liệu thiết kế cho lớp xếp hạng dùng chung của `/search` và `/research`. Mục tiêu không chỉ là
"kết quả liên quan nhất" mà là kết quả toàn diện nhất: ưu tiên nguồn tin cậy và nguồn mới, đồng thời
phủ đủ các góc nhìn (loại nguồn, ngôn ngữ, địa lý) để chống thiên lệch.

## Vấn đề và cách chia tầng

Xếp hạng có hai bài toán khác bản chất:

- Chấm điểm từng kết quả (point-wise): mỗi kết quả tốt tới đâu xét riêng nó.
- Làm cả danh sách toàn diện (list-wise): tập kết quả có đa dạng không, hay bị một domain hay một
  loại nguồn áp đảo.

Point-wise một mình không tạo được tính toàn diện, vì đa dạng là tính chất của cả tập. Nên kiến trúc
tách hai tầng: chấm điểm rồi đa dạng hóa.

## Catalog tín hiệu

Mỗi tín hiệu chuẩn hóa về đoạn [0, 1], cao là tốt. Phần lớn lấy được từ URL và metadata SearXNG nên
không cần scrape hay LLM.

| Tín hiệu | Đo gì | Nguồn dữ liệu |
|---|---|---|
| trust | sourceType: academic, official, reference, web, community, aggregator | domain (classify) |
| recency | mới vs cũ | publishedDate |
| engine_agreement | bao nhiêu engine SearXNG cùng trả về | field `engines` |
| institutional | tổ chức/entity vs blog cá nhân | domain |
| global_local | toàn cầu vs địa phương, khớp với intent | TLD + danh sách domain |
| language | ngôn ngữ kết quả khớp ngôn ngữ các bên liên quan | lang kết quả vs intent |
| geo | địa lý kết quả khớp các bên liên quan | ccTLD/domain vs intent |

Tín hiệu cần scrape hoặc LLM (chủ yếu cho `/research`): substance (nội dung thực chất, không stub),
corroboration (nhiều nguồn độc lập cùng xác nhận, qua cross_check), near-duplicate (cùng nội dung
khác domain).

## Tầng 1: chấm điểm point-wise

Gộp bằng tổng có trọng số, không phải nhân, để tinh chỉnh từng yếu tố độc lập.

```
quality(d)  = Σ wᵢ · signalᵢ(d) / Σ wᵢ           # trust, recency, engine, institutional, lang, geo, global_local
score(d)    = wr · relevance(d) + wq · quality(d)  # cả hai trong [0, 1]
```

`relevance(d)` lấy từ thứ hạng gốc của SearXNG, chuẩn hóa về [0, 1] (hạng càng cao điểm càng lớn), có
thể trộn thêm engine_agreement. `wr` và `wq` cân bằng giữa liên quan thuần và chất lượng nguồn. Mặc
định nghiêng về liên quan một chút để không bóp méo ý định tìm kiếm.

## Tầng 2: đa dạng hóa list-wise (MMR)

Chọn lần lượt từng kết quả. Mỗi lần chọn cái có điểm cân bằng cao nhất giữa điểm point-wise và độ
khác biệt so với những cái đã chọn:

```
chọn d = argmax [ λ · score(d) − (1 − λ) · similarity(d, đã_chọn) ]
```

`similarity(d, đã_chọn)` lấy max độ giống của d với từng cái đã chọn, tính theo: cùng domain (giống
nhất), cùng sourceType khi loại đó đã nhiều, cùng cụm ngôn ngữ hoặc địa lý, tiêu đề gần trùng
(near-duplicate). Kèm một ràng buộc cứng: mỗi domain tối đa k kết quả.

`λ` điều khiển mức đa dạng: λ = 1 là xếp thuần theo điểm, λ nhỏ hơn thì ép đa dạng mạnh hơn. `/search`
dùng λ cao (đa dạng nhẹ), `/research` dùng λ thấp hơn (ép phủ rộng).

## Query intent: LLM có heuristic đỡ lưng

Để chấm language và geo cho đúng, cần biết chủ đề liên quan tới ngôn ngữ và địa lý của những bên nào.
Đây là phần hiểu truy vấn.

- Đường LLM (ưu tiên): một call ngắn bằng `angler-fast`, trả JSON
  `{languages, geos, is_global, parties}`. Kết quả cache theo query để không gọi lại.
- Đường heuristic (đỡ lưng): đoán ngôn ngữ của query, nhận tên địa danh đơn giản, mặc định coi là
  global khi không có địa lý rõ.
- Fail-open: LLM lỗi, hết quota, hoặc quá timeout thì dùng ngay heuristic. Ranking không bao giờ chết
  vì thiếu LLM, chỉ kém sâu hơn một chút. Đúng nguyên tắc fail-open chung của stack.

Với chủ đề nhiều bên, `parties` cho biết cần phủ ngôn ngữ và địa lý nào. `/research` dùng thông tin
này để gom nguồn đa góc nhìn (chọn ngôn ngữ search và các `site:` theo từng bên), không chỉ để chấm
điểm.

## Khác nhau giữa /search và /research

| | /search | /research |
|---|---|---|
| Tầng 1 | đủ tín hiệu từ URL và metadata SearXNG | thêm substance và corroboration sau khi scrape |
| Tầng 2 | MMR nhẹ: cap domain + cân bằng sourceType | MMR đầy đủ, phủ đa ngôn ngữ và địa lý theo các bên |
| Query intent | LLM, fail-open heuristic, có cache | LLM, fail-open heuristic, dùng cả để gom nguồn |
| Độ trễ | mili-giây, LLM intent chạy nền có timeout ngắn | vài giây tới vài phút |

## Minh bạch

Mỗi kết quả trả kèm `sourceType`, và có thể kèm một object `ranking` phơi điểm từng tín hiệu, để
người dùng thấy vì sao kết quả được xếp ở đó. Đây là hộp kính chứ không phải hộp đen, đúng tinh thần
chống thiên lệch.

## Cấu hình

Mỗi trọng số tín hiệu, `wr`/`wq`, `λ` của MMR, và cap mỗi domain đều có env để chỉnh. Đặt một trọng
số về 0 là tắt tín hiệu đó. Đặt `λ` về 1 là tắt đa dạng hóa.

## Module

- `ranking.py`: hàm thuần chấm điểm và đa dạng hóa (test offline được, không I/O).
- `query_intent.py`: phân tích intent bằng LLM với heuristic đỡ lưng, có cache.
- `search.py` và `research.py`: gọi hai module trên.
- `config.py`: trọng số và knob.
