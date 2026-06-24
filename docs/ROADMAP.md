# ROADMAP — Angler

Tài liệu này chỉ liệt kê hướng tương lai và việc chưa làm. Năng lực đã hoàn thành mô tả ở
[`GIOI-THIEU-SAN-PHAM.md`](./GIOI-THIEU-SAN-PHAM.md); chi tiết endpoint ở
[`README.md`](./README.md). Cập nhật: 2026-06-22.

---

## Thêm provider fallback nguồn ngoài (chưa làm, thêm khi cần)

`/scrape` hiện đã có fallback v1: Jina Reader (miễn phí, không cần key) và Firecrawl cloud (cần
`FIRECRAWL_CLOUD_API_KEY`). Kiến trúc registry-ready (`PROVIDERS` dict cùng `fetch_external`):
thêm một provider chỉ là một hàm async kèm một env key.

Theo YAGNI, không build đầu cơ. Chỉ thêm provider mới khi gặp trang thật mà chuỗi local (Crawl4AI
và FlareSolverr) và cả Jina/Firecrawl đều bó tay, rồi ngắm provider theo đúng ca đó. Khảo sát
(06-2026):

| Provider | Mạnh ở | Công sức tích hợp | Chi phí (đã khảo) |
|---|---|---|---|
| ScrapingBee / ScraperAPI | proxy cao cấp kèm render, vượt anti-bot | Nhẹ — one-shot `GET ?url=&render=&premium_proxy=` trả HTML, cắm như Jina | Trial khoảng 1.000 credit (không thẻ); call render kèm premium khoảng 25–75 credit mỗi lần, chỉ khoảng 15–40 lần rồi trả phí |
| Browserbase | điều khiển trình duyệt thật (form, multi-step, JS tương tác) | Nặng — drive session qua CDP/Playwright trả HTML rồi `raw://` re-render (giống đường FlareSolverr, thêm phụ thuộc Playwright). Cần API key và Project ID | Free tier giới hạn phút mỗi session rồi trả phí |
| Exa | search ngữ nghĩa/neural (không phải scraper) | `/contents` cắm dạng fallback thì dễ nhưng phí giá trị; đúng chỗ là backend search/research (việc lớn hơn, lệch local-first) | Trial rồi trả phí |

Kết luận khảo sát: mảng "render và premium-proxy vượt anti-bot" không có cái nào free mãi mãi,
tất cả chỉ trial rồi trả phí; cái free thật duy nhất là Jina (đã tích hợp). Nếu cần dễ và rẻ nhất
khi chấp nhận trả phí thì chọn ScrapingBee one-shot; nếu cần điều khiển trình duyệt phức tạp thì
việc đó gần `/agent` hơn là scrape-fallback. Nên giữ nguyên registry-ready, chưa thêm tới khi có
trang thật cần.

---

## Nguyên tắc cho tính năng mới

Khi thêm tính năng mới, giữ triết lý lõi là local hay cloud đều là lựa chọn của user:
- Không thiên bên nào, cả hai đều first-class: user có hardware thì full local (riêng tư); user
  không có hardware thì full cloud (free-tier hoặc dịch vụ) vẫn dùng trọn vẹn. Stack không tự ép
  một đường.
- Cho chọn theo từng request, hoặc đặt default qua env.
- Minh bạch giới hạn: mỗi lựa chọn có đánh đổi, nên stack phải cho user biết rõ bằng cách đánh dấu
  nguồn và đường đi (cờ kiểu `blocked`/`source`) và báo rõ khi vướng giới hạn (chưa cấu hình, hết
  quota, model quá nhỏ), không im lặng degrade.
- Có dự phòng và không chết câm: lựa chọn lỗi hoặc hết quota thì thử dự phòng user đã cấu hình;
  nếu không có thì trả thông báo rõ ràng, không giả vờ thành công.
- Ưu tiên làm bằng code thay vì bắt LLM gánh, giữ tinh thần đa dạng nguồn và chống bias.
