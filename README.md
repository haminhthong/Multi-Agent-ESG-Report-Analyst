# Evidence-Grounded ESG Report Analyst

Nền tảng local-first để rà soát công bố ESG theo nguyên tắc **evidence-first**. Hệ thống không coi câu trả lời của agent là nguồn sự thật: mọi fact, nhận định và tín hiệu đều phải truy ngược được về tài liệu, trang, chunk ổn định và evidence id.

## Mục tiêu hiện tại

- Lập chỉ mục báo cáo PDF bằng PyMuPDF/PyPDF, có OCR Tesseract cho trang scan.
- Tách text thành layout block và chunk có `stable_id`, sau đó tìm kiếm BM25, dense hoặc hybrid/rerank.
- Trích xuất fact ESG offline thành lớp `fact_candidates`.
- Chỉ đưa fact vào `esg_facts` sau quyết định explicit `ACCEPTED`.
- Đánh giá disclosure theo rubric versioned `climate-disclosure-v1`.
- Trả lời có citation, completeness, claim/evidence mapping và trace của supervisor graph.
- Sàng lọc greenwashing chỉ trong luồng audit; đây là tín hiệu ưu tiên kiểm tra, không phải xác suất hay kết luận pháp lý.

## Luồng dữ liệu

```text
PDF
  -> validate
  -> native extraction / OCR
  -> page quality report
  -> layout blocks
  -> stable chunks + embeddings
  -> fact_candidates (offline)
  -> human/validator decision log
  -> esg_facts (accepted)

Question
  -> typed planner
  -> scoped retrieval
  -> citation validation
  -> request facts + completeness gate
  -> rubric audit
  -> temporal/comparison trên accepted facts
  -> claim review
  -> grounded answer
```

Re-index cùng một tài liệu dùng upsert và chỉ thay chunk/index của tài liệu đó. Review decision và fact accepted không bị xóa khi re-index.

## Hướng agent

Ứng dụng có một `AgentGraphSupervisor` chạy graph bounded theo từng request. Agent là lớp điều phối; parsing, retrieval, OCR, extraction, validation và rubric evaluation là deterministic services.

Route chuẩn:

```text
ScopeAgent
 -> QueryPlanningAgent
 -> RetrievalAgent
 -> EvidenceVerificationAgent
 -> EvidenceExtractionAgent
 -> EvidenceCompletenessGate
 -> ESGAuditAgent
 -> SpecializedAnalysisAgent (chỉ temporal/compare)
 -> ClaimVerificationAgent
 -> ExplanationAgent
 -> AnswerReviewAgent
 -> LimitationsAgent
```

Ba trách nhiệm reasoning chính là:

1. `QueryPlanningAgent`: chuyển câu hỏi thành `RetrievalPlan` có intent, criteria, metrics, năm và yêu cầu numeric.
2. `ESGAuditAgent`: đánh giá rubric và tạo kết quả theo evidence bundle của từng criterion.
3. `ExplanationAgent`: tổng hợp câu trả lời bounded từ citation đã kiểm tra.

Supervisor có cycle detection, giới hạn số bước và ghi `agent_route`, `agent_stop_reason`, `trace_steps`. Có ba chế độ:

- `agentic`: dùng LLM cho plan/tool proposal nếu cấu hình khả dụng.
- `orchestrated`: chạy graph bounded với planner deterministic.
- `deterministic`: tắt LLM, chạy hoàn toàn local.

## Fact lifecycle

`Store.add_document()` tự tạo candidate từ chunk sau khi index. Candidate không được đọc như accepted fact.

- `fact_candidates`: kết quả extraction chưa duyệt.
- `fact_review_decisions`: log nối tiếp của validator/người review.
- `esg_facts`: canonical fact đã accepted, dùng cho temporal và comparison.

Duyệt candidate:

```text
PATCH /api/v1/facts/{fact_id}
{
  "status": "ACCEPTED",
  "reviewed_by": "analyst@example.com"
}
```

`GET /api/documents/{document_id}/metrics` trả candidate của tài liệu để phục vụ màn hình review. Query online không ghi candidate vào canonical store.

## Cài đặt

Yêu cầu Python 3.11 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

OCR cần Tesseract trong PATH. Dockerfile đã cài Tesseract cho môi trường container.

## Chạy ứng dụng

```powershell
python -m uvicorn app.main:app --reload
```

Mở `http://localhost:8000`. Mặc định database là `data/esg.db`, demo data không tự nạp.

Nạp PDF hàng loạt:

```powershell
esg-analyst ingest --metadata data/metadata.csv --reports-dir data/reports
```

Audit deterministic:

```powershell
esg-analyst audit --agent-mode deterministic
```

Các lệnh evaluation:

```powershell
esg-analyst evaluate
esg-analyst benchmark
esg-analyst evaluate-answer
esg-analyst evaluate-extraction
```

## API chính

| Method | Endpoint | Mục đích |
|---|---|---|
| GET | `/health` | Health check và corpus stats |
| GET | `/api/documents` | Danh sách tài liệu đã index |
| POST | `/api/documents` | Upload và index PDF |
| POST | `/api/search` | Tìm citation trực tiếp |
| POST | `/api/analyze` | QA/audit qua supervisor workflow |
| POST | `/api/query` | QA evidence-grounded |
| POST | `/api/audit` | Audit disclosure |
| POST | `/api/temporal` | Temporal trên accepted facts |
| POST | `/api/compare` | Comparison trên accepted facts |
| GET | `/api/documents/{id}/metrics` | Candidate facts của tài liệu |
| GET | `/api/documents/{id}/audit` | Evidence matrix của tài liệu |
| PATCH | `/api/v1/facts/{fact_id}` | Accept/reject/conflict candidate |
| GET | `/api/analysis/recent/trace` | Trace request gần nhất |

Response phân tích gồm `request_id`, `status`, `answer`, `claims`, `citations`, `evidence_completeness`, `plan`, `versions`, `criterion_bundles`, `agent_route`, các pillar và specialized analysis nếu có.

## Cấu trúc thư mục

```text
app/
  main.py                 FastAPI routes
  workflow.py             supervisor workflow và state machine
  agent_runtime.py        bounded agent graph
  models.py               Pydantic contracts
  store.py                SQLite, FTS5, chunks, fact lifecycle
  document_service.py     PDF/OCR/quality/indexing
  capabilities/            planner, retrieval, verification, explanation
  domain/                  rubric, matrix, screening, temporal, comparison
  extraction/              fact extraction và validators
  facts/repository.py      accepted/candidate repository
  static/                  dashboard
rubrics/
  climate_disclosure_v1.yaml
tests/
  unit/                    domain và lifecycle tests
  test_*.py                API, workflow, retrieval, ingestion
```

## Kiểm tra chất lượng

```powershell
python -m ruff check app tests
python -m ruff format --check app tests
python -m pytest
```

Test hiện bao phủ lifecycle candidate/accepted, provenance, OCR quality, retrieval, rubric, screening, API và agent route. Một số warning từ Starlette/httpx là warning phụ thuộc test client, không phải lỗi nghiệp vụ.

## Giới hạn cần biết

- Chỉ phân tích corpus đã index; không tự xác minh độc lập tính đúng của báo cáo doanh nghiệp.
- Fact extraction hiện là rule-based; candidate cần review trước khi dùng cho temporal/comparison.
- Rubric active trong repository hiện là `climate-disclosure-v1`; mở rộng Social/Governance cần thêm rubric versioned và field validators tương ứng.
- Hybrid dense/rerank có fallback deterministic khi model ML hoặc LLM không khả dụng.
- Screening là heuristic để ưu tiên kiểm tra, không phải kết luận greenwashing.
