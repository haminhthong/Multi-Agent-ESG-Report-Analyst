# Evidence-Grounded ESG Report Analyst

[![CI](https://github.com/haminhthong/Multi-Agent-ESG-Report-Analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/haminhthong/Multi-Agent-ESG-Report-Analyst/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Repository: Multi-Agent-ESG-Report-Analyst

> Evidence-grounded ESG analysis from PDF reports: extract text, retrieve supporting passages, normalize structured metrics, validate facts, and produce answers with page-level citations.

## Bài toán và phạm vi

Báo cáo ESG thường dài, có bảng, OCR không đồng nhất và mô tả cùng một chỉ tiêu bằng nhiều tên khác nhau. Một câu trả lời hữu ích vì vậy không chỉ cần “tìm được đoạn văn bản”, mà còn phải giữ đúng tài liệu, trang, năm, đơn vị và phạm vi truy vấn.

Dự án được chia thành ba nhóm chức năng để mô tả luôn khớp với môi trường chạy:

- Core: PDF native extraction, layout metadata, OCR fallback, stable chunks, provenance,
  SQLite FTS5/BM25, structured ESG fact extraction, fact validation và grounded Q&A/audit;
- Extended analysis: rubric, evidence completeness, temporal analysis, company comparison và
  disclosure-risk screening dạng heuristic;
- Optional ML: SentenceTransformer dense retrieval, hybrid RRF, cross-encoder reranking và
  local LLM synthesis khi cài thêm profile `[ml]`.

FastAPI, CLI, dashboard, Docker và CI cung cấp cách chạy và kiểm thử reproducible cho pipeline.

Phạm vi là screening bằng chứng trên corpus đã index. Hệ thống không xác minh độc lập tính trung thực của doanh nghiệp, không suy ra hiệu quả ESG thực tế và không thay thế analyst, auditor hoặc tư vấn pháp lý.

## Pipeline kỹ thuật duy nhất

ESGPipeline.run() là entry point chung cho API, CLI và evaluation. Luồng không để LLM tự chọn tool hay điều khiển thứ tự xử lý.

~~~~mermaid
flowchart TD
    A[ESG PDF] --> B[Native text + layout extraction]
    B --> C{Trang thiếu text?}
    C -->|Có| D[OCR fallback + quality report]
    C -->|Không| E[Normalized page blocks]
    D --> E
    E --> F[Stable chunks + metadata]
    F --> G[SQLite FTS5 / BM25 mặc định]
    F -. optional ML .-> H[Dense / hybrid RRF / reranker]
    G --> I[Retrieved evidence]
    H --> I
    I --> J[Validated evidence citations]
    J --> K[Unit/year normalization + conflict checks]
    K --> L[Fact candidate repository]
    L --> M{Validator / human review}
    M -->|Rejected / conflict| N[Retain decision and limitation]
    M -->|Accepted| O[Accepted ESG facts]
    I --> P[Rubric and evidence completeness]
    O --> Q[Temporal / comparison analysis]
    P --> Q
    Q --> R[Grounded answer synthesis]
    R --> S[Claim and citation validation]
    S --> T[Answer + citations + limitations]
~~~~

### Luồng online

~~~~text
Question
  ↓
Validate scope
  ↓
Build RetrievalPlan
  ↓
Retrieve BM25 evidence (dense/hybrid optional)
  ↓
Validate citations and extract temporary facts
  ↓
Check evidence completeness
  ↓
Run rubric, temporal, comparison or screening analysis
  ↓
Generate deterministic answer or optional LLM synthesis
  ↓
Validate claims and attach limitations
~~~~

LLM, nếu được bật, chỉ hỗ trợ tổng hợp câu trả lời và tùy chọn kiểm tra grounding. Provenance, numeric checks, fact status, scope enforcement và acceptance vẫn là logic deterministic.

## Fact lifecycle và provenance

Đây là phần cốt lõi khác với chatbot đọc PDF:

~~~~text
PDF
 ↓
Stable chunk
 ↓
Fact candidate
 ↓
Validation / human review
 ├─ rejected
 ├─ conflict
 └─ accepted
       ↓
   Accepted ESG fact
       ↓
Temporal / comparison / audit
~~~~

Mỗi claim có thể truy ngược:

~~~~text
Claim → Evidence ID → Document → Page → Chunk → Fact candidate / accepted fact
~~~~

Ví dụ dữ liệu rút gọn:

~~~~json
{
  "metric": "scope_1_emissions",
  "value": 125000,
  "unit": "tCO2e",
  "year": 2025,
  "document_id": "example-report",
  "page": 42,
  "status": "CANDIDATE"
}
~~~~

Fact candidate chưa phải sự thật canonical. Chỉ fact đã được validator hoặc analyst chuyển sang ACCEPTED mới được dùng mặc định cho temporal và comparison.

## Retrieval, grounding và evaluation

BM25 là đường chạy mặc định vì có sẵn trong bộ cài đặt cơ bản. Dense retrieval, hybrid RRF
và cross-encoder chỉ là phần mở rộng; deterministic feature hashing chỉ phục vụ development/
testing và không được trình bày như semantic embedding.

| Thành phần | Cách kiểm tra |
|---|---|
| Retrieval | Recall@K, MRR, Precision@K, nDCG@K |
| Structured extraction | exact match, numeric tolerance, unit accuracy, year accuracy |
| Answer | citation correctness, faithfulness, completeness, unsupported claim rate |
| Gold evidence | citation precision và recall |
| Audit | disclosure coverage, evidence completeness, criterion-level matrix |

Các lệnh evaluation:

~~~~powershell
esg-analyst evaluate
esg-analyst benchmark
esg-analyst evaluate-answer
esg-analyst evaluate-extraction
python scripts/generate_reports.py
~~~~

Kết quả phụ thuộc corpus, retrieval mode và model tùy chọn nên không hard-code điểm benchmark vào README. Corpus demo và snapshot nằm ở data/demo/ và docs/CORPUS_SNAPSHOT.yaml.

## Cấu trúc dự án

~~~~text
Multi-Agent-ESG-Report-Analyst/
├─ app/
│  ├─ main.py                 FastAPI routes và lifecycle
│  ├─ pipeline.py             pipeline tuần tự duy nhất
│  ├─ models.py               Pydantic contracts và analysis context
│  ├─ store.py                SQLite, FTS5, chunks và fact lifecycle
│  ├─ document_service.py     PDF/OCR ingestion và indexing
│  ├─ document_intelligence.py parser, layout blocks và quality
│  ├─ query_plan.py           nhận diện intent và tạo truy vấn
│  ├─ retrieval.py            BM25/hybrid retrieval và citation mapping
│  ├─ answer.py               tổng hợp câu trả lời có bằng chứng
│  ├─ grounding.py             citation, claim và answer validation
│  ├─ domain/                 rubric, completeness, temporal, screening
│  ├─ extraction/             metric, unit, year và fact extraction
│  ├─ facts/repository.py     candidate/accepted fact persistence
│  ├─ services/               ESG rubric, matrix, temporal, comparison
│  ├─ llm.py                  optional synthesis/grounding client
│  ├─ evaluation.py           retrieval/extraction metrics
│  ├─ answer_eval.py          answer grounding metrics
│  └─ static/                 dashboard HTML/CSS/JavaScript
├─ data/demo/                 fixture text theo từng trang
├─ data/evaluation/           retrieval và answer cases
├─ rubrics/                   rubric YAML versioned
├─ docs/                      pipeline và corpus snapshot
├─ tests/                     unit, API, integration và regression tests
├─ reports/                  evaluation JSON sinh lại được
├─ scripts/                   tiện ích ingest/evaluation/report
├─ Dockerfile
├─ docker-compose.yml
├─ pyproject.toml
└─ README.md
~~~~

## Cài đặt

Yêu cầu Python 3.11+. OCR cho PDF scan cần Tesseract trong PATH; Docker image đã cài sẵn Tesseract.

~~~~powershell
git clone <repository-url>
cd Multi-Agent-ESG-Report-Analyst
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
~~~~

Cấu hình tùy chọn được đọc từ .env:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| DATABASE_PATH | data/esg.db | SQLite runtime |
| TOP_K | 6 | Số evidence tối đa cho query thường |
| MAX_FILE_SIZE | 78643200 | PDF tối đa 75 MiB |
| MAX_PDF_PAGES | 500 | Giới hạn số trang |
| USE_LLM | false | Bật local LLM cho synthesis/grounding |
| LLM_BASE_URL | http://localhost:11434/v1 | OpenAI-compatible endpoint |
| LLM_MODEL | qwen2.5:7b | Tên model local |
| RETRIEVAL_MODE | bm25 | bm25, dense, hybrid, hybrid_rerank |

Để bật dense/hybrid/reranker, cài thêm `pip install -e ".[ml]"` rồi chọn mode tương ứng.
Hằng số RRF mặc định là 60 và được giữ trong cấu hình nội bộ.

Mặc định project chạy offline-first và không phụ thuộc API trả phí.

## Chạy API, dashboard và CLI

~~~~powershell
python -m uvicorn app.main:app --reload
~~~~

Mở http://localhost:8000. Endpoint chính:

| Method | Endpoint | Mục đích |
|---|---|---|
| GET | /health | Health check và corpus stats |
| GET | /api/documents | Danh sách báo cáo đã index |
| POST | /api/documents | Upload và index PDF |
| POST | /api/search | Tìm evidence trực tiếp |
| POST | /api/analyze | Q&A hoặc audit theo mode |
| POST | /api/query | Evidence-grounded Q&A |
| POST | /api/audit | Disclosure audit và screening |
| POST | /api/temporal | Trend trên accepted facts |
| POST | /api/compare | So sánh disclosure giữa công ty |
| GET | /api/documents/{id}/metrics | Fact candidates của báo cáo |
| PATCH | /api/v1/facts/{fact_id} | Review ACCEPTED/REJECTED/CONFLICT |
| GET | /api/analysis/recent/trace | Trace tuần tự request gần nhất |

CLI:

~~~~powershell
esg-analyst stats
esg-analyst ingest --metadata C:\data\metadata.csv --reports-dir C:\data\reports
esg-analyst audit
esg-analyst compare --companies "Boeing,NextEra Energy,Alcoa"
~~~~

Chạy bằng Docker:

~~~~powershell
docker compose up --build
~~~~

## Quality gate và CI

CI workflow .github/workflows/ci.yml chạy trên Python 3.12:

1. cài package editable;
2. kiểm tra ruff format --check và ruff check;
3. chạy toàn bộ pytest;
4. import smoke test ESGPipeline và FastAPI app;
5. chạy retrieval gate với Recall@K và MRR;
6. build Docker image;
7. chạy container và gọi `GET /health`.

Chạy tương đương local:

~~~~powershell
python -m ruff check app tests scripts
python -m ruff format --check app tests scripts
python -m pytest -q
docker build -t esg-report-analyst:local .
docker run --rm -p 8000:8000 -e RETRIEVAL_MODE=bm25 esg-report-analyst:local
~~~~

## Giới hạn diễn giải

- Coverage đo độ hiện diện của bằng chứng trong corpus, không đo ESG performance.
- Extraction tạo candidate; review là bước bắt buộc trước khi dùng accepted-fact analysis.
- Citation validation kiểm tra metadata, page và excerpt, không phải assurance độc lập.
- Temporal/comparison báo thiếu năm hoặc thiếu fact thay vì tự suy luận trend.
- Greenwashing output chỉ là disclosure-risk screening signal, cần analyst review; không phải xác suất hay kết luận pháp lý.
- Dense retrieval, reranker và local LLM đều optional; BM25 deterministic là path mặc định.

## Tài liệu

- [Pipeline và data contracts](docs/PIPELINE.md)
- [Corpus snapshot](docs/CORPUS_SNAPSHOT.yaml)
