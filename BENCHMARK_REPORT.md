# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Thị Thùy Dung · 2A202603552

**Ngày chạy:** 2026-11-26 (UTC+07)

**Môi trường:** WSL2, Python 3.14.4, FastAPI 0.115.0 và Pydantic 2.14.4 có sẵn. CP7 dùng httpx 0.27.2 và prometheus-client 0.26.0. CP8 dùng Docker Compose và Python 3.11 trong container.

## 1. SLO của agent

| SLI | Ngưỡng | Lý do |
|---|---:|---|
| CP7 p95 latency `/ask` | ≤ 500 ms | Mặc định load test. Đo thời gian của phần lớn request thành công và phản ánh độ trễ đuôi. |
| CP7 error rate `/ask` | ≤ 2% | Mặc định load test. Có dư địa cho lỗi mock ở cấu hình 1%. |
| Accuracy trên golden dataset | ≥ 80% baseline, 100% fixed | Gate cuối yêu cầu đủ 23 câu đúng và không regression. |
| CP8 latency và error alert | p95 > 1 s trong 2 phút, HTTP 5xx > 5% trong 1 phút | Ngưỡng và thời gian duy trì từ `alert_rules.yml`. |

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Agent v2 sau khi bổ sung KB chạy trên cổng 8002. Mỗi cấu hình gửi 300 request. Latency trong JSON chỉ tính HTTP 200, error rate tính mọi request. Nguồn số liệu là [reports/](reports/). CP7 và stack Docker chạy cùng máy trong một phần phép đo, nên CPU và I/O dùng chung có thể ảnh hưởng các lần chạy tải cao.

### Exercise 7.1 — Kiểm tra metrics

Gửi một câu 40 ký tự vào `/ask` trên v2 rồi scrape `/metrics`. Output thực tế có Counter `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, Gauge `agent_in_flight_requests 0.0` sau khi request kết thúc, và Histogram `agent_question_length_chars_count 1.0`, `_sum 40.0`. Bucket `le="20.0"` có 0 và `le="50.0"` có 1.

Histogram dùng tập bucket cố định. Route template và nhãn `unmatched` gom URL lạ vào một nhóm. Dùng path thật làm label sẽ tạo series mới cho từng URL, làm phình bộ nhớ và dữ liệu scrape.

### 2.1 Concurrency vs latency

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 3.90 | 195.0 | 226.3 | 1703.4 | 1.00% | PASS |
| 10 | 39.56 | 192.3 | 222.6 | 1690.2 | 0.33% | PASS |
| 50 | 82.50 | 244.6 | 1131.3 | 1771.3 | 0.67% | FAIL |
| 100 | 40.73 | 1193.3 | 5135.9 | 5421.0 | 0.33% | FAIL |

RPS đổi từ 3.90 ở concurrency 1 lên 39.56 ở 10, 82.50 ở 50 và 40.73 ở 100. Một worker có thể chồng thời gian chờ bất đồng bộ. Ở tải cao, lập lịch, kết nối và tài nguyên dùng chung làm request xếp hàng. Các phép đo này ghi nhận hệ quả ở độ trễ và throughput. Chúng chưa tách riêng từng nguyên nhân.

### 2.2 Tail latency

Giữ concurrency 20 và `MOCK_ERROR_RATE=0.01`. Khởi động lại v2 theo từng slow rate.

| `MOCK_SLOW_RATE` | Avg (ms) | p95 (ms) | p99 (ms) |
|---:|---:|---:|---:|
| 0 | 197.4 | 235.5 | 266.7 |
| 0.03 | 262.4 | 264.2 | 1712.7 |
| 0.1 | 357.9 | 1686.5 | 1711.7 |

Từ rate 0 đến 0.03, p99 đổi từ 266.7 lên 1712.7 ms, trong khi p95 đổi từ 235.5 lên 264.2 ms. Tại rate 0.1, p95 đạt 1686.5 ms. Percentile cao bộc lộ nhóm request chậm mà average làm loãng.

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

V1 chạy cổng 8001 và v2 chạy cổng 8002. `MOCK_ERROR_RATE=0` trong eval để đo chất lượng câu trả lời. Golden dataset và runner gốc được giữ nguyên.

| Chỉ số | V1 | V2 | V2 sau sửa KB |
|---|---:|---:|---:|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Average tokens / câu | 56.5 | 108.8 | 113.3 |
| Tổng cost mô phỏng (USD) | 0.000396 | 0.000758 | 0.000787 |
| Cost / câu đúng (USD) | 0.00039555 | 0.00003607 | 0.00003423 |
| p95 latency (ms) | 190.9 | 218.5 | 226.5 |
| Quality gate | FAIL | PASS | PASS |

| ID ban đầu sai | Keyword thiếu | Thay đổi |
|---|---|---|
| `security-02` | token, hết hạn, chữ ký | Thêm tài liệu JWT và vòng đời API key. |
| `scaling-03` | cpu, memory, custom metrics | Thêm tài liệu mô tả tín hiệu để HPA scale. |

Retrieval làm tăng token và p95 trong eval này. V2 sau sửa có chi phí mô phỏng trên mỗi câu đúng thấp nhất vì trả lời đúng nhiều câu hơn. Gate cuối so với baseline v2 trả exit 0 và không có regression. Khi so v1 với baseline v2, runner ghi 20 regression và trả exit 1.

Trong CI, khởi động candidate agent, chờ `/health` và chạy lệnh dưới đây trong thư mục `develop/`. Đặt job này thành required check trên nhánh chính để exit 1 chặn merge.

```bash
python eval/run_eval.py --url http://127.0.0.1:8002 --min-accuracy 1.0 \
  --baseline reports/eval_v2.json --out reports/eval_candidate.json
```

---

## 4. Observability stack (production)

Stack chạy với project `k5-day14-observability`. Image ban đầu tìm thấy script Uvicorn nhưng thiếu module khi chạy bằng user `agent`. Đặt `PYTHONUSERBASE=/home/agent/.local` để Python tìm thấy dependencies được copy từ builder. Build lại rồi kiểm `GET /health` qua Nginx trả 200. Lượt Locust trong lúc agent chưa boot bị loại khỏi số liệu. `promtool test rules /p/alert_rules_test.yml` báo SUCCESS với file gốc.

### 4.1 Dashboard và metrics (Exercise 7.4)

- [x] [Grafana dưới tải](screenshots/grafana-dashboard.png) hiển thị Golden Signals.
- [x] [Jaeger trace chậm](screenshots/jaeger-slow-trace.png) và [Jaeger trace lỗi](screenshots/jaeger-error-trace.png) có các span tương ứng.
- [x] [Prometheus Alerts](screenshots/prometheus-alert-firing.png) hiển thị hai cảnh báo SLO cùng firing.

Trong lượt Locust 30 users, ramp 5 users/giây và hai replica, mẫu Prometheus ghi p95 **294.1 ms** và avg **236.1 ms**. Khoảng cách phản ánh nhóm request ở đuôi phân phối. Tốc độ đo theo instance là 10.00 và 9.60 req/s. Input và output lần lượt **603.7** và **319.8** token/s. Input gồm prompt và context retrieval, trong khi output chỉ tính câu trả lời. Nginx trả 404 cho `/metrics`. Prometheus scrape các container agent qua mạng Compose.

### 4.2 Fault injection và thời gian phát hiện (Exercise 7.6)

Áp dụng A và B cùng lúc với 30 client làm tải để chụp hai alert cùng firing. Poll `/api/v1/alerts` mỗi 2 giây. Thời gian tính từ lúc bắt đầu áp dụng cấu hình hoặc gọi pause đến lần thấy firing đầu tiên, gồm thời gian scrape và điều kiện `for`.

| # | Thay đổi | Quan sát | Thời gian | Panel |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` firing ở 18.36% lỗi 5xx. | 87.7 s | Error rate |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` firing tại p95 1.89 s. | 147.8 s | Latency p95 |
| C | `LLM_MODEL=mock-llm-large` | Cost burn rate đạt 10.86 USD/giờ. `LLMCostBurnRateHigh` đã firing từ tải trước. | Trigger mới không quan sát được | Cost burn rate |
| D | Pause một agent | `AgentInstanceDown` firing khi scrape có `up=0`. Sau đó unpause. | 36.2 s sau khi gọi pause | Instances up |
| E | `AGENT_VERSION=v1` | `/health` trả ok và Prometheus thấy 3 instance v1. Alert cost cũ vẫn firing. Không quan sát thấy alert mới do đổi phiên bản. | Không áp dụng | Bảng version |

Pause giữ container trong DNS nên Prometheus còn thấy target và báo `up=0`. Nginx có thể gửi lỗi hoặc timeout mà metric agent không đếm được, vì vậy cần đo thêm ở gateway. Suy giảm chất lượng của v1 cần eval trước deploy và kiểm tra chất lượng bằng tập câu hỏi cố định trong production. Alert hạ tầng chỉ nhìn thấy các tín hiệu vận hành.

### 4.3 Trace và đối chiếu log (Exercise 7.5)

Trace chậm nhất trong mẫu Jaeger có log đối chiếu là `b0d80fc24318f42b662d4dd947f2b6a4`. Span HTTP mất **1725.24 ms**. Bên trong agent, `chat mock-llm-small` mất **1693.63 ms** (98.2% tổng thời gian) và retrieval mất 26.12 ms. [Ảnh Jaeger](screenshots/jaeger-slow-trace.png)

```json
{"ts": "2026-11-25T17:13:48.037677+00:00", "level": "INFO", "service": "observable-agent", "instance": "9529c8e56816", "event": "llm_call", "trace_id": "b0d80fc24318f42b662d4dd947f2b6a4", "span_id": "97db2271abbe2b84", "request_id": "e03f61abdc6f", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 79, "output_tokens": 46, "cost_usd": 3.9e-05, "llm_ms": 1692.6}
```

Trace lỗi `1e3fc2d89695503094a8c3edc71094f9` trả **HTTP 503** sau **844.73 ms**. Span chat mất 819.26 ms và chứa event `exception` với loại lỗi `utils.mock_llm.LLMError`. [Ảnh Jaeger](screenshots/jaeger-error-trace.png)

```json
{"ts": "2026-11-25T17:13:48.948395+00:00", "level": "INFO", "service": "observable-agent", "instance": "9529c8e56816", "event": "llm_error", "trace_id": "1e3fc2d89695503094a8c3edc71094f9", "span_id": "9b72d60224d53a46", "request_id": "9eb7d244e8a7", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

[Snapshot Prometheus, span Jaeger và log tương ứng](reports/observability.json)

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 56.70 | 210 | 910 | 1700 | 67/6752 (0.99%) |
| 3 | 59.50 | 200 | 320 | 1700 | 86/7093 (1.21%) |

Các hàng lấy từ POST `/ask` trong [CSV một replica](benchmark-results/scale_1_stats.csv) và [CSV ba replica](benchmark-results/scale_3_stats.csv). Cả hai lần chạy dùng 100 users, ramp 10 users/giây, 2 phút. `--no-deps` tránh Compose tự kích hoạt số replica mặc định khi tạo container Locust. Hai lượt đều báo lỗi HTTP 503 từ mock upstream.

P95 giảm từ 910 ms xuống 320 ms và throughput tăng từ 56.70 lên 59.50 req/s. P99 vẫn 1700 ms ở cả hai lượt, phù hợp với độ trễ mock bất thường còn xuất hiện sau scale. Tải Locust theo mô hình user với thời gian chờ giữa task nên throughput không tăng theo tỷ lệ replica. CP7 và CP8 chia sẻ máy trong một phần phép đo, vì vậy kết quả p95 có thể chịu ảnh hưởng tranh chấp tài nguyên.

---

## 6. Kết luận

1. Tail latency cho thấy nhóm request bị chậm ngay khi average còn thấp. Scale cải thiện p95 trong lượt này, còn p99 giữ ở khoảng 1.7 giây.
2. Trace đã định vị thời gian chậm trong span gọi mock LLM. Log cùng trace ID xác nhận lỗi upstream 503 của request khác.
3. Quality gate phát hiện v1 regression dù health vẫn 200. Cần theo dõi chất lượng cùng traffic, lỗi, latency và saturation.

Trong production, theo dõi 502/504 và latency tại gateway, budget burn theo thời gian, tỷ lệ retry và sai lệch eval/canary theo version. Giữ label có cardinality thấp và dùng trace ID trong log.
