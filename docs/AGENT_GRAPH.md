# Agent Graph và Supervisor Runtime

Tài liệu này mô tả graph agent thực tế trong `app/workflow.py` và runtime bounded trong `app/agent_runtime.py`. Graph là lớp điều phối của workflow; các thao tác đọc PDF, OCR, truy xuất, trích xuất fact, kiểm tra citation, rubric và lưu SQLite vẫn được thực hiện bởi service deterministic.

## Route chuẩn

```text
ScopeAgent
  → QueryPlanningAgent
  → RetrievalAgent
  → EvidenceVerificationAgent       (chỉ khi có citation thô)
  → EvidenceExtractionAgent         (chỉ khi có citation đã validate)
  → EvidenceCompletenessGate
  → ESGAuditAgent
  → SpecializedAnalysis              (chỉ temporal_trend/cross_document_compare)
  → ClaimVerificationAgent
  → ExplanationAgent
  → AnswerReviewAgent
  → LimitationsAgent
  → END
```

Nhánh rẽ được kiểm soát như sau:

| Điểm quyết định | Điều kiện | Hướng đi |
|---|---|---|
| Sau retrieval | Không có citation thô | Bỏ qua verification/extraction, đi thẳng đến completeness gate |
| Sau verification | Không còn citation hợp lệ | Bỏ qua extraction, đi đến completeness gate |
| Completeness gate | Thiếu hoặc partial required evidence | Chạy targeted retry tối đa cho các yêu cầu đầu tiên, sau đó vẫn tiếp tục với limitation rõ ràng |
| Sau ESG audit | Intent là `temporal_trend` hoặc `cross_document_compare` | Chạy `SpecializedAnalysis` trên accepted facts |
| Sau ESG audit | Intent khác | Đi thẳng đến claim verification |
| Screening | Chỉ `mode=audit` | Chạy screening heuristic và gắn `screening_priority` vào response |

## Trách nhiệm của từng node

| Node | Trách nhiệm | Dữ liệu tạo hoặc cập nhật |
|---|---|---|
| `ScopeAgent` | Lọc document IDs không tồn tại và ghi warning | `AnalysisState.document_ids`, `warnings` |
| `QueryPlanningAgent` | Chuyển câu hỏi thành plan typed | `RetrievalPlan`: intent, subqueries, criteria, metrics, years, required evidence |
| `RetrievalAgent` | Tìm bằng chứng theo plan; audit truy xuất thêm theo từng criterion | `raw_citations`, `criterion_bundles` |
| `EvidenceVerificationAgent` | Kiểm tra document, page, excerpt và provenance | `validated_citations` |
| `EvidenceExtractionAgent` | Trích xuất fact tạm thời và phát hiện conflict | `extracted_facts`, `conflicts` |
| `EvidenceCompletenessGate` | Đối chiếu required evidence, retry mục tiêu khi thiếu | `evidence_completeness`, `trace_steps` |
| `ESGAuditAgent` | Chạy rubric và evidence matrix; audit mới chạy screening | `pillars`, `evidence_matrix`, `screening_result` |
| `SpecializedAnalysis` | Temporal hoặc comparison dựa trên accepted fact repository | `temporal_analysis` hoặc `comparison` |
| `ClaimVerificationAgent` | Gắn evidence IDs và kiểm tra claim overlap | `claims`, `verification_summary` |
| `ExplanationAgent` | Sinh câu trả lời từ citation đã validate | `answer` |
| `AnswerReviewAgent` | Kiểm tra citation và grounding; fallback deterministic nếu cần | `answer`, `verification_summary.answer_review` |
| `LimitationsAgent` | Công bố giới hạn, missing evidence và warning | `limitations` |

## Bounded execution và an toàn

`AgentGraphSupervisor` nhận một `AnalysisState`, một mapping node và node bắt đầu. Runtime:

- giới hạn mặc định là `max_steps=16`;
- dừng với `max_steps_reached` nếu graph chạy quá giới hạn;
- dừng với `cycle_detected` nếu node lặp lại;
- ghi từng dispatch, handoff và stop reason vào `AnalysisState.trace`;
- trả `agent_route` và `agent_stop_reason` để API, dashboard và test có thể kiểm chứng.

Graph được tạo mới cho từng request, vì vậy closure của một request không dùng chung state với request khác.

## Ba mode thực thi

`AnalysisRequest.agent_mode` là mode được yêu cầu từ API/CLI:

- `deterministic`: tắt LLM và chạy fallback local;
- `orchestrated`: planner deterministic nhưng vẫn dùng graph supervisor;
- `agentic`: ưu tiên local LLM nếu `USE_LLM=true` và endpoint phản hồi, nếu không thì fallback.

Response ghi thêm mode thực tế đã resolve: `llm_agentic`, `agent_orchestrated` hoặc `deterministic_fallback`. Vì vậy người dùng không phải suy đoán LLM có thật sự được gọi hay không.

## Handoff contract

Các node không truyền dữ liệu tự do cho nhau. Chúng cùng đọc/ghi `AnalysisState` với những vùng dữ liệu chính:

```text
question + scope
  → RetrievalPlan
  → raw_citations
  → validated_citations
  → extracted_facts + conflicts
  → evidence_completeness
  → pillars + evidence_matrix
  → accepted temporal/comparison (nếu cần)
  → claims + verification_summary
  → answer + limitations + trace
```

Response cuối cùng mang theo `request_id`, `status`, `versions`, `agent_route`, `trace_steps`, `claims`, `citations`, `evidence_completeness` và các kết quả audit để tái kiểm tra được quyết định.
