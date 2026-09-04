# Định hướng phát triển

## Nguyên tắc ưu tiên

Mỗi giai đoạn chỉ được mở rộng khi giai đoạn trước đã có kiểm thử và số đo chất lượng. Hệ thống ưu tiên bằng chứng có thể kiểm chứng hơn số lượng agent hoặc độ phức tạp hạ tầng.

## Giai đoạn 1 — Ingestion đáng tin cậy

- Tách xử lý tài liệu khỏi FastAPI.
- Đo tỷ lệ trang trích xuất được văn bản.
- Phát hiện PDF scan cần OCR.
- Theo dõi tài liệu đã index, lỗi hoặc cần xử lý lại.
- Import metadata và xử lý theo lô từ `Dataset_ESG`.

**Điều kiện hoàn thành:** xử lý lặp lại an toàn, không tạo chunk trùng và có báo cáo chất lượng cho từng PDF.

## Giai đoạn 2 — Hybrid RAG

- Giữ BM25 cho từ khóa, số liệu và mã tiêu chuẩn.
- Thêm embedding/vector search cho truy vấn ngữ nghĩa.
- Hợp nhất kết quả và rerank trước khi phân tích.
- Xây tập câu hỏi chuẩn để đo Recall@K, MRR và độ chính xác citation.

**Điều kiện hoàn thành:** Recall@5 tối thiểu 0,80 và citation đúng trang tối thiểu 0,90 trên tập đánh giá nội bộ.

## Giai đoạn 3 — ESG intelligence

- Rubric riêng cho Energy, Materials và Industrials.
- Tách disclosure, performance và evidence quality.
- So sánh nhiều năm và nhiều doanh nghiệp.
- Dùng điểm LSEG/S&P làm benchmark, không coi là ground truth.

## Giai đoạn 4 — Multi-agent có LLM

- Supervisor định tuyến theo ý định thay vì luôn chạy toàn bộ pipeline.
- Structured output cho từng agent.
- Citation validator loại mọi nhận định không có bằng chứng.
- Theo dõi timeout, retry, token và chi phí.

## Giai đoạn 5 — Production/MLOps

- PostgreSQL, vector database, object storage và background worker.
- Authentication, rate limit và audit log.
- Tracing bằng Langfuse hoặc OpenTelemetry.
- CI/CD lên môi trường staging trước production.

