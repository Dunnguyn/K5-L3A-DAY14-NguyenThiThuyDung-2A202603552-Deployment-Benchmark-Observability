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

### 4.1 Screenshot

- [x] [Dashboard Grafana dưới tải](screenshots/grafana-dashboard.png), có traffic, lỗi, p95, in-flight và số instance.
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với hai alert cùng **firing**.

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

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

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
