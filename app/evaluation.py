import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agents import RetrievalAgent


class ExpectedCitation(BaseModel):
    """Citation chuẩn (Ground Truth) gồm mã tài liệu và số trang kỳ vọng được đánh giá."""

    document_id: str
    page: int = Field(ge=1)


class RetrievalEvalCase(BaseModel):
    """Một trường hợp kiểm thử đánh giá: bao gồm ID, câu hỏi, query_scope (nếu có) và tập citation chuẩn."""

    id: str
    question: str
    query_scope: list[str] | None = None
    expected: list[ExpectedCitation]
    category: str | None = (
        "fact_retrieval"  # fact_retrieval, negative_evidence, table_retrieval, unanswerable, cross_page
    )


class EvaluationCaseResult(BaseModel):
    """Kết quả đo lường chi tiết chỉ số truy xuất của một câu hỏi kiểm thử.

    Chỉ số:
    - recall: Tỷ lệ citation chuẩn tìm được trong Top-K kết quả.
    - reciprocal_rank: Giá trị 1/vị_trí_xuất_hiện_đầu_tiên của citation đúng (dùng tính MRR).
    - precision: Tỷ lệ citation đúng trong tổng số kết quả trả về.
    - ndcg: Normalized Discounted Cumulative Gain tại Top-K.
    """

    id: str
    recall: float
    reciprocal_rank: float
    precision: float
    ndcg: float = 0.0
    retrieved: int


class RetrievalEvaluationReport(BaseModel):
    """Báo cáo tổng hợp chất lượng truy xuất toàn bộ test suite (Quality Gate)."""

    cases: int
    top_k: int
    recall_at_k: float
    mrr: float
    precision_at_k: float
    ndcg_at_k: float = 0.0
    details: list[EvaluationCaseResult]


class AblationSystemResult(BaseModel):
    """Kết quả đo lường cho một hệ thống trong nghiên cứu thực nghiệm bóc tách (Ablation Study)."""

    system: str
    recall_at_k: float
    mrr: float
    precision_at_k: float
    ndcg_at_k: float = 0.0


class RetrievalAblationReport(BaseModel):
    """Báo cáo tổng hợp Ablation Study so sánh BM25, Dense, Hybrid và Hybrid + Reranker."""

    cases: int
    top_k: int
    systems: list[AblationSystemResult]

    def to_markdown_table(self) -> str:
        """Xuất bảng định dạng Markdown chuẩn đẹp cho tài liệu nghiên cứu và Portfolio CV."""
        headers = (
            f"| System | Recall@{self.top_k} | MRR | Precision@{self.top_k} | nDCG@{self.top_k} |\n"
            f"|---|---:|---:|---:|---:|"
        )
        rows = [
            f"| {s.system} | **{s.recall_at_k:.2f}** | **{s.mrr:.2f}** | **{s.precision_at_k:.2f}** | **{s.ndcg_at_k:.2f}** |"
            for s in self.systems
        ]
        return "\n".join([headers, *rows])


# ==============================================================================
# TIER 2: STRUCTURED EXTRACTION EVALUATION
# ==============================================================================
class ExtractionEvalCase(BaseModel):
    """Ca kiểm thử năng lực trích xuất sự thật ESG có cấu trúc."""

    id: str
    question: str
    query_scope: list[str] | None = None
    expected_metric: str
    expected_value: float | str
    expected_unit: str | None = None
    expected_year: int | None = None
    tolerance: float = 0.05


class ExtractionEvaluationReport(BaseModel):
    """Báo cáo đo lường độ chính xác trích xuất số liệu ESG có cấu trúc."""

    cases: int
    exact_match: float
    numeric_tolerance_acc: float
    unit_acc: float
    year_acc: float
    details: list[dict[str, Any]] = Field(default_factory=list)


def load_evaluation_cases(path: Path) -> list[RetrievalEvalCase]:
    """Đọc tệp cấu hình JSON chứa danh sách câu hỏi kiểm thử và Ground Truth citations."""
    content = json.loads(path.read_text(encoding="utf-8"))
    return [RetrievalEvalCase.model_validate(item) for item in content]


def evaluate_retrieval(
    retrieval: RetrievalAgent,
    cases: list[RetrievalEvalCase],
    top_k: int = 5,
) -> RetrievalEvaluationReport:
    """Chạy toàn bộ tập đánh giá và tính toán các chỉ số thống kê `Recall@K`, `MRR`, `Precision@K`, `nDCG@K`."""
    details = [_evaluate_case(retrieval, case, top_k) for case in cases]
    count = len(details)
    return RetrievalEvaluationReport(
        cases=count,
        top_k=top_k,
        recall_at_k=_average(item.recall for item in details),
        mrr=_average(item.reciprocal_rank for item in details),
        precision_at_k=_average(item.precision for item in details),
        ndcg_at_k=_average(item.ndcg for item in details),
        details=details,
    )


def _evaluate_case(
    retrieval: RetrievalAgent,
    case: RetrievalEvalCase,
    top_k: int,
) -> EvaluationCaseResult:
    """Thực thi đánh giá cho một trường hợp câu hỏi kiểm thử cụ thể KHÔNG bị leakage document_id."""
    document_ids = case.query_scope
    citations = retrieval.run(case.question, top_k, document_ids)
    expected = {(item.document_id, item.page) for item in case.expected}
    retrieved = [(item.document_id, item.page) for item in citations]
    relevant_positions = [
        position for position, key in enumerate(retrieved, start=1) if key in expected
    ]
    matched = len(set(retrieved) & expected)

    # Tính nDCG@K
    dcg = 0.0
    for pos, key in enumerate(retrieved, start=1):
        if key in expected:
            dcg += 1.0 / math.log2(pos + 1)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(expected), top_k) + 1))
    ndcg = round(dcg / idcg, 4) if idcg > 0 else 0.0

    return EvaluationCaseResult(
        id=case.id,
        recall=round(matched / len(expected), 4) if expected else (1.0 if not retrieved else 0.0),
        reciprocal_rank=round(1 / relevant_positions[0], 4) if relevant_positions else 0,
        precision=round(matched / len(retrieved), 4) if retrieved else 0,
        ndcg=ndcg,
        retrieved=len(retrieved),
    )


def evaluate_retrieval_ablation(
    store: Any,
    cases: list[RetrievalEvalCase],
    top_k: int = 5,
) -> RetrievalAblationReport:
    """Chạy thực nghiệm bóc tách (Ablation Study) 4 cấu hình Retrieval."""
    systems_config = [
        ("BM25", "bm25"),
        ("Dense", "dense"),
        ("Hybrid", "hybrid"),
        ("Hybrid + Reranker", "hybrid_rerank"),
    ]
    systems_results: list[AblationSystemResult] = []
    for label, mode in systems_config:
        agent = RetrievalAgent(store, mode=mode)
        rep = evaluate_retrieval(agent, cases, top_k=top_k)
        systems_results.append(
            AblationSystemResult(
                system=label,
                recall_at_k=rep.recall_at_k,
                mrr=rep.mrr,
                precision_at_k=rep.precision_at_k,
                ndcg_at_k=rep.ndcg_at_k,
            )
        )
    return RetrievalAblationReport(cases=len(cases), top_k=top_k, systems=systems_results)


def evaluate_extraction(
    supervisor: Any,
    cases: list[ExtractionEvalCase],
    top_k: int = 6,
) -> ExtractionEvaluationReport:
    """Đo lường chất lượng trích xuất sự thật ESG có cấu trúc (Tier 2 Evaluation)."""
    details: list[dict[str, Any]] = []
    em_count = 0
    tol_count = 0
    unit_count = 0
    year_count = 0

    for case in cases:
        resp = supervisor.run(
            question=case.question,
            top_k=top_k,
            document_ids=case.query_scope,
            mode="qa",
        )
        facts = resp.extracted_facts
        matched_fact = next((f for f in facts if f.metric == case.expected_metric), None)

        is_em = False
        is_tol = False
        is_unit = False
        is_year = False

        if matched_fact and matched_fact.value is not None:
            if str(matched_fact.value).strip() == str(case.expected_value).strip():
                is_em = True

            try:
                actual_num = float(str(matched_fact.value).replace(",", ""))
                expected_num = float(str(case.expected_value).replace(",", ""))
                if (
                    expected_num != 0
                    and abs(actual_num - expected_num) / abs(expected_num) <= case.tolerance
                ):
                    is_tol = True
                elif actual_num == expected_num:
                    is_tol = True
            except (ValueError, TypeError):
                is_tol = is_em

            if (
                case.expected_unit
                and matched_fact.unit
                and case.expected_unit.lower() in matched_fact.unit.lower()
            ):
                is_unit = True
            elif not case.expected_unit:
                is_unit = True

            if case.expected_year and matched_fact.year == case.expected_year:
                is_year = True
            elif not case.expected_year:
                is_year = True

        if is_em:
            em_count += 1
        if is_tol:
            tol_count += 1
        if is_unit:
            unit_count += 1
        if is_year:
            year_count += 1

        details.append(
            {
                "case_id": case.id,
                "exact_match": is_em,
                "tolerance_match": is_tol,
                "unit_match": is_unit,
                "year_match": is_year,
                "extracted": matched_fact.model_dump() if matched_fact else None,
            }
        )

    total = max(1, len(cases))
    return ExtractionEvaluationReport(
        cases=len(cases),
        exact_match=round(em_count / total, 4),
        numeric_tolerance_acc=round(tol_count / total, 4),
        unit_acc=round(unit_count / total, 4),
        year_acc=round(year_count / total, 4),
        details=details,
    )


def _average(values: Iterable[float]) -> float:
    """Hàm phụ trợ tính giá trị trung bình an toàn."""
    items = list(values)
    return round(sum(items) / len(items), 4) if items else 0.0
