# Chọn model LLM — tài liệu tham khảo

Một số tính năng của stack cần LLM (`/extract`, `/research` khi bật `analyze`, `/deep-research`,
`/agent`). LLM là lựa chọn của user: chạy local (Ollama/vLLM/LM Studio) hay cloud free-tier
đều được, miễn là nói được `/chat/completions` chuẩn OpenAI. Shim gọi thẳng endpoint đó, không
có router trung gian. File này giúp chọn model cho đúng việc và đo chất lượng thật thay vì đoán.

Cấu hình để bật LLM xem [`README.md`](../README.md) mục "Bật LLM". Cập nhật: 2026-09-23.

---

## Hai tier model

Stack chia việc thành hai tier để xài model nhỏ cho việc dễ và model lớn cho việc khó:

- Tier fast cho việc cơ học: planning, sinh truy vấn, lọc, tóm tắt, dịch query, extract đơn
  giản (các tác vụ 1 đến 5, 8, 10 ở bảng dưới).
- Tier smart cho suy luận khó: synthesis, hậu kiểm citation, so chéo nguồn (tác vụ 6, 7, 9).

Đặt qua env `LLM_MODEL_FAST` và `LLM_MODEL_SMART` (bỏ trống thì cả hai lấy `LLM_MODEL`). Việc
chọn tier nào cho tác vụ nào nằm trong mã shim, không nằm ở cấu hình. Hai tier có thể trỏ vào
cùng một model nếu bạn không cần tách.

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
- Tier fast: khoảng 4B local (Gemma/Qwen) hoặc một model cloud nhỏ, nhanh cho việc dễ.
- Tier smart: khoảng 12 đến 14B local hoặc một model cloud mạnh hơn cho việc khó.

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

## Số đo thật trên endpoint đang dùng (đo ngày 2026-09-23)

Endpoint hiện cấu hình là `https://console.bizbrain.app/v1`, OpenAI-compatible. Mình đo bốn model
chat của nó trên hai tải sát workload thật của Angler:

- Tải fast: dịch một query ngắn sang hai thứ tiếng, trả JSON.
- Tải smart: payload 112.938 ký tự (khoảng 28K token, gần gấp đôi trần 60.000 ký tự mà
  `extract.py` cắt), yêu cầu trích hai con số nằm lẫn giữa văn bản nhiễu, trả JSON.

| Model | fast: xong sau | smart: xong sau | smart trả đúng số | Ghi chú |
|---|---|---|---|---|
| Qwen3.8-27B | 1,8s | 5,7s | đúng | không tốn token suy nghĩ, nhanh nhất cả hai tải |
| GLM-5.3 | 6,5s | 8,3s | đúng | có suy nghĩ trước khi trả lời, chậm hơn nhưng vẫn gọn |
| DeepSeek-V4-Flash | 20,1s | 15,7s | đúng | context 1M, nhưng chậm nhất, kể cả với prompt ngắn |
| Qwen3.8-27B-Uncensored | 3,0s | 7,8s | JSON hỏng | trả `{"ok{"ok":1}`, không dùng được cho extract |

Chốt đề xuất:

```
LLM_MODEL_FAST=Qwen3.8-27B
LLM_MODEL_SMART=GLM-5.3
```

Lý do: tier fast nằm trong vòng lặp của deep-research và agent nên độ trễ nhân lên theo số vòng,
Qwen3.8-27B nhanh gấp ba hai model kia. Tier smart đổi lấy khả năng suy luận với giá 2,6 giây so
với Qwen, mức chênh không đáng kể cho một job extract hay deep-research chạy nền.

DeepSeek-V4-Flash chỉ nên dùng khi thật sự cần context vượt 131K. Payload lớn nhất mà shim tạo ra
là 60.000 ký tự (`extract.py`), nên trường hợp đó hiện không xảy ra.

Cả ba model dùng được đều chạy tốt với `LLM_JSON_NATIVE=1`.

Về đường stream: model có suy nghĩ gửi `delta.reasoning_content` trước `delta.content`. Khoảng
cách lớn nhất giữa hai dòng SSE đo được là 5,3 giây, còn xa trần `STREAM_STALL_TIMEOUT` 30 giây,
nên guard chống treo không cắt nhầm.

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
