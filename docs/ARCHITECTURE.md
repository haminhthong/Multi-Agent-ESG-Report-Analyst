# Kiến trúc Hệ thống (System Architecture)
## Evidence-Grounded ESG Intelligence & Audit Platform

---

## 1. Tầm nhìn & Nguyên tắc Thiết kế Cốt lõi (Architectural Principles)

Hệ thống được định vị là **Nền tảng Trí tuệ và Kiểm toán Báo cáo Bền vững ESG Dựa trên Bằng chứng (Evidence-Grounded ESG Intelligence & Audit Platform)**. Khác với các hệ thống RAG demo thông thường (vốn chỉ tìm văn bản tương tự rồi yêu cầu LLM tóm tắt tự do), nền tảng này áp dụng quy trình kiểm soát bằng chứng nghiêm ngặt tương đương chuẩn mực kiểm toán công nghiệp:

1. **Evidence-First & Deep Provenance**: Mọi khẳng định, điểm số, trạng thái tuân thủ và số liệu trích xuất đều phải được neo trực tiếp vào văn bản nguồn với đầy đủ định danh tài liệu, số trang PDF thực tế (`page`), tiêu đề phân mục (`section`), và khối nội dung (`block_id`).
2. **Deterministic DAG Workflow (Agent-Orchestrated)**: Thay vì để các agent trò chuyện tự do thiếu kiểm soát (dẫn đến không dự đoán được kết quả và lãng phí token), hệ thống vận hành theo một đồ thị có hướng không chu trình (Deterministic DAG): *Plan → Retrieve → Verify → Extract → Audit → Synthesize*.
3. **Global RRF Fusion (Subquery Bias Elimination)**: Khi phân rã câu hỏi thành nhiều subqueries, kết quả được hợp nhất toàn cục bằng thuật toán **Reciprocal Rank Fusion (RRF $k=60$)**, loại bỏ hoàn toàn bias thứ tự truy vấn.
4. **Evidence Completeness Gate**: Kiểm soát chặt chẽ các trường dữ liệu bắt buộc (`required_evidence`, `required_fields`). Nếu tài liệu thiếu dữ liệu đối chứng (ví dụ chỉ có cam kết Net-Zero mà thiếu năm cơ sở hoặc thiếu kiểm toán độc lập), hệ thống dán nhãn `partial` hoặc `missing` và công bố rõ ràng trong phần `limitations`.
5. **Canonical Unit Normalization & Conflict Disambiguation**: Tự động quy đổi các đơn vị phát thải về `tCO2e` và năng lượng về `MWh`. Thuật toán phát hiện mâu thuẫn phân nhóm đa chiều theo chỉ tiêu, năm báo cáo và phương pháp luận đo lường (như *market-based* vs *location-based*), triệt tiêu các báo động mâu thuẫn giả.
6. **Zero-Cost Local First & Fallback Resiliency**: Toàn bộ hệ thống chạy 100% offline với mô hình cục bộ hoặc **Deterministic Heuristic Engine** ($0 API cost), sẵn sàng mở rộng sang Local LLM (Ollama: Qwen 2.5, Llama 3) khi cần lập luận phức tạp.

---

## 2. Quy trình Canonical 2 Nhánh (Dual-Pipeline Architecture)

Hệ thống phân tách rạch ròi giữa nhánh **Nạp & Lập chỉ mục Kiến thức Ngoại tuyến (Offline Knowledge Pipeline)** và nhánh **Phân tích Kiểm toán Trực tuyến (Online Evidence-Grounded Analysis Pipeline)**.

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
   ├── Span-based localized metric & year association
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

## 3. Bảng Đặc tả Chi tiết 10 Bước Canonical (Canonical Step Specification)

| Bước | Tên Bước | Đầu vào (Inputs) | Đầu ra (Outputs) | Cơ chế Xử lý & Thuật toán | Nguy cơ Lỗi (Failure Modes) | Cơ chế Dự phòng (Fallback) | Ngân sách Độ trễ |
|:---:|---|---|---|---|---|---|:---:|
| **1** | **Document Ingestion & Quality Gate** | Tệp tin PDF nhị phân | Document metadata, SHA-256, Extraction Quality Score | Kiểm tra định dạng PDF, tính hash SHA-256 định danh, tính tỷ lệ trang có text có thể trích xuất | Tệp tin hỏng, PDF dạng scan thuần ảnh không có text layer | Báo lỗi `OcrRequiredError`, từ chối nạp tài liệu rác | < 200 ms / file |
| **2** | **Document Intelligence** | Trang tài liệu PDF | Layout Blocks (Heading, Text, Table) | Phân loại trang PDF theo cấu trúc; bóc tách phân mục tài liệu và khối bảng biểu có cấu trúc | Trích xuất sai thứ tự đọc của văn bản nhiều cột | Dùng heuristic dựa trên khoảng cách dòng và kích thước font chữ | < 500 ms / 100 trang |
| **3** | **Contextual Chunking & Enrichment** | Layout Blocks | Structured Chunks kèm Metadata | Cắt đoạn theo ranh giới đoạn văn (200-500 từ), gắn tiền tố tiêu đề mục cha (`section_title`), gán nhãn trụ cột ESG (`E`, `S`, `G`) | Cắt đứt đôi bảng số liệu hoặc câu quan trọng | Bảo tồn trọn vẹn khối bảng biểu (`block_type='table'`) | < 100 ms |
| **4** | **Hybrid Indexing** | Chunks | Chỉ mục SQLite FTS5 + Vector Embeddings | Lập chỉ mục FTS5 cho BM25; sinh embedding 384 chiều bằng `all-MiniLM-L6-v2` | Hết bộ nhớ GPU / CPU chậm | Chế độ Sparse-only BM25 dự phòng khi không có PyTorch | < 2s / 50 chunks |
| **5** | **Analytical Intent & Query Planning** | Câu hỏi người dùng | `RetrievalPlan`: Intent, Subqueries, Required Evidence | LLM JSON Planning hoặc Heuristic Regex Planner phân loại 5 loại intent nghiệp vụ | Câu hỏi mơ hồ hoặc chứa nhiều mục tiêu xung đột | Bộ phân loại Heuristic dựa trên từ điển ESG chuẩn hóa | < 50 ms (Heuristic) / < 1s (LLM) |
| **6** | **Hybrid Retrieval & Global RRF Fusion** | `RetrievalPlan`, Store | Top-$K$ Citations ứng viên | Truy xuất song song BM25 và Dense cho từng subquery; hợp nhất điểm RRF toàn cục $k=60$; Cross-Encoder rerank; lọc tối đa 2 trích đoạn / trang | Bias thứ tự subquery; trích dẫn tập trung cục bộ vào 1 trang | Global RRF không phụ thuộc thứ tự; Page Diversification cưỡng bức | < 150 ms |
| **7** | **Evidence Verification & Completeness Gate** | Candidate Citations, Required Evidence | Validated Citations, Completeness Report | Thẩm định số trang hợp lệ ($page \ge 1$), loại bỏ đoạn rỗng/trùng; kiểm tra đối chiếu các trường yêu cầu | Bằng chứng bị thiếu các trường số liệu cốt lõi | Dán nhãn `[MISSING_EVIDENCE]` vào phần `limitations` của báo cáo | < 20 ms |
| **8** | **Fact Extraction & Conflict Detection** | Validated Citations | `ESGFact` records, `EvidenceConflict` | Quét cửa sổ cục bộ quanh số liệu để gắn đúng năm báo cáo vs năm cơ sở; `UnitNormalizer` quy đổi về tCO2e, MWh; phát hiện sai lệch số liệu | Trích xuất nhầm năm cơ sở thành năm báo cáo; conflict giả do khác phương pháp | Window span localized extraction; phân nhóm theo metric + năm + methodology | < 30 ms |
| **9** | **ESG Audit Matrix & Greenwashing Radar** | Validated Citations, Facts | Evidence Matrix, Screening Result, YoY Analysis | Đối soát từng tiêu chí GRI/SASB theo `required_fields`; tính độ phủ công bố; tính điểm radar greenwashing 3 chiều | Bị ngộ nhận là kiểm toán độc lập thay vì công cụ sàng lọc | Hiển thị rõ nhãn "Screening Risk", ghi nhận rõ ràng các tiêu chí thiếu | < 40 ms |
| **10** | **Grounded Synthesis & Provenance Binding** | Matrix, Citations, Question | `AnalysisResponse`: Answer, Citations, Waterfall ms | Tổng hợp giải trình bằng chứng; kiểm chứng nghiêm ngặt số trang trong câu trả lời phải thuộc trích dẫn đã truy xuất | LLM sinh câu trả lời bịa số trang hoặc bịa số liệu | Tự động chuyển đổi sang Deterministic Rule-Grounded Synthesis | < 50 ms (Rule) / < 2s (LLM) |

---

## 4. 6 Năng lực Cốt lõi của Hệ thống (6 Core Capabilities)

Thay vì phân mảnh thành các "autonomous agent tự đàm phán", hệ thống được tổ chức thành **6 Năng lực Nghiệp vụ Chuyên sâu**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SUPERVISOR ORCHESTRATION LAYER (DAG)                     │
│               Observable Latency Waterfall & Execution Tracing              │
└──────┬──────────────┬──────────────┬──────────────┬──────────────┬──────────┘
       │              │              │              │              │
       ▼              ▼              ▼              ▼              ▼
┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
│ Capability 1 ││ Capability 2 ││ Capability 3 ││ Capability 4 ││ Capability 5 │
│   Document   ││  Analytical  ││    Hybrid    ││   Evidence   ││  Structured  │
│ Intelligence ││   Intent &   ││  Retrieval & ││ Verification ││     Fact     │
│  & Quality   ││    Query     ││  Global RRF  ││      &       ││ Extraction & │
│     Gate     ││   Planning   ││    Fusion    ││  Provenance  ││  Discrepancy │
└──────────────┘└──────────────┘└──────────────┘└──────────────┘└──────────────┘
                                                                       │
                                                                       ▼
                                                        ┌──────────────────────┐
                                                        │     Capability 6     │
                                                        │   ESG Audit Matrix,  │
                                                        │ Greenwashing Radar & │
                                                        │  Grounded Synthesis  │
                                                        └──────────────────────┘
```

1. **Document Intelligence & Quality Gate**: Phân tích bố cục, phân loại trang PDF, tính điểm chất lượng trích xuất text, nhận diện và từ chối tài liệu scan cần OCR.
2. **Analytical Intent & Query Planning**: Phân tích ý định câu hỏi (tra cứu sự thật, kiểm toán tiêu chí, phân tích chuỗi thời gian YoY, so sánh chéo doanh nghiệp), sinh truy vấn con đa hướng và xác định bằng chứng đối chứng bắt buộc.
3. **Hybrid Evidence Retrieval & Global RRF Fusion**: Kết hợp BM25 chính xác từ khóa và Dense MiniLM hiểu ngữ nghĩa, hợp nhất điểm toàn cục bằng RRF $k=60$, tái xếp hạng bằng Cross-Encoder và đa dạng hóa trang.
4. **Evidence Verification & Deep Provenance**: Thẩm định tính hợp lệ hình thức của trích dẫn, kiểm soát cổng độ đầy đủ bằng chứng (Evidence Completeness Gate), và kiểm chứng các khẳng định với nội dung gốc.
5. **Structured Fact Extraction & Multidimensional Conflict Detection**: Bóc tách số liệu có cấu trúc (`ESGFact`), chuẩn hóa đơn vị đo lường quốc tế (`UnitNormalizer`), tách bạch năm cơ sở với năm báo cáo, và phát hiện mâu thuẫn số liệu công bố đa chiều.
6. **ESG Audit Matrix, Greenwashing Radar & Grounded Synthesis**: Đối soát ma trận tiêu chuẩn GRI/SASB, sàng lọc rủi ro tẩy xanh đa tín hiệu (Target Credibility, Evidence Quality, Narrative Risk), và tổng hợp báo cáo giải trình minh bạch dẫn nguồn số trang chính xác.

---

## 5. Công thức Toán học & Thuật toán Cốt lõi

### 5.1. Global Reciprocal Rank Fusion (RRF)
Khi câu hỏi được phân rã thành tập hợp các truy vấn con $Q_{\text{sub}} = \{q_1, q_2, \dots, q_m\}$, mỗi subquery truy xuất một danh sách ứng viên được xếp hạng bởi cả BM25 và Dense Vector. Điểm RRF toàn cục của một đoạn trích dẫn $d$ được tính tích lũy qua toàn bộ các truy vấn con:

$$\text{Score}_{\text{RRF}}(d) = \sum_{q \in Q_{\text{sub}}} \sum_{m \in \{\text{BM25}, \text{Dense}\}} \frac{\mathbb{I}(d \in R_{q, m})}{k + \text{rank}_{q, m}(d)} \quad (k = 60)$$

Sau đó, nếu có điểm Cross-Encoder Reranker, điểm tổng hợp cuối cùng được chuẩn hóa:
$$\text{Score}_{\text{final}}(d) = \text{Score}_{\text{RRF}}(d) + 0.1 \cdot \text{Score}_{\text{CrossEncoder}}(d)$$

### 5.2. Công thức Chuẩn hóa Đơn vị Phát thải & Năng lượng (Unit Normalization)
$$V_{\text{normalized}} = V_{\text{raw}} \times \text{Factor}(\text{unit}_{\text{raw}})$$

* **Phát thải KNK (GHG)**: Base unit = `tCO2e`
  - $1 \text{ ktCO2e} = 1,000 \text{ tCO2e}$
  - $1 \text{ MtCO2e} = 1,000,000 \text{ tCO2e}$
  - $1 \text{ metric ton} = 1 \text{ tCO2e}$
* **Năng lượng**: Base unit = `MWh`
  - $1 \text{ GWh} = 1,000 \text{ MWh}$
  - $1 \text{ kWh} = 0.001 \text{ MWh}$
  - $1 \text{ TJ} \approx 277.78 \text{ MWh}$
  - $1 \text{ GJ} \approx 0.2778 \text{ MWh}$

### 5.3. Công thức Tính Độ phủ Tiêu chí (Disclosure Coverage)
Hệ thống tính điểm độ phủ công bố thông tin có tính đến mức độ đầy đủ của các trường bắt buộc (`required_fields`):

$$\text{Coverage}_{\text{pillar}} = \frac{N_{\text{found}} + 0.5 \times N_{\text{partial}}}{N_{\text{total\_criteria}}} \times 100\%$$

Trong đó:
- $N_{\text{found}}$: Tiêu chí tìm thấy đầy đủ mọi trường bắt buộc (giá trị định lượng, đơn vị, năm báo cáo, năm cơ sở nếu là target).
- $N_{\text{partial}}$: Tiêu chí chỉ có từ khóa hoặc thiếu trường định lượng bắt buộc.
- $N_{\text{total\_criteria}}$: Tổng số tiêu chí trong bộ tiêu chuẩn của trụ cột đó.

---

## 6. Cấu trúc Cơ sở Dữ liệu & Lưu trữ (Storage Architecture)

Sử dụng cơ sở dữ liệu nhúng SQLite với cơ chế tự động di chuyển lược đồ (Auto-Migration) tại `data/esg.db`:

1. **`documents`**:
   - `id` (TEXT, PK): Định danh tài liệu (SHA-256 hash).
   - `name` (TEXT): Tên tệp báo cáo PDF.
   - `company` (TEXT), `year` (INTEGER): Siêu dữ liệu doanh nghiệp và năm phát hành.
   - `page_count` (INTEGER), `extraction_quality` (REAL): Số trang và chất lượng trích xuất văn bản.
2. **`chunks`**:
   - `id` (INTEGER, PK AUTOINCREMENT): Mã định danh đoạn trích.
   - `document_id` (TEXT, FK): Liên kết đến bảng `documents`.
   - `page` (INTEGER): Số trang PDF gốc (1-indexed).
   - `text` (TEXT): Nội dung văn bản của đoạn trích.
   - `section_title` (TEXT): Tiêu đề mục cha trích xuất theo layout.
   - `block_type` (TEXT): Loại khối (`text` hoặc `table`).
   - `block_id` (TEXT): Định danh khối nội dung.
   - `pillar` (TEXT): Trụ cột ESG liên quan (`E`, `S`, `G`).
3. **`chunks_fts`** (FTS5 Virtual Table):
   - Bảng ảo toàn văn bản hỗ trợ tìm kiếm từ khóa BM25 tốc độ cao với thuật toán porter stemmer.
4. **`chunk_embeddings`**:
   - `chunk_id` (INTEGER, PK): Khóa ngoại trỏ về `chunks`.
   - `embedding` (TEXT): Vector đặc trưng 384 chiều biểu diễn dưới dạng JSON float mảng.
