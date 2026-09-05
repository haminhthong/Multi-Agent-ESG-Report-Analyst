# Evidence-Grounded ESG Intelligence & Audit Platform 🛡️🌱

> **Nền tảng Trí tuệ và Kiểm toán Báo cáo Bền vững ESG Dựa trên Bằng chứng: Tích hợp Quy trình Canonical 2 Nhánh (Offline Ingestion & Online Audit), 6 Năng lực Cốt lõi được điều phối theo luồng xác định (Deterministic DAG), Truy xuất Hybrid (Dense + BM25 + Global RRF Fusion + Cross-Encoder Reranker), Bóc tách Số liệu Có cấu trúc với Chuẩn hóa Đơn vị (Unit Normalization), Sàng lọc Rủi ro Greenwashing Đa tín hiệu, và Khung Đánh giá Toàn diện 4 Tầng (4-Tier Evaluation).**

Dự án được xây dựng theo tiêu chuẩn công nghiệp khắt khe (**Production-Ready, Evidence-First, Clean Architecture**) phục vụ làm **Dự án Flagship #1** cho Hồ sơ cá nhân (CV / Portfolio) ứng tuyển các vị trí **Applied AI Engineer, Senior AI/MLOps Engineer, LLM Systems Engineer**.

---

## 🌟 Điểm Nhấn Kiến Trúc: Quy trình Canonical 2 Nhánh (Dual-Pipeline Architecture)

Khác với các hệ thống RAG demo thông thường, nền tảng phân định rạch ròi giữa nhánh **Nạp Kiến thức Ngoại tuyến** và nhánh **Kiểm toán Phân tích Trực tuyến**:

```
                         OFFLINE KNOWLEDGE PIPELINE

ESG / Sustainability PDF Reports
              ↓
1. DOCUMENT INGESTION & QUALITY GATE
   ├── PDF validation & SHA-256 identity
   ├── Text extraction ratio quality scoring
   └── OCR-required scan detection & rejection
              ↓
2. DOCUMENT INTELLIGENCE
   ├── Page classifier (native_text, table, scanned_image, mixed_page)
   ├── Tabular block extraction
   └── Layout preservation (heading, paragraph, table)
              ↓
3. CONTEXTUAL CHUNKING & ENRICHMENT
   ├── Layout-aware chunking (200-500 words, 50-word overlap)
   ├── Heading hierarchy & page metadata enrichment
   └── ESG Pillar tagging (Environmental, Social, Governance)
              ↓
4. HYBRID INDEXING
   ├── Sparse Lexical Index: SQLite FTS5 (BM25)
   └── Dense Semantic Index: MiniLM-L6-v2 Embeddings (JSON float vectors)

─────────────────────────────────────────────────────────────────────────────

                 ONLINE EVIDENCE-GROUNDED ANALYSIS PIPELINE

User Query / Audit Request (Web UI / REST API / CLI)
              ↓
5. ANALYTICAL INTENT & QUERY PLANNING (QueryPlanningAgent)
   ├── Intent classification (fact_lookup, criterion_audit, temporal_trend, etc.)
   ├── Multi-perspective subquery decomposition
   └── Required evidence specification
              ↓
6. MULTI-QUERY HYBRID RETRIEVAL & GLOBAL RRF FUSION (RetrievalAgent)
   ├── Parallel Sparse (BM25) + Dense Vector retrieval per subquery
   ├── Global Reciprocal Rank Fusion across all subqueries (RRF k=60)
   ├── Cross-Encoder Deep Contextual Reranking (ms-marco-MiniLM-L-6-v2)
   └── Semantic & Page Diversification (max 2 chunks / page)
              ↓
7. EVIDENCE VERIFICATION & COMPLETENESS GATE (EvidenceVerificationAgent)
   ├── Page boundary check & document identity verification
   ├── Provenance validation
   └── Evidence Completeness Gate: audits required fields vs retrieved evidence
              ↓
8. STRUCTURED FACT EXTRACTION & CONFLICT DETECTION (EvidenceExtractionAgent)
   ├── Span-based localized metric & year association (baseline vs reporting)
   ├── UnitNormalizer: canonical conversion to tCO2e, MWh, %
   └── Multidimensional Conflict Detection (metric + year + methodology grouping)
              ↓
9. ESG AUDIT MATRIX & GREENWASHING RADAR (ESGAuditAgent)
   ├── GRI/SASB Criteria Evaluation (status: found, partial, missing, contradicts)
   ├── Multi-Signal Greenwashing Screening (Target Credibility, Evidence Quality, Narrative Risk)
   └── Temporal YoY Analysis & Cross-Company Comparison
              ↓
10. GROUNDED EXPLANATION SYNTHESIS & AUDIT REPORT (ExplanationAgent)
   ├── LLM Synthesis or Deterministic Rule-Grounded Fallback ($0 API cost)
   ├── Post-generation Citation Grounding (validates all page citations)
   └── Trace Waterfall & Observability Emission (latency ms per capability)
```

---

## 🏛️ 6 Năng Lực Nghiệp Vụ Cốt Lõi (6 Core Capabilities)

Toàn bộ quy trình được điều phối theo một **Đồ thị Xác định Có hướng (Deterministic DAG Workflow)** qua 6 khối năng lực chuyên trách:

| Năng Lực | Thành phần Code | Vai trò Kỹ thuật & Nghiệp vụ |
|---|---|---|
| **1. Document Intelligence & Quality Gate** | `DocumentIngestionService`, `DocumentAgent` | Kiểm định tính toàn vẹn của PDF (SHA-256), chấm điểm chất lượng trích xuất text, nhận diện và từ chối tài liệu scan cần OCR (`OcrRequiredError`). |
| **2. Analytical Intent & Query Planning** | `QueryPlanningAgent`, `LLMClient` | Phân tích ý định câu hỏi thành `RetrievalPlan`, sinh subqueries đa chiều và xác định bằng chứng bắt buộc (`required_evidence`). |
| **3. Hybrid Retrieval & Global RRF Fusion** | `RetrievalAgent`, `SQLiteFTSStore` | Truy xuất song song BM25 (FTS5) và Dense MiniLM; hợp nhất điểm toàn cục bằng **Reciprocal Rank Fusion (RRF $k=60$)**, triệt tiêu bias thứ tự truy vấn con; rerank bằng Cross-Encoder và đa dạng hóa trang. |
| **4. Evidence Verification & Completeness Gate** | `EvidenceVerificationAgent` | Thẩm định số trang hợp lệ ($page \ge 1$); kiểm soát cổng độ đầy đủ bằng chứng (Evidence Completeness Gate); tự động ghi nhận các trường thiếu vào `limitations`. |
| **5. Structured Fact Extraction & Discrepancy Detection** | `EvidenceExtractionAgent`, `UnitNormalizer` | Bóc tách số liệu có cấu trúc (`ESGFact`); quét cửa sổ cục bộ để phân định năm cơ sở vs năm báo cáo; chuẩn hóa đơn vị về `tCO2e` và `MWh`; phát hiện mâu thuẫn số liệu đa chiều tránh báo động sai do khác phương pháp luận. |
| **6. ESG Audit Matrix, Greenwashing Radar & Grounded Synthesis** | `ESGAuditAgent`, `ExplanationAgent` | Đối soát ma trận tiêu chuẩn GRI/SASB (trạng thái: `found`, `partial`, `missing`, `contradicts`); tính độ phủ công bố; sàng lọc rủi ro tẩy xanh 3 chiều; tổng hợp báo cáo giải trình minh bạch dẫn nguồn số trang chính xác. |

---

## 📊 Khung Đánh giá Toàn diện 4 Tầng (4-Tier Evaluation Framework)

Hệ thống được kiểm chuẩn qua 4 tầng đo lường độc lập trên bộ dữ liệu thực tế đa ngành (**Boeing - Industrials**, **NextEra Energy - Energy**, **Alcoa - Materials**) với siêu dữ liệu và mã checksum được lưu trữ minh bạch tại [`reports/benchmark_manifest.json`](reports/benchmark_manifest.json):

### Tier 1: Retrieval Ablation Benchmark (21 Test Cases, Top-5)
| Cấu hình Retrieval | Recall@5 | MRR@5 | nDCG@5 | Precision@5 | Phân tích Kỹ thuật |
|---|---:|---:|---:|---:|---|
| **BM25 (SQLite FTS5)** | **1.00** | **0.90** | **0.92** | 0.25 | Bắt chính xác từ khóa định lượng (Scope 1, TRIR), nhưng nhạy cảm với cách dùng từ khác biệt |
| **Dense (MiniLM Vector)** | **1.00** | **0.92** | **0.94** | 0.25 | Bắt được ngữ nghĩa tương đồng cao, nhạy bén với câu hỏi diễn đạt tự nhiên |
| **Hybrid (BM25 + Dense RRF)** | **1.00** | **0.98** | **0.98** | 0.23 | **MRR & nDCG vượt trội**: Đưa bằng chứng chuẩn xác lên Rank 1 nhanh nhất nhờ thuật toán RRF fusion ($k=60$) |
| **Hybrid + Cross-Encoder Reranker** | **1.00** | **0.95** | **0.96** | 0.23 | Tái sắp xếp ứng viên theo ngữ cảnh câu hỏi, tối ưu hóa cửa sổ ngữ cảnh cho LLM |

### Tier 2: Structured Fact Extraction Benchmark
| Tiêu chí Đánh giá | Tỷ lệ Đạt | Ghi chú Triển khai |
|---|---:|---|
| **Exact Match** | **100.0%** | Khớp hoàn toàn cả giá trị số liệu, chỉ tiêu và năm báo cáo |
| **Numeric Tolerance Accuracy (5%)** | **100.0%** | Sai số số liệu định lượng nằm trong ngưỡng kiểm soát cho phép |
| **Unit Normalization Accuracy** | **100.0%** | Tự động quy đổi ktCO2e/MtCO2e về **tCO2e**, GWh về **MWh** |
| **Year Disambiguation Accuracy** | **100.0%** | Phân định rạch ròi giữa năm cơ sở (Baseline Year) và năm báo cáo (Reporting Year) |

### Tier 3: Faithfulness, Groundedness & Anti-Hallucination
* **Answer Faithfulness (Groundedness)**: **92.0%** — 92% khẳng định số liệu trong câu trả lời có bằng chứng trực tiếp hỗ trợ trong văn bản trích đoạn.
* **Citation Correctness**: **80.0%+** — Trích dẫn số trang chính xác dẫn chiếu về trang tài liệu PDF thực tế trong corpus.
* **Answer Completeness**: **90.0%** — Đáp ứng đầy đủ các khía cạnh thông tin câu hỏi yêu cầu.
* **Unsupported Claim Rate (Hallucination)**: Giảm mạnh xuống còn **8.0%** nhờ lớp Evidence Verification và Post-Generation Citation Grounding.

### Tier 4: ESG Rubric Coverage & Greenwashing Screening
* **Ma trận Bằng chứng chuẩn mực (Evidence Matrix)**: Tự động đối soát từng tiêu chí GRI 302/305/403/405/2-5 với các trạng thái rõ ràng (`found`, `partial`, `missing`, `contradicts`).
* **Sàng lọc Greenwashing Đa tín hiệu (Screening Radar)**:
  - *Target Credibility*: Phân tích cam kết Net-Zero, phát hiện thiếu năm cơ sở (Missing Baseline Year), kiểm tra mốc trung hạn 2030 (không tự suy diễn năm đích khi không có bằng chứng).
  - *Evidence Quality*: Đánh giá mật độ số liệu định lượng, kiểm tra bảo đảm độc lập (External Assurance) và nhận diện các tuyên bố phủ định (Negated Assurance / Increased Emissions).
  - *Narrative Risk*: Tính tỷ lệ từ ngữ tham vọng suông (`vague words`) so với số liệu chứng minh thực tế.

---

## 💻 Kiến trúc Thư mục Dự án

```
Multi-Agent-ESG-Report-Analyst/
├── app/
│   ├── agents.py               # 6 Core Capabilities & Supervisor DAG Orchestrator
│   ├── answer_eval.py          # Framework RAG Triad & Answer Faithfulness
│   ├── chunking.py             # Contextual Chunking, Layout Blocks & Section Detection
│   ├── cli.py                  # Giao diện dòng lệnh CLI (benchmark, eval, audit, compare)
│   ├── config.py               # Pydantic Settings & Cấu hình môi trường
│   ├── demo.py                 # Bộ nạp dữ liệu Demo đa ngành (Boeing, NextEra, Alcoa)
│   ├── document_service.py     # PDF Ingestion, Quality Gate & OCR Detection
│   ├── evaluation.py           # Engine đo lường Retrieval Ablation (Hit@K, MRR, nDCG)
│   ├── evidence_extractor.py   # UnitNormalizer, Fact Extraction & Conflict Detection
│   ├── llm.py                  # Local LLM Client (Ollama Qwen 2.5) & Fallback Engine
│   ├── main.py                 # FastAPI Application & REST API Endpoints v2.0.0
│   ├── models.py               # Pydantic Schemas (CriterionResult, ESGFact, Matrix)
│   ├── rubric.py               # Bộ tiêu chí ESG Rubric (GRI/SASB) & Regex Patterns
│   ├── store.py                # Storage Abstraction, SQLite FTS5 BM25 & Diversification
│   ├── tools.py                # Agent Tools Registry
│   └── static/                 # Modern Dark Emerald Web UI Dashboard
│       ├── app.js              # Client Controller (5 tabs, matrix, radar, waterfall)
│       ├── index.html          # Dashboard HTML với 5 Tab phân tích
│       └── style.css           # Modern Glassmorphism Design System
├── data/
│   ├── demo/                   # Báo cáo trích đoạn mẫu phục vụ thử nghiệm
│   └── evaluation/             # Bộ test cases benchmark độc lập (21 retrieval, 10 QA)
├── docs/
│   ├── ARCHITECTURE.md         # Tài liệu Kiến trúc 10 bước Canonical & 6 Capabilities
│   └── BENCHMARK_METHODOLOGY.md# Phương pháp luận đánh giá 4 tầng độc lập
├── reports/                    # Báo cáo thực nghiệm & Benchmark Manifest
│   ├── benchmark_manifest.json # Manifest theo dõi Git SHA, thông số và kết quả đo lường
│   ├── retrieval_ablation.json # Dữ liệu thực nghiệm Retrieval Ablation
│   └── extraction_eval.json    # Dữ liệu thực nghiệm Fact Extraction
├── tests/                      # Bộ kiểm thử tự động Pytest (52 tests passed 100%)
│   ├── test_agents.py          # Unit tests cho các Agent & Verifier
│   ├── test_answer_evaluation.py # Unit tests cho Answer Quality & Groundedness
│   ├── test_api.py             # Integration tests cho REST API endpoints
│   ├── test_batch_ingest.py    # Unit tests cho Batch Ingestion & Path Security
│   ├── test_behavioral.py      # Behavioral tests cho Failure modes, Units, Conflicts
│   ├── test_chunking.py        # Unit tests cho Chunking, Layout blocks & Pillar tagging
│   ├── test_counter_examples.py# Unit tests cho Phản ví dụ (Negation, Target, Abstention)
│   ├── test_document_service.py# Unit tests cho PDF Ingestion & OCR
│   ├── test_evaluation.py      # Unit tests cho công thức Recall@K, MRR, nDCG
│   ├── test_evidence_grounded_platform.py # Tests cho P0/P1 fixes (Units, Span Year, Gate)
│   ├── test_hybrid_retrieval.py# Unit tests cho BM25, Dense, RRF Fusion & Reranker
│   ├── test_llm_fallback.py    # Unit tests cho Local LLM & Heuristic Fallback
│   └── test_store.py           # Unit tests cho SQLite FTS5 Storage & Migration
├── Dockerfile                  # Đóng gói container an toàn (Non-root user)
├── docker-compose.yml          # Cấu hình Docker Compose
├── pyproject.toml              # Cấu hình Python, Pytest (--basetemp), Ruff
└── README.md                   # Tài liệu hướng dẫn toàn diện của dự án
```

---

## 🛠️ Hướng dẫn Cài đặt & Khởi chạy (Quick Start)

### Yêu cầu môi trường:
* Python `>= 3.11` (Khuyến nghị Python 3.11 - 3.13)
* Git

### Step 1: Cài đặt Môi trường

```powershell
# 1. Clone repository
git clone https://github.com/your-username/Multi-Agent-ESG-Report-Analyst.git
cd "Multi-Agent-ESG-Report-Analyst"

# 2. Tạo môi trường ảo Python
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Cài đặt các gói phụ thuộc
pip install -e ".[dev]"
```

### Step 2 (Tùy chọn): Kích hoạt Local LLM với Ollama ($0 API Cost)

Để kích hoạt chế độ **LLM Agentic Planning & LLM Synthesis**, chỉ cần khởi chạy Ollama:

```powershell
# Tải và chạy mô hình Qwen 2.5 hoặc Llama 3 cục bộ
ollama run qwen2.5:7b

# Tạo tệp .env và bật cờ USE_LLM
Copy-Item .env.example .env
# Chỉnh sửa .env: USE_LLM=true
```

*(Hệ thống tích hợp sẵn **Deterministic Heuristic Engine** với $0 chi phí, tự động kích hoạt khi chạy offline mà không yêu cầu thêm bất kỳ cấu hình nào).*

### Step 3: Khởi chạy Web Server & Dashboard

```powershell
python -m uvicorn app.main:app --reload
```

Truy cập ứng dụng tại:
* **Web Dashboard**: [http://localhost:8000](http://localhost:8000)
* **OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 💻 Sử dụng Công cụ Dòng lệnh CLI (`esg-analyst`)

```powershell
# 1. Chạy thực nghiệm bóc tách Retrieval Ablation Study (BM25, Dense, Hybrid, Reranker)
python -m app.cli benchmark --top-k 5

# 2. Chạy đánh giá độ chính xác bóc tách số liệu định lượng (Tier 2 Extraction)
python -m app.cli evaluate-extraction

# 3. Chạy đánh giá chất lượng câu trả lời và kiểm soát ảo giác (RAG Triad)
python -m app.cli evaluate-answer --top-k 5

# 4. Chạy kiểm toán toàn diện một báo cáo và xuất Evidence Matrix
python -m app.cli audit --document-id boeing_demo

# 5. So sánh chéo chất lượng công bố ESG giữa các doanh nghiệp
python -m app.cli compare --companies Boeing,Airbus

# 6. Xem thống kê tổng quan corpus đa ngành
python -m app.cli stats
```

---

## 🧪 Kiểm thử Tự động & Chuẩn hóa Mã nguồn (52 Tests Passed 100%)

```powershell
# 1. Kiểm tra Linter bằng Ruff (0 errors)
python -m ruff check app tests

# 2. Kiểm tra định dạng code Formatting
python -m ruff format --check app tests

# 3. Chạy toàn bộ 52 bài kiểm thử Pytest
python -m pytest
```

---

## 📝 Đưa Dự án vào Hồ sơ Cá nhân (CV / Resume Ready)

### 🇻🇳 Phiên bản Tiếng Việt

**Dự án: Evidence-Grounded ESG Intelligence & Audit Platform**
* **Tech Stack**: Python 3.11/3.13, FastAPI, SQLite FTS5, Sentence-Transformers, Cross-Encoder, Local LLMs (Ollama Qwen 2.5), PyMuPDF, Docker, GitHub Actions, Pytest.
* **Mô tả & Điểm nhấn Kỹ thuật**:
  - Thiết kế kiến trúc **Evidence-Grounded Intelligence & Audit Platform** với quy trình Canonical 2 nhánh (Offline Ingestion & Online Analysis), phân rã qua **6 Năng lực Nghiệp vụ Cốt lõi** được điều phối bằng đồ thị xác định (**Deterministic DAG Workflow**), đảm bảo 100% bằng chứng có số trang và trích đoạn đối soát thực tế.
  - Xây dựng giải pháp **Zero-Cost Local First Integration** kết nối Ollama kèm cơ chế **Deterministic Fallback tự động** đảm bảo hệ sinh thái vận hành 100% offline với $0 API cost.
  - Phát triển hệ thống **Multi-Stage Hybrid Retrieval Pipeline**: kết hợp BM25 RAG và Dense Vector Embeddings (`all-MiniLM-L6-v2`) qua thuật toán **Global Reciprocal Rank Fusion (RRF $k=60$)**, triệt tiêu bias thứ tự subquery, kết hợp tái xếp hạng bằng **Cross-Encoder Reranker (`ms-marco-MiniLM-L-6-v2`)** và khử trùng lặp trang bằng **Semantic Diversification**.
  - Thực hiện nghiên cứu thực nghiệm bóc tách (**Retrieval Ablation Study**) trên 21 ca kiểm thử đa ngành, chứng minh giải pháp Hybrid nâng chỉ số **MRR lên 0.98 và nDCG lên 0.98** so với các phương pháp đơn lẻ.
  - Thiết kế bộ bóc tách số liệu có cấu trúc (`ESGFact`) với **UnitNormalizer** tự động quy đổi về đơn vị chuẩn (`tCO2e`, `MWh`), thuật toán quét cửa sổ cục bộ tách bạch năm cơ sở với năm báo cáo, và cơ chế phát hiện mâu thuẫn số liệu đa chiều tránh báo động sai do khác biệt phương pháp luận (như *market-based* vs *location-based*).
  - Xây dựng **Ma trận Bằng chứng chuẩn mực (Evidence Matrix)** chuẩn hóa GRI/SASB với cổng kiểm soát độ đầy đủ (Evidence Completeness Gate), hệ thống **Sàng lọc Greenwashing Đa tín hiệu** (Target Credibility, Evidence Quality, Narrative Risk), phân tích xu hướng đa năm (Temporal YoY) và so sánh chéo doanh nghiệp (Cross-Company Comparison).
  - Triển khai bộ kiểm chuẩn tự động 4 tầng (**4-Tier Evaluation**) với **52 bài kiểm thử Pytest** đạt tỷ lệ thành công 100%.

---

### 🇬🇧 English Version

**Project: Evidence-Grounded ESG Intelligence & Audit Platform**
* **Tech Stack**: Python 3.11/3.13, FastAPI, SQLite FTS5, Sentence-Transformers, Cross-Encoder, Local LLMs (Ollama Qwen 2.5), PyMuPDF, Docker, GitHub Actions, Pytest.
* **Key Achievements**:
  - Architected an industrial **Evidence-Grounded Intelligence & Audit Platform** featuring a dual-pipeline architecture (Offline Ingestion & Online Analysis) organized across **6 Core Capabilities** orchestrated by a **Deterministic DAG Workflow** with strict page-level citation provenance.
  - Engineered a **Zero-Cost Local LLM Engine** supporting Ollama (Qwen 2.5 / Llama 3) with an instantaneous **Deterministic Fallback** guaranteeing 100% offline execution at $0 API cost.
  - Designed an advanced **Multi-Stage Hybrid RAG Pipeline**: fusing SQLite FTS5 BM25 and dense vector embeddings (`all-MiniLM-L6-v2`) via **Global Reciprocal Rank Fusion (RRF $k=60$)** to eliminate subquery ordering bias, topped by a **Cross-Encoder Reranker (`ms-marco-MiniLM-L-6-v2`)** and semantic page diversification.
  - Executed a rigorous **Retrieval Ablation Study** across 21 multi-sector test cases, demonstrating that Hybrid Fusion elevates **MRR to 0.98 and nDCG to 0.98** over single-strategy baselines.
  - Built a structured data extraction engine (`ESGFact`) equipped with **UnitNormalizer** (standardizing GHG to `tCO2e` and energy to `MWh`), metric-span localized year extraction (disambiguating baseline vs reporting years), and multidimensional conflict detection that prevents false alarms across disparate accounting methodologies (e.g., market-based vs location-based).
  - Built an automated **GRI/SASB Evidence Matrix** with an Evidence Completeness Gate, a **Multi-Signal Greenwashing Screening Radar** (Target Credibility, Evidence Quality, Narrative Risk), multi-year Temporal trend analysis, and Cross-Company comparison tooling.
  - Established a **4-Tier Evaluation Framework** validated by a robust suite of **52 automated Pytest tests** with 100% pass rate.

---

## 📜 Giấy phép & Tuyên bố miễn trừ trách nhiệm (Disclaimer)

* Dự án được phát hành theo giấy phép MIT.
* *Tuyên bố miễn trừ*: Hệ thống đóng vai trò công cụ sàng lọc minh bạch thông tin bằng chứng (evidence-first screening), không thay thế cho các khuyến nghị đầu tư hoặc ý kiến kiểm toán chính thức.
