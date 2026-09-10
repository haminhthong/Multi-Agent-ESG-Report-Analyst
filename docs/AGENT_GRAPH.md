# Workflow roles và service boundaries

`app/workflow.py` có một graph ngắn gồm bốn role. Graph chỉ điều phối các
stage; những phép tính cần kiểm chứng vẫn nằm trong service deterministic.
Điều này giúp route dễ quan sát mà không biến từng hàm validation thành một
agent độc lập.

## Route thực tế

```text
Planner → Evidence → Analysis → Answer → END
```

`AgentGraphSupervisor` trong `app/agent_runtime.py` vẫn giới hạn số bước,
phát hiện cycle và ghi `agent_route`/`agent_stop_reason` vào response. Graph
được tạo theo từng request nên closure không dùng chung state giữa các request.

## Trách nhiệm theo role

| Role | Công việc điều phối | Service/capability được gọi | State chính |
|---|---|---|---|
| `Planner` | Kiểm tra document scope và lập kế hoạch truy xuất | `QueryPlanner` | `plan`, `warnings` |
| `Evidence` | Tìm, kiểm tra citation, trích xuất fact tạm thời và kiểm tra completeness | `EvidenceRetriever`, `CitationVerifier`, `FactExtractor`, `EvidenceCompletenessGate` | `raw_citations`, `validated_citations`, `extracted_facts`, `evidence_completeness` |
| `Analysis` | Chạy rubric, evidence matrix và intent-specific analysis | `ESGAnalysisService`, `TemporalAnalyzer`, `CompanyComparisonService`, screening service | `pillars`, `evidence_matrix`, `temporal_analysis`, `comparison`, `screening_result` |
| `Answer` | Kiểm tra claim, tổng hợp và xác nhận grounding | `CitationVerifier`, `AnswerGenerator`, `AnswerValidator` | `claims`, `answer`, `limitations`, `verification_summary` |

## Luồng dữ liệu

```text
question + scope
    ↓
RetrievalPlan
    ↓
raw citations → validated citations
    ↓
temporary facts + conflicts → completeness status
    ↓
rubric / evidence matrix / accepted-fact analysis
    ↓
claims → grounded answer + limitations + trace
```

Completeness không phải một role riêng. Trong `Evidence` stage, gate có thể
chạy targeted retrieval cho các trường `missing` hoặc `partial`; nếu vẫn thiếu,
pipeline tiếp tục nhưng ghi rõ giới hạn thay vì suy diễn trend.

Temporal và comparison là các nhánh nghiệp vụ của `Analysis`, không phải
agent mới. Hai nhánh này đọc accepted facts từ `FactRepository`; fact tạm thời
trích từ citation online không tự động trở thành canonical fact.

## Offline fact lifecycle

```text
PDF
  ↓ native extraction / OCR / stable chunks
fact_candidate
  ↓ validator hoặc human review
rejected | conflict | accepted
                         ↓
                     esg_fact
                         ↓
               temporal / comparison / audit
```

Mọi claim cuối phải trỏ được tới citation có `document_id`, `page`, excerpt và
`evidence_id`. Citation validation kiểm tra provenance của dữ liệu đã truy xuất;
nó không phải xác minh độc lập tính trung thực của doanh nghiệp.

## Execution modes

- `deterministic`: tắt LLM và chạy local fallback.
- `orchestrated`: dùng planner deterministic, chạy bốn role qua supervisor.
- `agentic`: ưu tiên local LLM cho planning/synthesis nếu endpoint sẵn sàng,
  nếu không thì fallback.

Response ghi mode yêu cầu và mode thực tế (`llm_agentic`,
`agent_orchestrated` hoặc `deterministic_fallback`) để dễ kiểm tra.
