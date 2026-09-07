# Multi-Agent ESG Report Analyst
### Agentic Climate Disclosure Evidence Review

> **Hệ thống rà soát bằng chứng công bố khí hậu theo từng tiêu chí**, kết hợp phân tích layout tài liệu thực (PyMuPDF layout blocks + genuine bboxes + OCR recovery), truy xuất lai BM25/Dense + Reciprocal Rank Fusion (RRF), trích xuất fact candidate có provenance, kiểm tra tính đầy đủ của bằng chứng và grounding khẳng định cấp câu. Hệ thống đo mức độ hiện diện của bằng chứng trong tài liệu, không chấm hiệu quả ESG hay kết luận greenwashing.

> **Tuyên bố miễn trừ trách nhiệm:** Hệ thống này là **công cụ thông minh hỗ trợ phân tích, thẩm tra và sàng lọc rủi ro công bố** (Intelligence & Screening Tool), không thay thế ý kiến kiểm toán độc lập theo chuẩn ISAE 3000, tư vấn pháp lý hay xếp hạng tín nhiệm ESG thương mại. Mọi nhận định, điểm số và cảnh báo đều được ràng buộc nghiêm ngặt với bằng chứng có trích dẫn xuất xứ từ tài liệu nguồn.

---

## 1. Mục lục
1. [Bài toán & Định vị hệ thống](#2-bài-toán--định-vị-hệ-thống)
2. [Ranh giới hệ thống (System Boundaries)](#3-ranh-giới-hệ-thống-system-boundaries)
3. [Kiến trúc Canonical (Architecture)](#4-kiến-trúc-canonical-architecture)
4. [Document Intelligence & Ingestion](#5-document-intelligence--ingestion)
5. [Lập chỉ mục & Quản lý tri thức (Knowledge Ingestion)](#6-lập-chỉ-mục--quản-lý-tri-thức-knowledge-ingestion)
6. [Truy xuất đơn tầng & Tối ưu hóa RRF (Hybrid Retrieval)](#7-truy-xuất-đơn-tầng--tối-ưu-hóa-rrf-hybrid-retrieval)
7. [Mô hình dữ liệu sự thật ESG & Fact Store](#8-mô-hình-dữ-liệu-sự-thật-esg--fact-store)
8. [Evidence Completeness Gate có hành động](#9-evidence-completeness-gate-có-hành-động)
9. [Thẩm định chi tiết theo tiêu chí (Criterion-Level Audit)](#10-thẩm-định-chi-tiết-theo-tiêu-chí-criterion-level-audit)
10. [Phát hiện mâu thuẫn công bố đa chiều (Conflict Detection)](#11-phát-hiện-mâu-thuẫn-công-bố-đa-chiều-conflict-detection)
11. [Sàng lọc rủi ro Greenwashing (Risk Screening)](#12-sàng-lọc-rủi-ro-greenwashing-risk-screening)
12. [Phân tích chuỗi thời gian & So sánh doanh nghiệp](#13-phân-tích-chuỗi-thời-gian--so-sánh-doanh-nghiệp)
13. [Tổng hợp câu trả lời & Xác thực grounding (Claim-Level Grounding)](#14-tổng-hợp-câu-trả-lời--xác-thực-grounding-claim-level-grounding)
14. [Hệ thống đánh giá 4 tầng (Evaluation Framework)](#15-hệ-thống-đánh-giá-4-tầng-evaluation-framework)
15. [Tính tái lập & Dữ liệu kiểm thử (Reproducibility)](#16-tính-tái-lập--dữ-liệu-kiểm-thử-reproducibility)
16. [API, CLI & Khả năng quan sát (Trace Waterfall)](#17-api-cli--khả-năng-quan-sát-trace-waterfall)
17. [Giới hạn hiện tại (Limitations)](#18-giới-hạn-hiện-tại-limitations)
18. [Lộ trình phát triển (Roadmap)](#19-lộ-trình-phát-triển-roadmap)

---

## 2. Bài toán & Định vị hệ thống

### 2.1 Bản chất bài toán
Báo cáo phát triển bền vững của doanh nghiệp thường là tài liệu từ 100 đến hơn 300 trang PDF chứa đựng:
- Cấu trúc trình bày hỗn hợp: văn bản tường thuật (PR narrative), bảng biểu tài chính - phi tài chính phức tạp, hộp thông tin phụ và biểu đồ đồ họa.
- Không đồng nhất về chuẩn mực đo lường: đơn vị phát thải thay đổi giữa `tCO2e`, `ktCO2e`, `MtCO2e`; phương pháp luận phát thải phân nhánh giữa `market-based` và `location-based`; chỉ tiêu tổng hợp `gross` vs `net`.
- Rủi ro Greenwashing tinh vi: công bố mục tiêu Net-Zero tham vọng (ví dụ: năm 2050) nhưng không có năm cơ sở (baseline year), không rõ ranh giới tổ chức (Scope 1/2 hay có cả Scope 3), hoặc công bố số liệu mâu thuẫn giữa các trang khác nhau.

### 2.2 Vì sao không dùng Naive RAG?
Kiến trúc Naive RAG (chunking kích thước cố định + vector search thuần túy + prompt trực tiếp vào LLM) thất bại hoàn toàn trong bài toán kiểm toán ESG:

| Nhược điểm Naive RAG | Hậu quả trong thẩm định ESG | Giải pháp của Evidence-Grounded ESG Platform |
| :--- | :--- | :--- |
| **Fixed-size chunking thô bạo** | Bảng số liệu bị cắt đôi, chỉ số tách rời tiêu đề cột và đơn vị | **Structure-Aware Chunking**: giữ nguyên khối bảng (`table`), tiêu đề (`heading`), không gộp xuyên trang |
| **Mất dấu nguồn gốc (Provenance)** | Trích dẫn chung chung "theo báo cáo của công ty" | **Stable Provenance**: mỗi chunk có `stable_chunk_id` (SHA-256), `content_hash`, số trang PDF thực, tọa độ `bbox` |
| **Nhầm lẫn năm báo cáo và năm cơ sở** | Lấy nhầm năm baseline 2019 gán cho phát thải năm 2024 | **Proximity Year Resolver**: phân tích ngữ cảnh cục bộ ±120 ký tự, tách bạch `reporting_year` ↔ `baseline_year` |
| **Rerank 2 lần gây suy giảm thứ hạng** | Store rerank rồi Agent rerank lại theo subquery đầu tiên | **Single-Pass Reranking**: Store chỉ làm primitive, Agent làm fusion + ONE Cross-Encoder trên `canonical_query` |
| **Thiếu bằng chứng nhưng vẫn phán đoán** | LLM tự suy diễn hoặc bịa số liệu khi không tìm thấy | **Active Evidence Completeness Gate**: bắt buộc đủ các trường định lượng, kích hoạt targeted retry trước khi kết luận |
| **Thẩm định lỏng lẻo bằng Top-K chung** | Lấy 12 chunk chung cho câu hỏi để chấm 13 tiêu chí | **Criterion-Level Audit**: mỗi tiêu chí rubric được retrieval riêng biệt, đánh giá fact-first |

### 2.3 Luồng nghiệp vụ cốt lõi
```
ESG Reports (PDF)
       ↓
Knowledge Base & Fact Store
       ↓
User Question / Audit Request
       ↓
Evidence Retrieval (Hybrid RRF)
       ↓
Structured ESG Facts
       ↓
Verification & Completeness Gate (Targeted Retry)
       ↓
ESG Analysis (Pillar / Conflict / Greenwashing)
       ↓
Grounded Answer / Audit Report
```

---

## 3. Ranh giới hệ thống (System Boundaries)

Hệ thống được thiết kế theo nguyên tắc **Local-First & Evidence-Bound**:
1. **Local-First Runtime ($0 API Cost)**: Toàn bộ quá trình ingestion, FTS5 BM25, dense embeddings (`sentence-transformers/all-MiniLM-L6-v2`), cross-encoder reranking (`ms-marco-MiniLM-L-6-v2`) và rule-based extraction/screening chạy cục bộ 100% trên CPU/GPU máy chủ mà không bắt buộc phải gọi API ngoài.
2. **Deterministic Backing**: Kết quả phân tích số liệu, bảng kiểm toán và cảnh báo greenwashing được tính toán từ Fact Store và Rule Engine bằng code tất định (deterministic), không phụ thuộc vào nhiệt độ (temperature) hay tính bất định của LLM.
3. **LLM Bounded Synthesis**: LLM chỉ được sử dụng ở khâu tổng hợp ngôn ngữ tự nhiên cuối cùng (`ExplanationAgent`) và bị ràng buộc nghiêm ngặt: mọi khẳng định phải có trích dẫn `[C1]`, `[C2]`, số trang thực tế và được đối chiếu qua Claim-Level Grounding Check.

---

## 4. Kiến trúc Canonical (Architecture)

### 4.1 Supervisor Agent & Agent Handoff Graph

Luồng online được điều phối bằng một graph agent có giới hạn bước trong
`app/agent_runtime.py`, thay vì để các agent gọi lẫn nhau tự do:

```text
ScopeAgent
  → QueryPlanningAgent
  → RetrievalAgent
  → EvidenceVerificationAgent
  → EvidenceExtractionAgent
  → EvidenceCompletenessGate
  → ESGAuditAgent
  → ClaimVerificationAgent
  → ExplanationAgent
  → AnswerReviewAgent
  → LimitationsAgent
```

Supervisor đọc `AnalysisState` sau mỗi handoff để quyết định bước kế tiếp:

- Không có evidence: bỏ qua extraction và đi thẳng đến completeness gate.
- Có intent `temporal_trend` hoặc `cross_document_compare`: thêm
  `SpecializedAnalysisAgent`.
- Evidence không đủ: giữ kết quả ở trạng thái giới hạn, không suy diễn.
- AnswerReviewAgent kiểm tra lại citation sau mọi bước augment; answer không
  grounded sẽ được regenerate bằng fallback an toàn hoặc abstain.

Mỗi request trả về `requested_agent_mode`, `agent_mode`, `agent_route`,
`agent_stop_reason` và `trace_steps`. Có thể chọn:

```json
{"agent_mode": "agentic"}
```

`agentic` dùng LLM cho structured planning nếu khả dụng; `orchestrated` dùng
graph tất định; `deterministic` tắt LLM hoàn toàn.

### A. Offline / Knowledge Ingestion Pipeline
```
PDF ESG Reports
       ↓
1. DOCUMENT VALIDATION (MIME / Magic Bytes %PDF- / Size / SHA-256 Idempotency)
       ↓
2. DOCUMENT INTELLIGENCE (PyMuPDF real bboxes / Table extraction / Tesseract OCR recovery)
       ↓
3. EXTRACTION QUALITY GATE (Native text ratio / OCR ratio / Empty pages / Parser confidence)
       ↓
4. STRUCTURE-AWARE CHUNKING (Heading-aware / Table-preserved / Stable Chunk ID / Content Hash)
       ↓
5. DUAL RETRIEVAL INDEX (SQLite FTS5 BM25 + Dense Embeddings)
       ↓
6. VERSIONED ESG KNOWLEDGE BASE & FACT STORE
```

### B. Online QA Pipeline
```
User Question
       ↓
Query Planning (Intent classification + Canonical Query + Typed Requirements)
       ↓
Multi-Query Retrieval (BM25 + Dense parallel execution)
       ↓
Reciprocal Rank Fusion (RRF) across subqueries
       ↓
ONE Cross-Encoder Rerank (chấm điểm trên candidate pool bằng canonical_query)
       ↓
Citation Validation (Kiểm tra excerpt và metadata thực)
       ↓
Structured ESG Fact Extraction (Regex + Unit Normalizer + Year Resolver)
       ↓
Fact Store Persistence (`esg_facts`)
       ↓
Evidence Completeness Gate
   ├── Missing Evidence? → Targeted Retrieval Retry → Re-check
   └── Satisifed / Final Incomplete → PARTIAL / ABSTAIN status
       ↓
Claim Grounding & Numeric Verification
       ↓
Grounded Answer ([C1], [C2] citations)
```

### C. Criterion-Level Audit Pipeline
Khác hoàn toàn với việc lấy một tập hợp Top-12 chunks dùng chung cho mọi tiêu chí, pipeline kiểm toán phân rã độc lập theo từng tiêu chí trong bộ Rubric chuẩn mực:
```
Selected ESG Report
       ↓
Rubric Criteria (E1..E5, S1..S5, G1..G5)
       ↓
FOR EACH CRITERION:
   ├── Criterion-specific retrieval (Top-5 chunks theo từ khóa chuyên biệt)
   ├── Validate evidence & chunk provenance
   ├── Extract structured facts
   ├── Required-fields check (value, unit, reporting_year, methodology)
   └── Assign status: FOUND / PARTIAL / MISSING / CONTRADICTS / UNCLEAR
       ↓
Evidence Matrix Construction
       ↓
Disclosure Coverage Calculation
       ↓
Multidimensional Conflict Detection (Cross-page discrepancies)
       ↓
Greenwashing Risk Screening (Signals + Severity)
       ↓
Comprehensive Audit Report
```

---

## 5. Document Intelligence & Ingestion

Trước đây, việc phân tích PDF chỉ đọc text thô qua `pypdf` và giả lập bounding box (`bbox=None`). Trong phiên bản mới, module `app/ingestion/` giải quyết triệt để:

### 5.1 PyMuPDF Real Layout Parser (`app/ingestion/layout_parser.py`)
- Sử dụng `fitz.open()` (PyMuPDF) để trích xuất cấu trúc trang.
- Đọc từng khối văn bản thông qua `page.get_text("blocks")`, thu được tọa độ chữ nhật thực tế `[x0, y0, x1, y1]`.
- Tự động nhận diện cấu trúc bảng thông qua `page.find_tables()`, trích xuất ma trận dữ liệu và tạo Markdown table nguyên vẹn kèm theo `bbox` bao quanh toàn bộ bảng.
- Phân loại khối thành: `heading`, `table`, `text`, `figure`.

### 5.2 Phục hồi OCR tự động (`app/document_service.py` & `app/ingestion/ocr.py`)
- Khi trang có tỷ lệ text số hóa thấp (`native_text_ratio < 0.20`), hệ thống không đơn thuần báo lỗi dừng chương trình.
- `DocumentIngestionService` tự động kết nối với `TesseractOCRProvider` (hoặc bất kỳ `OCRProvider` tuân thủ protocol):
  1. Render trang PDF thành hình ảnh độ phân giải cao (`page.get_pixmap(dpi=300)`).
  2. Thực thi OCR để phục hồi các khối chữ và số liệu.
  3. Gán cờ `source_method="ocr"` và gán điểm chất lượng `quality_score`.

---

## 6. Lập chỉ mục & Quản lý tri thức (Knowledge Ingestion)

### 6.1 Stable Chunk ID & Content Hash (`app/chunking.py`)
Để phục vụ yêu cầu kiểm toán tái lập (Reproducible Audit), các chunk không thể chỉ dựa vào cột `chunks.id AUTOINCREMENT` trong database vì ID này có thể thay đổi sau mỗi lần re-index. Mỗi chunk được gán:
```python
content_hash = SHA256(chunk_text)[:16]
stable_chunk_id = SHA256(f"{company}:{year}:{page}:{block_id}:{chunk_index}:{content_hash}")[:16]
```
Nhờ đó:
- Dù cơ sở dữ liệu được khởi tạo lại ở bất kỳ môi trường nào, `stable_chunk_id` vẫn giữ nguyên giá trị.
- Mọi citation trích dẫn trong báo cáo kiểm toán có thể truy ngược chính xác về đúng block và văn bản gốc.

### 6.2 Cấu trúc cơ sở dữ liệu SQLite FTS5 (`app/store.py`)
Cơ sở dữ liệu trung tâm gồm 4 bảng cốt lõi:
1. `documents`: Lưu trữ thông tin tài liệu, SHA-256 hash, năm báo cáo, công ty, lĩnh vực và chỉ số chất lượng trích xuất.
2. `chunks`: Lưu trữ từng đoạn văn bản, `page`, `section_title`, `block_type`, `block_id`, `pillar`, `stable_id`, `content_hash`.
3. `chunks_fts`: Bảng ảo SQLite FTS5 phục vụ tìm kiếm toàn văn BM25 cực nhanh với trigger đồng bộ tự động.
4. `chunk_embeddings`: Lưu trữ vector nhúng 384 chiều (`all-MiniLM-L6-v2`) dưới dạng JSON.
5. `esg_facts`: Fact Store lưu trữ các sự thật số liệu đã được chuẩn hóa.

---

## 7. Truy xuất đơn tầng & Tối ưu hóa RRF (Hybrid Retrieval)

### 7.1 Giải quyết triệt để vấn đề Double Reranking
Trong các kiến trúc RAG thông thường, cả tầng Store và tầng Agent cùng gọi Cross-Encoder Reranker khiến một câu hỏi bị rerank 2 lần liên tiếp. Điều này gây lãng phí tài nguyên và làm xáo trộn thứ hạng của các subquery:
- **Nguyên tắc phân tầng mới**:
  - `Store.search()`: Chỉ chịu trách nhiệm cung cấp các phương thức tìm kiếm nguyên thủy (`bm25`, `dense`, `hybrid_rrf`). Tuyệt đối không tự ý rerank.
  - `RetrievalAgent.run_plan()`: Chịu trách nhiệm điều phối đa truy vấn:
    1. Chạy song song từng subquery qua Store.
    2. Gom các kết quả và hợp nhất bằng **Cross-Query RRF**.
    3. Lấy Top-20 candidate pool.
    4. Chạy **MỘT LẦN DUY NHẤT Cross-Encoder Reranker** sử dụng `canonical_query` (câu hỏi chuẩn hóa tổng thể, tránh việc chỉ rerank theo subquery đầu tiên).
    5. Khử trùng lặp đa dạng hóa nguồn (`Diversification` tối đa 2 chunk/trang).

### 7.2 Lý do chọn `retrieval_mode = "hybrid"` làm mặc định
Dựa trên kết quả đo lường khách quan trong bộ benchmark thực tế (`reports/benchmark_manifest.json`):

| Cấu hình Retrieval | MRR@5 | nDCG@5 | Recall@5 |
| :--- | :---: | :---: | :---: |
| BM25 thuần túy | 0.9048 | 0.9238 | 0.9524 |
| Dense thuần túy | 0.9206 | 0.9410 | 0.9524 |
| **Hybrid RRF (BM25 + Dense)** | **0.9762** | **0.9824** | **1.0000** |
| Hybrid + Reranker (ms-marco) | 0.9524 | 0.9648 | 1.0000 |

Thực nghiệm cho thấy trên tập dữ liệu ESG kỹ thuật, Cross-Encoder tổng quát có xu hướng hạ điểm các bảng số liệu ngắn nhưng chứa thông tin mật độ cao. Do đó, hệ thống cấu hình mặc định:
```ini
RETRIEVAL_MODE=hybrid
```
và bảo lưu chế độ `hybrid_rerank` như một tùy chọn cấu hình cao cấp.

---

## 8. Mô hình dữ liệu sự thật ESG & Fact Store

Thay vì trích xuất số liệu tạm bợ qua regex ở mỗi request rồi vứt bỏ, hệ thống triển khai **Fact Store** (`app/facts/repository.py` & bảng `esg_facts` trong SQLite) đóng vai trò Single Source of Truth cho toàn bộ nền tảng.

### 8.1 Cấu trúc thực thể `ESGFact`
```
ESGFact
├── fact_id                 : Hash định danh ổn định của sự thật số liệu
├── company                 : Doanh nghiệp công bố (ví dụ: Boeing, Alcoa)
├── document_id             : Báo cáo nguồn
├── metric                  : Chỉ số chuẩn hóa (scope_1_emissions, net_zero_target...)
├── raw_value / raw_unit    : Giá trị và đơn vị nguyên bản trong tài liệu (e.g. 12.5 ktCO2e)
├── normalized_value / unit : Giá trị và đơn vị đã chuẩn hóa (e.g. 12,500.0 tCO2e)
├── reporting_year          : Năm công bố số liệu
├── baseline_year           : Năm cơ sở đối chiếu (nếu có)
├── target_year             : Năm đích cam kết (nếu có)
├── methodology             : Phương pháp tính (market-based, location-based, gross, net)
├── organizational_boundary : Ranh giới (global operations, manufacturing sites...)
├── page / chunk_id         : Xuất xứ số trang PDF và mã chunk
├── confidence              : Độ tin cậy trích xuất (0.0 - 1.0)
└── status                  : Vòng đời fact (CANDIDATE, ACCEPTED, REJECTED, CONFLICT)
```

### 8.2 Proximity Target Year Resolver (`app/extraction/year_resolver.py`)
Khắc phục lỗi bắt nhầm năm trong câu cam kết:
*Ví dụ câu:* `"In 2024, the corporation reaffirmed our net-zero target for 2050 against a 2018 baseline."*
- Regex cũ bắt năm đầu tiên `2024` → gán sai mục tiêu thành 2024.
- Hàm `resolve_target_year()` mới:
  1. Xác định vị trí span của cụm từ khóa mục tiêu (`net-zero`, `target`, `reduction goal`).
  2. Quét trong bán kính ±100 ký tự để tìm các năm khả dĩ.
  3. Loại trừ dứt khoát `reporting_year` (2024) và `baseline_year` (2018).
  4. Lựa chọn năm tương lai gần cụm từ khóa mục tiêu nhất → trích xuất chính xác `target_year = 2050`.

---

## 9. Evidence Completeness Gate có hành động

`EvidenceCompletenessGate` (`app/domain/evidence_completeness.py`) không chỉ là một reporter thụ động ghi nhận thiếu sót, mà đóng vai trò là một **Quality Gate điều khiển luồng thực thi**:

### 9.1 Hợp đồng bằng chứng định kiểu (Typed Requirements)
Mỗi yêu cầu bằng chứng hỗ trợ các điều kiện logic chặt chẽ:
```python
EvidenceRequirement(
    name="scope_1_2",
    all_of=["scope_1_emissions", "scope_2_emissions"],
    required_fields=["value", "unit", "reporting_year"],
)
```
- Loại bỏ bug logic: Nếu người dùng hỏi Scope 1 và Scope 2, hệ thống **bắt buộc phải có cả 2 facts**. Nếu chỉ tìm thấy Scope 1, requirement sẽ đánh dấu `partial`, không bao giờ được coi là `satisfied`.

### 9.2 Targeted Retrieval Retry trong Workflow (`app/workflow.py`)
Khi `EvidenceCompletenessGate` phát hiện thiếu bằng chứng trọng yếu:
1. Hệ thống không vội vàng chuyển sang tổng hợp câu trả lời thiếu sót.
2. Workflow tự động kích hoạt `_targeted_retrieval_retry(state)`.
3. Tạo ra các subquery tập trung chính xác vào các khía cạnh còn thiếu (ví dụ: truy vấn chuyên sâu cho `scope_2_emissions`).
4. Bổ sung các chunk mới vào tập bằng chứng, trích xuất lại fact và tái đánh giá cổng chất lượng.
5. Nếu vẫn thiếu sau khi retry → hệ thống ghi nhận trạng thái `partial` hoặc `abstain`, thông báo rõ ràng trong mục `limitations` thay vì suy diễn.

---

## 10. Thẩm định chi tiết theo tiêu chí (Criterion-Level Audit)

### 10.1 Khắc phục Retrieval Coverage Bias
Trong các hệ thống RAG thông thường, chế độ audit chạy 8 query chung chung rồi lấy Top-12 chunks để đánh giá toàn bộ 13 tiêu chí rubric. Điều này dẫn tới ngụy biện: *Tiêu chí không xuất hiện trong Top-12 không đồng nghĩa với việc doanh nghiệp không công bố*.

Trong kiến trúc mới:
- Với mỗi tiêu chí trong bộ Rubric (13 tiêu chí E/S/G), hệ thống kích hoạt một chu trình thu thập bằng chứng độc lập:
  `retrieve_for_criterion()` → `validate()` → `extract_facts()` → `evaluate_criterion()`.

### 10.2 Fact-First Evaluation (`app/domain/rubric_evaluator.py`)
- Thay vì quét text bằng regex bề mặt, `RubricEvaluator` ưu tiên thẩm định dựa trên **các sự thật số liệu có cấu trúc (`ESGFact`)**.
- Thẩm định trường bắt buộc: Một tiêu chí như `Scope 1 & 2` chỉ đạt trạng thái `FOUND` khi và chỉ khi:
  - Có fact Scope 1 đầy đủ (`value`, `unit`, `reporting_year`).
  - Có fact Scope 2 đầy đủ (`value`, `unit`, `reporting_year`).
  - Nếu chỉ có 1 trong 2 hoặc thiếu đơn vị → xếp hạng `PARTIAL`.
  - Nếu hoàn toàn không có bằng chứng hợp lệ → xếp hạng `MISSING`.

### 10.3 Chuẩn hóa 5 trạng thái thẩm định
Toàn bộ hệ thống thống nhất 5 trạng thái ngữ nghĩa:
- **`FOUND`**: Đầy đủ bằng chứng và mọi trường dữ liệu bắt buộc.
- **`PARTIAL`**: Có bằng chứng nhưng thiếu một phần số liệu hoặc thiếu trường định lượng.
- **`MISSING`**: Không tìm thấy bằng chứng sau khi đã kích hoạt truy xuất chuyên biệt.
- **`CONTRADICTS`**: Phát hiện bằng chứng phủ định hoặc có mâu thuẫn số liệu nội tại.
- **`UNCLEAR`**: Có đề cập trong văn bản nhưng câu từ mơ hồ, không đủ căn cứ xác nhận.

---

## 11. Phát hiện mâu thuẫn công bố đa chiều (Conflict Detection)

### 11.1 Cách ly mâu thuẫn đa doanh nghiệp (`app/extraction/fact_validator.py`)
Một lỗi nghiêm trọng trong các hệ thống trích xuất là gộp khóa mâu thuẫn theo `(metric, methodology, year)`. Khi phân tích so sánh:
- Boeing Scope 1 năm 2024 = 450,000 tCO2e.
- Alcoa Scope 1 năm 2024 = 120,000 tCO2e.
Nếu không có `company` trong khóa, hệ thống sẽ báo động giả mạo rằng tài liệu công bố mâu thuẫn số liệu!

Hệ thống đã chuẩn hóa khóa mâu thuẫn 6 chiều:
```
Conflict Key = (company, metric, reporting_year, methodology, organizational_boundary, normalized_unit)
```
Nhờ đó:
- Dữ liệu giữa các công ty khác nhau hoàn toàn độc lập, không gây xung đột giả.
- Phát thải `market-based` và `location-based` của cùng một năm được phân định rõ ràng.
- Chỉ kích hoạt cảnh báo `EvidenceConflict` khi **cùng một công ty, cùng chỉ số, cùng năm, cùng phương pháp luận** nhưng số liệu công bố chênh lệch bất thường giữa các trang báo cáo.

---

## 12. Sàng lọc rủi ro Greenwashing (Risk Screening)

Module `GreenwashingScreeningService` (`app/domain/screening.py`) tích hợp bộ luật suy luận phát hiện các tín hiệu greenwashing theo các khuyến nghị quốc tế:
- **`GW01 — Vague Net-Zero Target`**: Cam kết phát thải ròng bằng 0 nhưng không nêu rõ năm đích thực hiện.
- **`GW02 — Missing Baseline Year`**: Công bố tỷ lệ cắt giảm phần trăm ấn tượng (ví dụ: "giảm 40% phát thải") nhưng giấu năm cơ sở so sánh.
- **`GW03 — Selective Scope Disclosure`**: Chỉ công bố Scope 1 hoặc Scope 2, hoàn toàn bỏ qua Scope 3 mặc dù hoạt động kinh doanh phụ thuộc nặng vào chuỗi cung ứng.
- **`GW04 — Unverified High-Risk Claim`**: Cam kết môi trường mạnh mẽ nhưng không có báo cáo bảo đảm độc lập từ bên thứ ba (External Assurance theo ISAE 3000 / ISO 14064-3).
- **`GW05 — Discrepant Disclosures`**: Số liệu mâu thuẫn giữa các phần trong cùng một báo cáo.

Mỗi tín hiệu đi kèm cấp độ rủi ro (`HIGH`, `MEDIUM`, `LOW`), giải thích nguyên nhân và trích dẫn số trang bằng chứng đối chiếu.

---

## 13. Phân tích chuỗi thời gian & So sánh doanh nghiệp

Nhờ Fact Store thống nhất, hai tính năng nâng cao được vận hành mượt mà:
1. **Temporal Analysis (`app/domain/temporal_analysis.py`)**:
   - Truy vấn chuỗi thời gian đa năm của một chỉ số theo công ty: `repo.get_temporal_series(company, metric)`.
   - Tính toán tốc độ thay đổi YoY (Year-over-Year), phát hiện sự sụt giảm hoặc tăng đột biến bất thường.
2. **Company Comparison (`app/domain/company_comparison.py`)**:
   - Truy vấn các facts đồng chuẩn của nhiều doanh nghiệp: `repo.get_cross_company_facts(companies, metric)`.
   - So sánh trực tiếp trên cùng một đơn vị chuẩn hóa (ví dụ: quy đổi toàn bộ phát thải về `tCO2e`, năng lượng về `MWh`), đảm bảo tính công bằng và minh bạch khi đối sánh.

---

## 14. Tổng hợp câu trả lời & Xác thực grounding (Claim-Level Grounding)

Tầng ngôn ngữ tự nhiên (`app/capabilities/explanation.py` & `app/capabilities/verification.py`) áp dụng cơ chế bảo vệ 3 lớp:
1. **Citation Provenance Binding**: Mọi khẳng định trong câu trả lời bắt buộc phải gắn thẻ trích dẫn `[C1]`, `[C2]`.
2. **Numeric Cross-Check**: Mọi con số xuất hiện trong câu trả lời phải được tìm thấy trong đoạn trích dẫn tương ứng. Nếu LLM tự bịa một con số, câu trả lời sẽ bị từ chối ngay lập tức.
3. **Claim-Level Semantic Verification**:
   - Sử dụng `ClaimSplitter` để tách câu trả lời thành các khẳng định nguyên tử.
   - Đối chiếu từng khẳng định với bằng chứng trích dẫn cục bộ.
   - Khi có nghi ngờ, kích hoạt `LLMClient.verify_grounding()` thực hiện kiểm tra suy luận ngữ nghĩa (NLI). Khẳng định không có căn cứ sẽ bị lược bỏ hoặc kích hoạt fallback tất định an toàn.

---

## 15. Hệ thống đánh giá 4 tầng (Evaluation Framework)

Hệ thống thiết lập một khung đánh giá 4 tầng toàn diện:

```
┌────────────────────────────────────────────────────────────────────────┐
│                     4-LAYER EVALUATION FRAMEWORK                       │
├────────────────────────────────────────────────────────────────────────┤
│ Tầng 1: Document Intelligence                                          │
│   • Native text extraction ratio   • OCR recovery accuracy             │
│   • Bounding box precision         • Table structure completeness      │
├────────────────────────────────────────────────────────────────────────┤
│ Tầng 2: Retrieval Performance                                          │
│   • Recall@K                       • Mean Reciprocal Rank (MRR@K)      │
│   • nDCG@K                         • Precision@K                       │
├────────────────────────────────────────────────────────────────────────┤
│ Tầng 3: Structured Evidence & Fact Store                               │
│   • Metric extraction F1-score     • Value accuracy                    │
│   • Unit normalization accuracy    • Year & Target resolution rate     │
│   • Conflict detection precision   • False positive conflict rate      │
├────────────────────────────────────────────────────────────────────────┤
│ Tầng 4: Final Answer & Audit Quality                                   │
│   • Faithfulness (Groundedness)    • Citation Correctness              │
│   • Gold Citation Precision/Recall • Completeness Score                │
│   • Unsupported Claim Rate         • Abstention correctness            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 16. Tính tái lập & Dữ liệu kiểm thử (Reproducibility)

### 16.1 Phân chia Dev/Test Benchmarks
Để tránh hiện tượng overfitting trên tập kiểm thử (Data Snooping), hệ thống phân định rạch ròi tập dữ liệu:
- `data/evaluation/dev/`: Sử dụng để tinh chỉnh tham số (hyperparameters: RRF k, top-k, prompt, rubric).
- `data/evaluation/test/`: Khóa cố định, chỉ chạy đánh giá và báo cáo một lần duy nhất.

### 16.2 Gold Citation Evaluation (`data/evaluation/answer_eval_cases.json`)
Mỗi ca kiểm thử câu trả lời được gắn nhãn `expected_evidence` chuẩn vàng:
```json
{
  "id": "ans_boeing_suppliers",
  "question": "How many suppliers were evaluated using social criteria by Boeing?",
  "query_scope": ["boeing-demo"],
  "expected_topics": ["suppliers", "social", "criteria"],
  "expected_numbers": ["724", "148%"],
  "expected_evidence": [
    {"document_id": "boeing-demo", "page": 43}
  ]
}
```
Nhờ đó, hệ thống đo lường được **Gold Citation Precision** và **Gold Citation Recall** thực thụ, thay vì chỉ kiểm tra tính tự nhất quán hình thức.

---

## 17. API, CLI & Khả năng quan sát (Trace Waterfall)

### 17.1 HTTP Endpoints (`app/main.py`)
- `GET /`: Dashboard trực quan phục vụ người dùng.
- `GET /health`: Trạng thái hệ thống, cấu hình và thống kê corpus.
- `POST /api/documents`: Ingest tài liệu PDF mới (hỗ trợ multipart upload).
- `POST /api/search`: Tìm kiếm trực tiếp các đoạn bằng chứng.
- `POST /api/query`: Hỏi đáp thông minh kèm theo kế hoạch truy xuất.
- `POST /api/audit`: Kiểm toán toàn diện báo cáo theo 13 tiêu chí E/S/G.
- `POST /api/compare`: Đối sánh số liệu giữa các doanh nghiệp.
- `POST /api/temporal`: Phân tích chuỗi thời gian YoY.
- `GET /api/analysis/recent/trace`: Lấy waterfall latency trace của lần phân tích gần nhất.

### 17.2 CLI Commands
```bash
# Ingest dữ liệu hàng loạt từ thư mục
python -m app.cli ingest --metadata metadata.csv --reports-dir data/pdfs

# Đánh giá hiệu năng truy xuất RAG
python -m app.cli evaluate --cases data/evaluation/dev/retrieval_cases.json

# Đánh giá ablation benchmark 4 cấu hình
python -m app.cli benchmark --cases data/evaluation/retrieval_cases.json

# Đánh giá chất lượng câu trả lời và trích dẫn chuẩn vàng
python -m app.cli evaluate-answer --cases data/evaluation/answer_eval_cases.json

# Đánh giá độ chính xác trích xuất Fact
python -m app.cli evaluate-extraction

# Thực thi kiểm toán trực tiếp từ dòng lệnh
python -m app.cli audit --document-id boeing-demo --top-k 12
```

---

## 18. Giới hạn hiện tại (Limitations)

Hệ thống luôn minh bạch về các giới hạn kỹ thuật:
1. **OCR cho bảng biểu phức tạp**: Mặc dù PyMuPDF xử lý rất tốt bảng số liệu native text, các bảng biểu dạng ảnh scan méo lệch nặng vẫn cần mô hình Vision-Language chuyên dụng (như Nougat hoặc DocOwl) để đạt độ chính xác 100%.
2. **Khái quát hóa phương pháp luận GHG**: Một số báo cáo sử dụng các phương pháp luận nội bộ độc quyền không tuân theo GHG Protocol tiêu chuẩn có thể khiến parser phân loại phương pháp luận thành `unknown`.
3. **Phụ thuộc vào chất lượng công bố của doanh nghiệp**: Hệ thống phản ánh trung thực mức độ công bố của tài liệu; nếu báo cáo gốc hoàn toàn không công bố số liệu, hệ thống chỉ có thể gắn cờ `MISSING` và cảnh báo greenwashing chứ không thể tự suy đoán ra số liệu thực tế.

---

## 19. Lộ trình phát triển (Roadmap)

- [x] **P0**: Đổi mặc định `retrieval_mode = "hybrid"` phù hợp với thực nghiệm benchmark.
- [x] **P0**: Xóa bỏ hiện tượng double reranking; chuyển Cross-Encoder về một lần duy nhất tại `RetrievalAgent`.
- [x] **P0**: Nâng cấp `scope_1_2` bắt buộc đồng thời cả Scope 1 và Scope 2.
- [x] **P0**: Active Evidence Completeness Gate kích hoạt targeted retry.
- [x] **P0**: Khóa mâu thuẫn đa chiều bổ sung `company`, cách ly mâu thuẫn cross-company.
- [x] **P0**: Trình giải quyết năm mục tiêu (`resolve_target_year`) loại trừ reporting/baseline year.
- [x] **P1**: Tích hợp PyMuPDF `LayoutParser` với genuine bounding boxes `[x0, y0, x1, y1]`.
- [x] **P1**: Tích hợp `TesseractOCRProvider` phục hồi văn bản tự động khi native text < 20%.
- [x] **P1**: Stable Chunk ID (SHA-256) và Content Hash cho tính tái lập kiểm toán.
- [x] **P1**: Xây dựng bảng `esg_facts` và `FactRepository` làm Fact Store duy nhất.
- [x] **P1**: Thẩm định kiểm toán chi tiết theo từng tiêu chí (Criterion-level audit retrieval).
- [x] **P1**: Đánh giá Rubric Fact-First dựa trên `ESGFact`.
- [x] **P1**: Đo lường Gold Citation Precision/Recall trên tập dữ liệu kiểm thử.
- [x] **P1**: Phân chia Dev/Test splits cho bộ benchmark.
- [ ] **P2**: Tích hợp mô hình Vision-Language OCR phục vụ tài liệu scan chất lượng thấp.
- [ ] **P2**: Hỗ trợ backend Qdrant / Milvus khi mở rộng corpus lên hàng trăm ngàn tài liệu.

---

## 20. Bản quyền

Dự án được phân phối dưới giấy phép **MIT License**.
