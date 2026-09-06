# Multi-Agent ESG Report Analyst

**Hệ thống AI chuyên gia phân tích báo cáo phát triển bền vững (ESG) dựa trên bằng chứng (Evidence-Grounded), kiến trúc đường ống đơn luồng kiểm chứng đa tầng, triệt tiêu ảo giác và sàng lọc rủi ro Greenwashing.**

> **Tuyên bố miễn trừ trách nhiệm (Disclaimer):** Hệ thống này được xây dựng như một công cụ hỗ trợ phân tích, thẩm tra và sàng lọc rủi ro công bố thông tin (Screening Tool), không thay thế ý kiến kiểm toán độc lập, tư vấn pháp lý, xếp hạng tín nhiệm ESG chính thức hay kết luận gian lận pháp lý. Mọi nhận định đều được ràng buộc nghiêm ngặt với bằng chứng trích xuất từ tài liệu nguồn.

---

## 1. Giới thiệu tổng quan

**Multi-Agent ESG Report Analyst** giải quyết bài toán phức tạp bậc nhất trong lĩnh vực tài chính bền vững: đọc hiểu, đối chiếu, thẩm định và phát hiện mâu thuẫn số liệu trong các báo cáo phát triển bền vững (Sustainability / ESG Reports) dày hàng trăm trang của doanh nghiệp niêm yết.

Hệ thống được thiết kế theo tư duy **AI Engineering thực chiến**: loại bỏ các vòng lặp agentic mất kiểm soát, xây dựng đường ống dữ liệu một chiều duy nhất (Single Unidirectional Data Flow), phân định trách nhiệm rõ ràng (Single Responsibility Principle), chuẩn hóa hợp đồng dữ liệu có cấu trúc (Strict Typed Data Contracts) và đo lường định lượng qua bộ chỉ số đánh giá toàn diện.

---

## 2. Bài toán thực tế trong phân tích ESG

Báo cáo phát triển bền vững của doanh nghiệp thường đối mặt với các thách thức lớn:
- **Khối lượng đồ sộ và phi cấu trúc:** Từ 100 đến 300+ trang PDF gồm bảng biểu phức tạp, đồ họa, văn xuôi quan hệ công chúng (PR narrative) xen lẫn số liệu kỹ thuật.
- **Không nhất quán về đơn vị và phương pháp luận:** Cùng chỉ tiêu phát thải khí nhà kính nhưng công bố bằng $ktCO_2e$, $tCO_2e$, $gCO_2/kWh$, hoặc phân chia giữa *Market-based* và *Location-based*, phát thải ròng (*Net*) và gộp (*Gross*).
- **Rủi ro Greenwashing tinh vi:** Tuyên bố các mục tiêu tương lai xa vời ("Net Zero 2050") nhưng không công bố năm cơ sở (Baseline year), không nêu rõ phạm vi phát thải (Scope 1, 2 hay 3), hoặc số liệu các trang trước sau mâu thuẫn nhau.
- **Thiếu tính đối sánh (Comparability Gap):** Khó khăn khi so sánh các doanh nghiệp cùng ngành hoặc theo dõi tiến trình qua chuỗi thời gian (YoY trend).

---

## 3. Vì sao không dùng RAG ngây thơ (Naive RAG)?

Cách tiếp cận RAG thông thường (chặt văn bản thành các đoạn cố định 500 token, nạp vào Vector DB, tìm kiếm Cosine Similarity rồi gửi thẳng cho LLM sinh câu trả lời) thất bại hoàn toàn trong bài toán kiểm toán ESG vì:

| Nhược điểm Naive RAG | Hậu quả trong kiểm toán ESG | Giải pháp của Multi-Agent ESG Analyst |
| :--- | :--- | :--- |
| **Chunking thô bạo (Fixed-size)** | Bảng biểu bị cắt đôi, số liệu bị tách khỏi tiêu đề cột và đơn vị đo. | Phân tích layout (`LayoutBlock`), bảo toàn ranh giới trang và khối cấu trúc bảng biểu. |
| **Mất dấu nguồn gốc (Provenance Loss)** | LLM trích dẫn mơ hồ "theo báo cáo", không chỉ ra được trang mấy, dòng nào. | Mỗi trích dẫn gắn liền với `chunk_id`, `document_id`, số trang (`page`), excerpt và hash xác thực. |
| **Nhầm lẫn ngữ cảnh thời gian** | Lấy nhầm "năm cơ sở 2019" gán làm số liệu phát thải của năm hiện tại 2024. | Module `year_resolver` phân tích khoảng cách span cục bộ, tách biệt `reporting_year` và `baseline_year`. |
| **Ảo giác số liệu (Hallucination)** | LLM tự tính toán hoặc bịa đặt số liệu khi tài liệu không công bố. | **Evidence-First Gate**: Kiểm tra trường bắt buộc (`value`, `unit`, `year`), phát hiện thiếu bằng chứng trước khi sinh lời văn. |
| **Cộng dồn điểm số vô nghĩa** | Cộng trực tiếp BM25 score với Vector score mà không chuẩn hóa thang đo. | **Reciprocal Rank Fusion (RRF)** đa truy vấn kết hợp **Cross-Encoder Reranker** độc lập. |

---

## 4. Kiến trúc hệ thống

```
                         MULTI-AGENT ESG REPORT ANALYST
                                      │
              ┌───────────────────────┴────────────────────────┐
              │                                                │
      OFFLINE / INGESTION                              ONLINE / ANALYSIS
              │                                                │
       [PDF Document]                                  [User Request]
              │                                                │
      File Validation & Hash                           Query Planning
              │                                                │
     Layout Block Extraction                         Subquery Generation
              │                                                │
    Text Quality & OCR Gate                         Two-Stage Retrieval
              │                                   (RRF Fusion ➔ Cross-Encoder)
    Chunking with Metadata                                     │
              │                                       Citation Validation
      Hybrid Store Index                                       │
     (FTS5 BM25 + Vectors)                            Structured Fact Extraction
                                                               │
                                                   Evidence Completeness Gate
                                                               │
                                                    Domain Analysis Service
                                            (Rubric Matrix / Screening / Temporal)
                                                               │
                                                     Grounded Answer Synthesis
                                                               │
                                                    [Structured Response]
```

---

## 5. Hai luồng dữ liệu chính

### 5.1 Offline / Ingestion Pipeline
Quá trình chuẩn bị tài liệu diễn ra hoàn toàn offline, đảm bảo dữ liệu đầu vào đạt chuẩn chất lượng trước khi lập chỉ mục:
1. **File Validation:** Kiểm tra dung lượng (tối đa 75MB), định dạng PDF magic bytes (`%PDF-`), tính mã định danh SHA-256 (16 ký tự đầu).
2. **Layout Block Extraction:** Sử dụng PyMuPDF trích xuất các khối nội dung (`text`, `table`, `heading`), phân tách section và giữ nguyên số trang gốc.
3. **Ingestion Quality Gate:** Đánh giá tỷ lệ trang có chữ (`native_text_ratio`). Nếu tài liệu scan thiếu văn bản native (< 20%), kích hoạt giao diện `OCRProvider` (`TesseractOCRProvider`) hoặc từ chối lập chỉ mục.
4. **Structured Chunking:** Phân đoạn có ngữ cảnh, gắn nhãn metadata (`document_id`, `page`, `block_id`, `chunk_id`).
5. **Dual Indexing:** Lưu trữ song song vào SQLite FTS5 (BM25 keyword search) và Vector Database (Dense semantic embeddings).

### 5.2 Online / Analysis Pipeline
Luồng xử lý câu hỏi/yêu cầu kiểm toán của người dùng tuân thủ đúng một đường ống tuần tự:
```text
Request ➔ QueryPlanning ➔ Retrieval ➔ Verification ➔ FactExtraction ➔ CompletenessGate ➔ DomainAnalysis ➔ AnswerSynthesis
```
1. **Query Planning:** Phân loại ý định (`intent`), sinh các truy vấn con chuyên biệt và danh sách yêu cầu bằng chứng bắt buộc (`required_evidence`).
2. **Two-Stage Retrieval:** Truy xuất lai (Hybrid BM25 + Vector) trên từng subquery, hợp nhất bằng RRF, chọn Top-20 ứng viên và chấm điểm lại bằng Cross-Encoder.
3. **Citation Validation (Single Responsibility):** Xác thực duy nhất một lần tại workflow, loại bỏ trích dẫn giả mạo hoặc không trùng khớp với tài liệu nguồn.
4. **Structured Fact Extraction:** Quét regex chuyên sâu, bóc tách số liệu định lượng, nhận diện năm báo cáo, phương pháp luận và chuẩn hóa đơn vị đo.
5. **Evidence Completeness Gate:** Thẩm định xem các bằng chứng thu thập được có đáp ứng đầy đủ số liệu, đơn vị, năm và năm cơ sở hay không.
6. **Domain Analysis Service:** Điều phối chấm điểm Rubric theo 3 trụ cột E-S-G, xây dựng ma trận bằng chứng (`EvidenceMatrixBuilder`), sàng lọc rủi ro greenwashing (`ScreeningService`), phân tích chuỗi thời gian (`TemporalAnalysis`) hoặc so sánh doanh nghiệp (`CompanyComparison`).
7. **Grounded Answer Synthesis:** Kết hợp LLM (với cơ chế Fallback tất định) để tổng hợp câu trả lời, đảm bảo mọi tuyên bố đều có trích dẫn nguồn đi kèm.

---

## 6. Vai trò của từng module (Module Responsibilities)

| Module | Trách nhiệm chính | Input | Output |
| :--- | :--- | :--- | :--- |
| `app.document_service` | Tiếp nhận, thẩm định PDF, kiểm tra chất lượng và lập chỉ mục | Raw PDF bytes, metadata | `DocumentIngestResponse`, `ExtractionQualityReport` |
| `app.ingestion.ocr` | Giao diện OCR và tích hợp Tesseract xử lý trang scan | Image / Page bytes | Plain text |
| `app.chunking` | Phân đoạn tài liệu theo khối layout và ranh giới trang | `list[LayoutBlock]` | `list[dict]` (Chunks kèm metadata) |
| `app.capabilities.planning` | Phân tích câu hỏi, phân loại intent và lập kế hoạch truy xuất | User prompt / Question | `RetrievalPlan` |
| `app.capabilities.retrieval` | Truy xuất bằng chứng hai tầng (RRF + Reranker) | Query / Plan, Document IDs | `list[Citation]` (Top-K reranked) |
| `app.capabilities.verification` | Xác thực trích dẫn với tài liệu nguồn, kiểm tra offset và hash | `list[Citation]` | Validated `list[Citation]`, Verification Summary |
| `app.extraction` | Bóc tách fact số liệu, chuẩn hóa đơn vị, phát hiện mâu thuẫn | Validated `list[Citation]` | `list[ESGFact]`, `list[EvidenceConflict]` |
| `app.domain.evidence_completeness` | Cổng kiểm soát chất lượng bằng chứng theo field bắt buộc | Requirements, Facts, Citations | `EvidenceCompletenessResult` |
| `app.domain.rubric_evaluator` | Đánh giá mức độ công bố thông tin theo 3 trụ cột E-S-G | Citations | `list[PillarResult]`, Overall coverage score |
| `app.domain.evidence_matrix` | Xây dựng bảng ma trận bằng chứng chi tiết từng tiêu chí | Citations, Facts | `list[EvidenceMatrixRow]` |
| `app.domain.screening` | Sàng lọc tín hiệu rủi ro Greenwashing đa chiều | Facts, Citations, Conflicts | `GreenwashingScreeningResult` |
| `app.domain.temporal_analysis` | Phân tích chuỗi số liệu qua các năm và tính YoY | Company, Facts, Metric | `TemporalAnalysisResult` |
| `app.domain.company_comparison` | So sánh chất lượng công bố giữa các doanh nghiệp | Company docs, Citations, Facts | `CompanyComparisonResult` |
| `app.services.esg_analysis_service` | Điều phối tổng hợp các evaluator nghiệp vụ phân tích | Citations, Facts, Config | Pillars, Matrix, Signals, Conflicts |
| `app.workflow` | Điều phối duy nhất toàn bộ vòng đời phân tích (Orchestrator) | `AnalysisRequest` / Question | `AnalysisResponse` |

---

## 7. Cơ chế Retrieval hai tầng (Two-stage Retrieval)

Hệ thống loại bỏ hoàn toàn việc cộng dồn điểm số (Score Addition) giữa BM25 và Dense Vector (vốn có phân phối điểm số hoàn toàn khác nhau). Thay vào đó, quy trình truy xuất gồm hai giai đoạn độc lập:

```
Subqueries ──► [Stage 1: Hybrid Retrieval] ──► RRF Fusion ──► Candidate Pool (Top-20)
                                                                       │
                                                                       ▼
                                                       [Stage 2: Cross-Encoder Reranker]
                                                                       │
                                                                       ▼
                                                            Final Evidence (Top-K)
```

1. **Giai đoạn 1 (Candidate Generation):**
   - Với mỗi subquery trong kế hoạch, thực hiện truy xuất song song qua BM25 (SQLite FTS5) và Semantic Embedding (`sentence-transformers/all-MiniLM-L6-v2`).
   - Hợp nhất các danh sách kết quả bằng thuật toán **Reciprocal Rank Fusion (RRF)**:
     $$RRF\_Score(d) = \sum_{q \in Q} \frac{1}{k + rank_q(d)} \quad (k=60)$$
   - Lọc phân tán theo trang (Page Diversification: tối đa 2 đoạn trích trên 1 trang PDF) để tạo ra tập ứng viên Candidate Pool gồm 20 đoạn trích xuất sắc nhất.

2. **Giai đoạn 2 (Precision Reranking):**
   - Đưa tập ứng viên qua mô hình **Cross-Encoder** (`cross-encoder/ms-marco-MiniLM-L-6-v2`) chấm điểm độ tương quan trực tiếp giữa cặp `(query, excerpt)`.
   - Cắt lấy Top-K (mặc định 6-12) trích dẫn có điểm số cao nhất để chuyển tiếp cho các bước phân tích tiếp theo.

---

## 8. Pipeline trích xuất Fact có cấu trúc (Fact Extraction)

Nằm trong gói `app/extraction/`, pipeline bóc tách số liệu hoạt động theo mô hình lắp ghép mô-đun:
- **`metric_detector.py`:** Chứa tập biểu thức chính quy (Regex) tối ưu hóa cho các chỉ số ESG:
  - Khí nhà kính: Scope 1, Scope 2, Scope 3 ($tCO_2e$, $ktCO_2e$, $MtCO_2e$).
  - Mục tiêu giảm phát thải: Net Zero, Carbon Neutral.
  - Năng lượng: Điện tái tạo, công suất điện gió/mặt trời ($MWh$, $GWh$, $MW$).
  - Xã hội & Lao động: Tỷ lệ an toàn lao động ($TRIR$, tai nạn), quy mô nhân sự, tỷ lệ đa dạng giới (Diversity %).
  - Chuỗi cung ứng: Tỷ lệ đánh giá nhà cung cấp.
- **`value_parser.py`:** Chuẩn hóa chuỗi số học, xử lý dấu phẩy, dấu chấm phân cách hàng nghìn.
- **`unit_normalizer.py`:** Quy đổi tất cả đơn vị tương thích về đơn vị chuẩn:
  - Khí nhà kính quy đổi về **$tCO_2e$** ($1\,ktCO_2e = 1.000\,tCO_2e$; $1\,MtCO_2e = 1.000.000\,tCO_2e$).
  - Năng lượng quy đổi về **$MWh$** ($1\,GWh = 1.000\,MWh$; $1\,TJ = 277,78\,MWh$).
  - Lưu vết song song cả giá trị gốc (`raw_value`, `raw_unit`) và giá trị chuẩn hóa (`normalized_value`, `normalized_unit`).
- **`year_resolver.py`:** Xác định năm báo cáo trong cửa sổ cục bộ [-120, +120 ký tự] xung quanh vị trí số liệu. **Quy tắc quan trọng:** Tuyệt đối không nhầm lẫn năm cơ sở (ví dụ *"from 2019 baseline"* hoặc *"2019 baseline"*) làm năm báo cáo của số liệu phát thải hiện tại.
- **`fact_validator.py`:** Phát hiện mâu thuẫn số liệu đa chiều theo khóa bộ ba `(metric, methodology, year)`. Nếu cùng một chỉ tiêu, cùng phương pháp và cùng năm nhưng số liệu giữa các trang chênh lệch trên 1%, hệ thống sẽ gắn nhãn cảnh báo `EvidenceConflict`.

---

## 9. Quality Gates & Domain Checks

Hệ thống thiết lập 3 cổng kiểm soát chất lượng (Quality Gates) độc lập:

1. **Ingestion Quality Gate (`ExtractionQualityReport`):**
   - Đánh giá chất lượng trích xuất văn bản PDF.
   - Báo cáo rõ ràng: `native_text_ratio`, `ocr_applied_ratio`, `table_count`, danh sách trang trắng (`empty_pages`), và điểm tin cậy trung bình.

2. **Evidence Completeness Gate (`EvidenceCompletenessGate`):**
   - Kiểm tra tính đầy đủ của bằng chứng trước khi tiến hành phân tích và tổng hợp câu trả lời.
   - Một yêu cầu chỉ được công nhận là `satisfied` khi có Fact hoặc Citation khớp ngữ nghĩa VÀ đáp ứng đủ các trường định lượng bắt buộc:
     - Phải có giá trị số (`value is not None`) và đơn vị (`unit`).
     - Phải có năm báo cáo (`year is not None`).
     - Phải có năm cơ sở (`baseline_year is not None`) đối với các chỉ tiêu mục tiêu (Target).
   - Nếu thiếu, ghi nhận trạng thái `incomplete` và tự động bổ sung cảnh báo `[MISSING_EVIDENCE]` vào mục hạn chế của kết quả.

3. **Claim Support Gate:**
   - Đối chiếu từng luận điểm do LLM sinh ra với tập bằng chứng đã được thẩm định.
   - Ngăn chặn triệt để hiện tượng mô hình tự suy diễn vượt quá phạm vi dữ liệu có trong tài liệu.

---

## 10. Hệ thống Rubric & Scoring

Khung kiểm toán ESG chuẩn mực đánh giá theo 12 tiêu chí cốt lõi phân bổ trên 3 trụ cột:

```text
├── E (Environment - Môi trường)
│   ├── E1: Scope 1 Emissions (Phát thải trực tiếp)
│   ├── E2: Scope 2 Emissions (Phát thải gián tiếp từ năng lượng)
│   ├── E3: Scope 3 Emissions (Phát thải chuỗi giá trị)
│   ├── E4: Net-Zero & Decarbonization Targets (Mục tiêu Net Zero)
│   ├── E5: Energy & Renewable Transition (Chuyển dịch năng lượng tái tạo)
│   └── E6: Climate Risk Governance & Assurance (Quản trị khí hậu & Kiểm toán)
├── S (Social - Xã hội)
│   ├── S1: Occupational Health & Safety / TRIR (An toàn lao động)
│   ├── S2: Diversity, Equity & Inclusion (Đa dạng giới & bình đẳng)
│   └── S3: Supply Chain Human Rights & Due Diligence (Thẩm định chuỗi cung ứng)
└── G (Governance - Quản trị)
    ├── G1: Board Independence & Diversity (Tính độc lập của HĐQT)
    ├── G2: Anti-Corruption, Ethics & Compliance (Chống tham nhũng & Tuân thủ)
    └── G3: ESG-Linked Executive Compensation (Gắn thù lao với chỉ tiêu ESG)
```

### Công thức tính điểm:
- **Disclosure Coverage (%):** Tỷ lệ tiêu chí có bằng chứng xác thực (`found` hoặc `partial`) trên tổng số tiêu chí được kiểm toán.
- **Evidence Quality (%):** Đánh giá độ tin cậy của trích dẫn (trang, đoạn trích, có bảng biểu, có xác thực bên thứ 3).
- **Data Completeness (%):** Đo lường mức độ đầy đủ của các trường số liệu, đơn vị, năm và năm cơ sở.
- **Confidence (0.0 - 1.0):** Độ tin cậy tổng thể của mô hình đối với kết quả phân tích.

---

## 11. Đánh giá hệ thống (Evaluation System)

Dự án tích hợp bộ kiểm thử đánh giá định lượng (Evaluation Suite) đo lường chất lượng hệ sinh thái theo 3 tầng chuẩn AI Engineering:

1. **RAG Triad Metrics (Độ chuẩn xác truy xuất & trả lời):**
   - **Context Relevance:** Mức độ phù hợp của các đoạn trích dẫn được truy xuất so với câu hỏi.
   - **Groundedness / Faithfulness:** 100% các câu khẳng định trong câu trả lời phải được bảo trợ bởi trích dẫn thực tế.
   - **Answer Relevance:** Trả lời trực diện vào câu hỏi kiểm toán của người dùng.

2. **Domain-Specific ESG Metrics:**
   - **Unit Normalization Accuracy:** Đo tỷ lệ chuẩn hóa chính xác các đơn vị đo lường phức tạp.
   - **Temporal Conflict Detection Precision:** Khả năng phát hiện đúng mâu thuẫn số liệu giữa các trang mà không phát sinh báo động giả (False Positives).
   - **Missing Evidence Precision:** Tỷ lệ gắn cờ chính xác khi báo cáo cố tình né tránh công bố năm cơ sở hoặc Scope 3.

3. **G-Eval & Automated Regression Testing:**
   - Chạy kiểm thử tự động trên tập test suite toàn diện (`tests/test_answer_evaluation.py`, `tests/test_evaluation.py`).
   - Đảm bảo điểm số đánh giá không bị suy thoái khi cập nhật logic retrieval hay prompt.

---

## 12. Data Contract & Models

Các cấu trúc dữ liệu được định nghĩa chặt chẽ bằng Pydantic v2 trong `app/models.py`:

```python
# Đại diện cho một trích dẫn bằng chứng có định danh nguồn gốc
class Citation(BaseModel):
    chunk_id: int | None
    document_id: str
    document_name: str
    page: int
    excerpt: str
    score: float
    retrieval_score: float
    reranker_score: float | None
    validation_status: Literal["valid", "flagged", "rejected"]

# Bằng chứng số liệu ESG có cấu trúc
class ESGFact(BaseModel):
    metric: str
    value: float | str | None
    unit: str | None
    year: int | None
    baseline_year: int | None
    source: Citation | None
    confidence: float
    raw_value: float | str | None
    raw_unit: str | None
    normalized_value: float | None
    normalized_unit: str | None
    methodology: str | None
    validation_status: Literal["valid", "conflict", ...]

# Hợp đồng kết quả kiểm tra chất lượng bằng chứng
class EvidenceCompletenessResult(BaseModel):
    requirements: list[EvidenceRequirementResult]
    satisfied_count: int
    partial_count: int
    missing_count: int
    completeness_score: float
    status: Literal["complete", "incomplete"]
    required: list[str]
    satisfied: list[str]
    partial: list[str]
    missing: list[str]

# Kết quả phân tích tổng hợp hoàn chỉnh trả về người dùng
class AnalysisResponse(BaseModel):
    mode: Literal["qa", "audit"]
    answer: str
    disclosure_coverage: float
    evidence_quality: float
    data_completeness: float
    confidence: float
    pillars: list[PillarResult]
    citations: list[Citation]
    evidence_matrix: list[EvidenceMatrixRow]
    extracted_facts: list[ESGFact]
    conflicts: list[EvidenceConflict]
    screening_result: GreenwashingScreeningResult | None
    temporal_analysis: TemporalAnalysisResult | None
    comparison: CompanyComparisonResult | None
    evidence_completeness: EvidenceCompletenessResult
    limitations: list[str]
    trace: list[str]
```

---

## 13. Tech Stack

- **Ngôn ngữ & Runtime:** Python 3.11+ / 3.12+ / 3.13+
- **Backend API:** FastAPI, Uvicorn, Pydantic v2
- **Xử lý PDF & Ingestion:** PyMuPDF (fitz), pdfplumber
- **Lưu trữ & Tìm kiếm:** SQLite FTS5 (BM25 Keyword Search), SQLite JSON Storage
- **Mô hình nhúng & Reranker:** HuggingFace `sentence-transformers` (`all-MiniLM-L6-v2`), `cross-encoder` (`ms-marco-MiniLM-L-6-v2`)
- **LLM Integration:** OpenAI API / Gemini API / Deterministic Fallback Mode (chạy độc lập không phụ thuộc Internet khi cần kiểm thử)
- **Frontend Dashboard:** Vanilla HTML5, Modern CSS (Glassmorphism & Dark Mode), Javascript ES6
- **Kiểm thử & Đảm bảo chất lượng:** Pytest, AnyIO, Pytest-Asyncio

---

## 14. Cài đặt và Chạy thử

### Yêu cầu tiên quyết
- Python 3.11 trở lên
- Git

### Các bước cài đặt

```bash
# 1. Clone repository
git clone https://github.com/haminhthong/Multi-Agent-ESG-Report-Analyst.git
cd Multi-Agent-ESG-Report-Analyst

# 2. Khởi tạo môi trường ảo
python -m venv .venv
source .venv/bin/activate       # Trên Linux/macOS
# .venv\Scripts\activate        # Trên Windows PowerShell

# 3. Cài đặt thư viện phụ thuộc
pip install -r requirements.txt
```

### Chạy kiểm thử tự động
```bash
pytest
```

### Khởi chạy ứng dụng Web & API
```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Truy cập giao diện Web Dashboard tại: `http://localhost:8000`  
Tài liệu tương tác Swagger API tại: `http://localhost:8000/docs`

---

## 15. API Endpoints

| Phương thức | Endpoint | Chức năng |
| :--- | :--- | :--- |
| `POST` | `/api/documents` | Tải lên và lập chỉ mục báo cáo PDF (`multipart/form-data`) |
| `GET` | `/api/documents` | Danh sách tài liệu đã được nạp kèm chỉ số chất lượng |
| `POST` | `/api/analyze` | Hỏi đáp (Q&A) dựa trên tài liệu kèm kế hoạch truy xuất |
| `POST` | `/api/audit` | Thực hiện kiểm toán toàn diện 3 trụ cột E-S-G kèm ma trận bằng chứng |
| `POST` | `/api/compare` | So sánh chất lượng công bố giữa các doanh nghiệp |
| `POST` | `/api/temporal` | Phân tích diễn biến chỉ số ESG qua các năm của một doanh nghiệp |
| `GET` | `/api/health` | Kiểm tra trạng thái hoạt động của hệ thống |

---

## 16. CLI Usage

Hệ thống cung cấp giao diện dòng lệnh (CLI) hoàn chỉnh qua module `app.cli`:

```bash
# 1. Nạp tài liệu PDF vào hệ thống
python -m app.cli ingest path/to/report.pdf --company "Vinamilk" --year 2023

# 2. Đặt câu hỏi phân tích bằng chứng
python -m app.cli analyze "What are the company's Scope 1 and Scope 2 emissions?"

# 3. Thực hiện kiểm toán toàn diện ESG
python -m app.cli audit --focus E --top-k 12

# 4. So sánh các doanh nghiệp
python -m app.cli compare --companies "CompanyA" "CompanyB"

# 5. Phân tích chuỗi thời gian của một chỉ tiêu
python -m app.cli temporal --company "Vinamilk" --metric "scope_1_emissions"

# 6. Chạy bộ đánh giá chất lượng hệ thống
python -m app.cli evaluate
```

---

## 17. Cấu hình (Configuration)

Các tham số hệ thống được cấu hình qua biến môi trường hoặc file `.env`:

| Biến môi trường | Mặc định | Ý nghĩa |
| :--- | :--- | :--- |
| `ESG_STORAGE_DIR` | `./data` | Thư mục lưu trữ SQLite database và chỉ mục |
| `ESG_RETRIEVAL_MODE` | `hybrid` | Cơ chế truy xuất: `bm25`, `dense`, `hybrid` |
| `ESG_RERANKER_ENABLED` | `true` | Bật/tắt tầng Cross-Encoder Reranker |
| `ESG_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Mô hình biểu diễn vector ngữ nghĩa |
| `ESG_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Mô hình Cross-Encoder reranking |
| `OPENAI_API_KEY` | `None` | API Key OpenAI (nếu sử dụng LLM Cloud) |
| `GEMINI_API_KEY` | `None` | API Key Google Gemini (nếu sử dụng Gemini) |

---

## 18. Triết lý thiết kế (Design Decisions)

1. **Điều phối tất định (Deterministic Orchestration over Uncontrolled Agent Loops):** Thay vì để các Agent tự trao đổi vô tận gây tốn chi phí token và khó dự đoán, hệ thống sử dụng một Pipeline tuần tự có thể quan sát (observable) và kiểm thử được 100%.
2. **Nguyên tắc một trách nhiệm (Single Responsibility Principle):** Xác thực trích dẫn (`EvidenceVerificationAgent`) chỉ thực hiện một lần duy nhất tại Workflow, giải phóng Retrieval Agent khỏi gánh nặng thẩm định trùng lặp.
3. **Evidence-First & Dual Value Representation:** Mọi thông tin định lượng đều lưu trữ đồng thời dạng nguyên bản (`raw_value`, `raw_unit`) và dạng chuẩn hóa (`normalized_value`, `normalized_unit`) để phục vụ đối soát kiểm toán độc lập.
4. **Decoupled Business Evaluators:** Các nghiệp vụ đánh giá Rubric, sàng lọc Greenwashing, so sánh doanh nghiệp và phân tích chuỗi thời gian được phân rã thành các class độc lập trong `app/domain/`, thuận tiện cho việc mở rộng quy tắc kiểm toán mới mà không ảnh hưởng tới core framework.

---

## 19. Giới hạn hiện tại & Hướng phát triển

- **Bảng biểu phức tạp nhiều tầng (Multi-level Tables):** Các bảng tài chính lồng nhau hoặc bị scan nghiêng hiện đang phụ thuộc vào chất lượng bóc tách văn bản native của PyMuPDF.
- **Tài liệu thuần scan ảnh:** Đã có giao diện `OCRProvider` (`TesseractOCRProvider`), định hướng tiếp theo sẽ tích hợp các giải pháp Vision-Language Models (như Nougat hoặc DocOwl) cho các tài liệu scan chất lượng thấp.
- **Hỗ trợ đa ngôn ngữ chuyên sâu:** Mở rộng từ khóa và mẫu phát hiện thực thể cho các báo cáo phát triển bền vững bằng tiếng Việt, tiếng Nhật và tiếng Trung.

---

## 20. Đóng góp & Bản quyền

Dự án được phân phối dưới giấy phép **MIT License**. Mọi đóng góp (Pull Requests), báo cáo lỗi (Issues) hoặc đề xuất tính năng mới đều được chào đón!

1. Fork repository.
2. Tạo branch tính năng (`git checkout -b feature/AmazingFeature`).
3. Commit các thay đổi (`git commit -m 'Add some AmazingFeature'`).
4. Đảm bảo toàn bộ test suite vượt qua (`pytest`).
5. Push lên branch (`git push origin feature/AmazingFeature`) và mở Pull Request.
