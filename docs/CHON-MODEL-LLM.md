# Chọn model LLM — tài liệu tham khảo

Một số tính năng của stack cần LLM (`/extract`, `/research` khi bật `analyze`, `/deep-research`,
`/agent`). LLM là lựa chọn của user: chạy local (Ollama/vLLM/LM Studio) hay cloud free-tier
(Groq/Gemini/OpenRouter/DeepSeek...) đều được, vào chung qua LiteLLM router. File này giúp chọn
model cho đúng việc và đo chất lượng thật thay vì đoán.

Cấu hình để bật LLM xem [`README.md`](../README.md) mục "Bật LLM". Cập nhật: 2026-06-22.

---

## Hai tier model

Stack chia việc thành hai tier, mỗi tier là một model group trong LiteLLM (trải được cả local lẫn
cloud), để xài model nhỏ cho việc dễ và model lớn cho việc khó:

- `angler-fast` cho việc cơ học: planning, sinh truy vấn, lọc, tóm tắt, dịch query, extract đơn
  giản (các tác vụ 1 đến 5, 8, 10 ở bảng dưới).
- `angler-smart` cho suy luận khó: synthesis, hậu kiểm citation, so chéo nguồn (tác vụ 6, 7, 9).

Đặt qua env `LLM_MODEL_FAST` và `LLM_MODEL_SMART` (mặc định cả hai bằng `LLM_MODEL`). Router tự
route và fallback khi một deployment 429 hoặc hết quota.

---

## Việc cần LLM trong stack

Khoảng 10 tác vụ, không chỉ mỗi synthesis. Phần lớn việc retrieval và làm sạch mà người ta hay
bắt LLM gánh thì stack đã làm bằng code, nên model chỉ cần reasoning trên text sạch.

| # | Tác vụ | Nhóm | Độ khó |
|---|---|---|---|
| 1 | Chia query thành sub-search (planning) | research | Dễ |
| 2 | Sinh truy vấn thay thế khi chưa trả lời được (retry) | research | Dễ |
| 3 | Lọc liên quan: chọn kết quả nào đáng scrape | research | Vừa |
| 4 | Tóm tắt hoặc nén từng nguồn trước khi tổng hợp (map) | research | Dễ đến vừa |
| 5 | Quyết định đã đủ chưa, dừng vòng lặp (loop control) | research | Vừa |
| 6 | Tổng hợp có citation (synthesis) | research | Khó |
| 7 | Hậu kiểm citation, faithfulness | research | Khó |
| 8 | Dịch và chuẩn hóa đa ngôn ngữ (dịch query) | chống bias | Dễ đến vừa |
| 9 | So sánh chéo nguồn, phát hiện bất đồng | chống bias | Khó |
| 10 | Extract JSON theo schema (`/v1/extract`) | extract | Vừa |
| + | (cho `/agent`) quyết định hành động trình duyệt, đọc trạng thái, điền form | agent | Khó |

---

## Chọn model local theo size

Hướng dẫn này cho user chọn đường local. Chọn cloud thì dùng model của provider
(Gemini-Flash/Pro, Groq-Llama, DeepSeek...) ánh xạ vào cùng hai tier ở trên, không cần bảng này.
Các con số dưới là theo lớp kích cỡ, cần đo thật trên workload thực tế (xem mục eval).

| Lớp size | Dùng được cho | Không nên |
|---|---|---|
| khoảng 2B | tác vụ vặt: phân loại, trích field đơn giản, tóm tắt một đoạn | synthesis nghiên cứu (hay bịa, nông) |
| khoảng 4B (Gemma 4 / Qwen khoảng 4B) | tác vụ 1, 2, 3, 4, 8, 10: planning, dịch, tóm tắt, lọc, extract đơn giản | tác vụ 6, 7, 9 nếu không ràng buộc chặt |
| khoảng 12 đến 14B (Gemma 3 12B / Qwen 7 đến 14B) | tác vụ 6, 7, 9: synthesis, kiểm citation, so chéo | đây là sweet spot cho deep-research local |

Rủi ro lớn nhất của model nhỏ là bịa citation. Giảm bằng cách ép format trích nguyên văn kèm URL
nguồn, chia nhỏ chunk mỗi nguồn, grounding chặt, và hậu kiểm citation (tác vụ 7).

Ánh xạ vào hai tier:
- `angler-fast`: khoảng 4B local (Gemma/Qwen) hoặc Gemini-Flash/Groq cloud cho việc dễ.
- `angler-smart`: khoảng 12 đến 14B local hoặc Gemini-Pro/DeepSeek cloud cho việc khó.

---

## Tiêu chí khác khi chọn model

Size chỉ là một phần. Với workload của Angler (gom nhiều nguồn để synthesis, extract trang dài,
loop nhiều vòng cho deep-research và agent), mấy yếu tố dưới đây thường quyết định nhiều hơn.

### Context window

Quan trọng vì synthesis và deep-research nhồi nhiều nguồn vào một lần gọi, còn extract thì đưa cả
trang markdown (trang luật, tài liệu dài có thể rất lớn). Stack đã giảm tải bằng cách tóm tắt và
nén từng nguồn trước khi tổng hợp (tác vụ 4), nhưng bước synthesis vẫn phải giữ nhiều nguồn cùng
citation trong context.

- Tier fast (planning, dịch, lọc) sống tốt với context nhỏ, khoảng 8k là đủ.
- Tier smart (synthesis, so chéo, extract trang dài) nên chọn context từ 32k trở lên để khỏi phải
  cắt nguồn quá tay.
- Với model local, để ý context thực dùng được thường nhỏ hơn con số quảng cáo: chất lượng tụt
  dần khi gần chạm trần, nhất là bản quant mạnh.

### Thinking mode (reasoning)

Model reasoning (Qwen3, DeepSeek-R1, gpt-oss bật reasoning...) bỏ token ra suy nghĩ trước khi trả
lời, hợp cho việc khó: synthesis (6), hậu kiểm citation (7), so chéo nguồn (9), và quyết định của
agent. Đổi lại nó tốn token và chậm hơn, mà trong loop deep-research hoặc agent thì độ chậm này
nhân lên theo số vòng. Tier fast nên dùng model không thinking (hoặc tắt thinking) để loop nhanh.

Lưu ý một interaction đã gặp trong repo: model thinking khi nhận `response_format` kiểu
`json_object` thường trả content rỗng. Vì vậy đặt `LLM_JSON_NATIVE=0` cho các model như Qwen3
reasoning. Model thường (không thinking) thì để mặc định `LLM_JSON_NATIVE=1`.

### JSON và structured output

`/extract` bắt model trả JSON theo schema. Model bám schema kém thì extract hay hỏng. Nếu model hỗ
trợ chế độ JSON native thì bật `LLM_JSON_NATIVE=1` cho ổn định; model thinking thì tắt như trên,
và bù lại bằng prompt ép format rõ ràng.

### Đa ngôn ngữ

Research chống bias và dịch query (tác vụ 8) cần model giỏi đa ngôn ngữ, gồm cả tiếng Việt. Model
thiên về tiếng Anh thường dịch query và đọc nguồn ngoại ngữ kém, làm hỏng mục tiêu gom nguồn đa
ngôn ngữ. Gemma và Qwen nhìn chung khá khoản này.

### Độ trễ trong loop

Deep-research và `/agent` gọi LLM nhiều vòng, nên một model chậm (hoặc reasoning nặng) có thể kéo
một job tới vài phút. Cân nhắc tốc độ token mỗi giây của model local trên máy bạn, hoặc rate-limit
của cloud free-tier. Việc một lần (như extract) thì độ trễ ít đáng lo hơn.

### Quantization (local)

Bản quant càng mạnh (Q4 trở xuống) càng dễ bịa citation, hại faithfulness của synthesis. Việc khó
(tier smart) nên dùng quant nhẹ hơn (Q5 hoặc Q8) nếu VRAM cho phép; việc dễ thì quant mạnh vẫn ổn.

### Không cần function calling

Shim dùng prompt JSON và index-grounding chứ không dựa vào tool/function calling, nên đừng loại
một model chỉ vì nó thiếu tính năng đó. Cái cần là bám format và reasoning, không phải tool API.

---

## Đề xuất cho OpenRouter free (đo ngày 2026-06-22)

OpenRouter đổi pool model free bất kỳ lúc nào, nên phần này có hạn dùng và cần kiểm lại định kỳ.
Lấy danh sách free hiện tại bằng `scripts/refresh-litellm-free.py`, hoặc query nhanh:

```bash
curl -s https://openrouter.ai/api/v1/models \
  | jq -r '.data[] | select(.pricing.prompt=="0" and .pricing.completion=="0") | .id'
```

Ngày đo có 27 model free. Mình test live 5 ứng viên đa ngôn ngữ trên ba tác vụ sát workload
Angler: extract JSON từ văn bản tiếng Việt, dịch query sang ba thứ tiếng, và synthesis có citation
kèm phát hiện outlier. Kết quả:

| Model | Context | Extract JSON | Dịch đa ngôn ngữ | Synthesis kèm citation | Độ trễ | Tình trạng free |
|---|---|---|---|---|---|---|
| gemma-4-31b-it:free | 262k | đúng (bọc fence) | đúng | tốt nhất: cite đủ, bám nguồn chặt, bắt được outlier | 2.7 đến 5.8s | chạy ổn cả 3 task |
| gpt-oss-120b:free | 131k | đúng (JSON trần) | đúng | tốt, nhưng bồi thêm vài chi tiết không có trong nguồn | 3.1 đến 7.2s | chạy ổn cả 3 task |
| gpt-oss-20b:free | 131k | đúng (JSON trần) | đúng | khá, một câu outlier thiếu tag [2] | 2.8 đến 7.2s | chạy ổn cả 3 task |
| qwen3-next-80b-a3b-instruct:free | 262k | đúng | bị rate-limit | bị rate-limit | 1.8s | chỉ qua 1 trên 3, còn lại 429 |
| gemma-4-26b-a4b-it:free | 262k | bị rate-limit | bị rate-limit | bị rate-limit | không đo được | 0 trên 3, 429 cả 5 lần retry |

Nhận xét:
- Faithfulness: gemma-4-31b bám nguồn chặt nhất, không thêm thông tin ngoài nguồn, quan trọng cho
  synthesis và hậu kiểm citation. gpt-oss có xu hướng bồi thêm chi tiết hợp lý nhưng không có trong
  nguồn (over-attribution), cần để ý nếu dùng cho deep-research.
- JSON: gpt-oss trả JSON trần, cắm thẳng vào extract; gemma bọc trong khối fence nên shim phải bóc
  (transform đã làm, nhưng JSON trần vẫn sạch hơn). gemma và gpt-oss-20b hỗ trợ response_format
  json native; gpt-oss-120b thì không.
- Đa ngôn ngữ: cả năm đều dịch EN, JA, FR chính xác, không model nào rớt tiếng Việt.
- Rate-limit là yếu tố quyết định: gemma-4-26b-a4b và qwen tuy mạnh nhưng phổ biến nên bị throttle
  nặng, gần như không gọi được lúc cao điểm với key keyless-shared.

Chốt đề xuất (theo ngày đo):
- `angler-smart` (synthesis, so chéo, extract trang dài): `google/gemma-4-31b-it:free`. Faithfulness
  tốt nhất, context 262k, JSON native (giữ `LLM_JSON_NATIVE=1`), chạy ổn định. Fallback
  `openai/gpt-oss-120b:free` (reasoning mạnh, sẵn sàng; nhưng đặt `LLM_JSON_NATIVE=0` vì không có
  json native, và canh over-attribution).
- `angler-fast` (planning, dịch, lọc, extract đơn giản): `openai/gpt-oss-20b:free`. Nhanh, ổn định,
  JSON trần sạch, json native. Nếu muốn đúng hướng dùng 4B thì đặt `google/gemma-4-26b-a4b:free`
  làm primary (chất lượng và context tốt), nhưng bắt buộc có fallback vì nó hay 429.
- Luôn cấu hình chuỗi fallback trong `litellm/config.yaml`: xếp 2 đến 3 model free cùng tier rồi
  chốt bằng Ollama local, để khi free 429 thì router tự chuyển. Đây là cách duy nhất để free tier
  dùng được ổn định.

Lưu ý `LLM_JSON_NATIVE`: gemma và gpt-oss-20b để 1; gpt-oss-120b và các model reasoning thuần
(như Qwen3 reasoning) để 0.

Nếu cần context lớn hơn 262k cho nguồn cực dài: `nvidia/nemotron-3-super-120b-a12b:free` có 1M
context và đang free, nhưng thiên tiếng Anh, chưa kiểm tiếng Việt, chỉ cân nhắc khi nội dung chủ
yếu tiếng Anh.

---

## Đo chất lượng bằng eval harness

Để biết một model có đủ tốt cho workload của mình không, chạy eval harness thay vì đoán. Package
`app/eval/` chạy in-process trong container, có hai phép đo:

- Extraction accuracy: `/extract` trích đúng field mong đợi tới đâu, dùng LLM-judge so với
  `expected`.
- Synthesis faithfulness: mỗi câu trong câu trả lời `/deep-research` có nguồn thật chống lưng hay
  bịa, kiểm theo lối adversarial; câu không dẫn nguồn bị tính là không faithful.

```bash
docker compose exec firecrawl-shim python -m app.eval.run all
docker compose exec firecrawl-shim python -m app.eval.run extraction
docker compose exec firecrawl-shim python -m app.eval.run faithfulness --out /tmp/eval.json
```

Dataset built-in nhỏ ở `firecrawl-shim/app/eval/datasets/*.json`; truyền `--dataset <file>` để dùng
bộ riêng. Eval cần LLM, và model local chạy chậm nên một lần đo có thể mất vài phút. Kết quả biến
câu hỏi "model X đủ chất lượng chưa" thành con số trên đúng workload của bạn.
