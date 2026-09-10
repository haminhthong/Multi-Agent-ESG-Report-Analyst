# Pipeline và data contracts

ESGPipeline trong app/pipeline.py là đường chạy duy nhất cho API, CLI và evaluation. Pipeline tuần tự, không có graph runtime, tool dispatcher hay execution mode do LLM lựa chọn.

## Luồng chạy

~~~~text
question + document scope
    ↓
validate scope
    ↓
RetrievalPlan
    ↓
BM25 / dense / hybrid retrieval
    ↓
raw citations → validated citations
    ↓
temporary ESG facts + conflicts
    ↓
evidence completeness
    ↓
rubric / temporal / comparison / screening
    ↓
claim checks
    ↓
deterministic answer hoặc optional LLM synthesis
    ↓
grounded answer + citations + limitations
~~~~

Các API và CLI chỉ là adapter. Chúng không tự lắp ráp retrieval, extraction hoặc validation.

## Ranh giới deterministic và optional LLM

| Thành phần | Quyết định |
|---|---|
| PDF extraction, OCR, layout và chunking | Deterministic |
| BM25, dense, hybrid, RRF và reranking | Deterministic theo cấu hình/model |
| Citation page/provenance validation | Deterministic |
| Metric, unit, year normalization | Deterministic |
| Candidate/accepted fact lifecycle | Deterministic + review |
| Rubric, evidence matrix, temporal, comparison | Deterministic |
| Answer synthesis | Deterministic mặc định; LLM optional |
| Claim grounding | Deterministic trước; LLM optional bổ sung |

LLM không được phép tự chọn tool, bỏ qua evidence gate hoặc biến extraction chưa review thành accepted fact.

## Data contracts

| Giai đoạn | Input | Output |
|---|---|---|
| Ingestion | PDF bytes và metadata | documents, pages, layout blocks |
| Chunking/indexing | blocks đã chuẩn hóa | stable chunks, FTS5, optional embeddings |
| Retrieval | câu hỏi hoặc RetrievalPlan | Citation candidates |
| Verification | candidates | citations hợp lệ có page, excerpt, evidence ID |
| Extraction | citations hợp lệ | ESGFact candidates và conflicts |
| Review | fact ID và quyết định | accepted/rejected/conflict lifecycle |
| Analysis | citations, accepted facts, rubric | pillars, matrix, temporal/comparison/screening |
| Answer | question, analysis, citations | answer, claim support, limitations |

fact_candidates là dữ liệu chờ review. Temporal và comparison mặc định đọc accepted facts từ FactRepository; fact tạm thời trong một request không tự động trở thành canonical.

## Fact lifecycle và provenance

~~~~text
PDF
 ↓ native extraction / OCR / stable chunk
fact_candidate
 ↓ validator hoặc analyst review
rejected | conflict | accepted
                         ↓
                    accepted fact
                         ↓
               temporal / comparison / audit
~~~~

Mỗi claim cần có đường dẫn tới evidence:

~~~~text
Claim
 ↓
Evidence ID
 ↓
Document + page + section
 ↓
Stable chunk / excerpt
 ↓
Fact candidate hoặc accepted fact
~~~~

Citation validation kiểm tra tính nhất quán của dữ liệu đã truy xuất. Nó không phải xác minh độc lập tính trung thực của báo cáo.

## Completeness và hạn chế

Nếu câu hỏi yêu cầu nhiều năm hoặc nhiều metric nhưng retrieval chỉ tìm thấy một phần, pipeline trả trạng thái partial/missing và thêm limitation. Pipeline không tự gắn nhãn trend hoàn chỉnh từ một năm duy nhất.

Greenwashing screening chỉ tạo disclosure-risk signals cần analyst review. Nó không phải fraud detector, xác suất greenwashing hay kết luận pháp lý.

