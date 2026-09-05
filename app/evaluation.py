import json
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


class EvaluationCaseResult(BaseModel):
    """Kết quả đo lường chi tiết chỉ số truy xuất của một câu hỏi kiểm thử.

    Chỉ số:
    - recall: Tỷ lệ citation chuẩn tìm được trong Top-K kết quả.
    - reciprocal_rank: Giá trị 1/vị_trí_xuất_hiện_đầu_tiên của citation đúng (dùng tính MRR).
    - precision: Tỷ lệ citation đúng trong tổng số kết quả trả về.
    """

    id: str
    recall: float
    reciprocal_rank: float
    precision: float
    retrieved: int


class RetrievalEvaluationReport(BaseModel):
    """Báo cáo tổng hợp chất lượng truy xuất toàn bộ test suite.

    Sử dụng làm Quality Gate trong CI/CD pipeline để đảm bảo không bị suy giảm hiệu năng (regression).
    """

    cases: int
    top_k: int
    recall_at_k: float
    mrr: float
    precision_at_k: float
    details: list[EvaluationCaseResult]


class AblationSystemResult(BaseModel):
    """Kết quả đo lường cho một hệ thống trong nghiên cứu thực nghiệm bóc tách (Ablation Study)."""

    system: str
    recall_at_k: float
    mrr: float
    precision_at_k: float


class RetrievalAblationReport(BaseModel):
    """Báo cáo tổng hợp Ablation Study so sánh BM25, Dense, Hybrid và Hybrid + Reranker."""

    cases: int
    top_k: int
    systems: list[AblationSystemResult]

    def to_markdown_table(self) -> str:
        """Xuất bảng định dạng Markdown chuẩn đẹp cho tài liệu nghiên cứu và Portfolio CV."""
        headers = (
            f"| System | Recall@{self.top_k} | MRR | Precision@{self.top_k} |\n|---|---:|---:|---:|"
        )
        rows = [
            f"| {s.system} | **{s.recall_at_k:.2f}** | **{s.mrr:.2f}** | **{s.precision_at_k:.2f}** |"
            for s in self.systems
        ]
        return "\n".join([headers, *rows])


def load_evaluation_cases(path: Path) -> list[RetrievalEvalCase]:
    """Đọc tệp cấu hình JSON chứa danh sách câu hỏi kiểm thử và Ground Truth citations."""

    content = json.loads(path.read_text(encoding="utf-8"))
    return [RetrievalEvalCase.model_validate(item) for item in content]


def evaluate_retrieval(
    retrieval: RetrievalAgent,
    cases: list[RetrievalEvalCase],
    top_k: int = 5,
) -> RetrievalEvaluationReport:
    """Chạy toàn bộ tập đánh giá và tính toán các chỉ số thống kê `Recall@K`, `MRR`, `Precision@K`.

    Tham số:
        retrieval: Thể hiện của RetrievalAgent.
        cases: Danh sách các trường hợp kiểm thử (eval cases).
        top_k: Số lượng citation tối đa lấy ra cho mỗi câu hỏi.
    """

    details = [_evaluate_case(retrieval, case, top_k) for case in cases]
    count = len(details)
    return RetrievalEvaluationReport(
        cases=count,
        top_k=top_k,
        recall_at_k=_average(item.recall for item in details),
        mrr=_average(item.reciprocal_rank for item in details),
        precision_at_k=_average(item.precision for item in details),
        details=details,
    )


def _evaluate_case(
    retrieval: RetrievalAgent,
    case: RetrievalEvalCase,
    top_k: int,
) -> EvaluationCaseResult:
    """Thực thi đánh giá cho một trường hợp câu hỏi kiểm thử cụ thể KHÔNG bị leakage document_id."""

    # KHÔNG lấy document_ids từ case.expected (loại bỏ leakage)
    document_ids = case.query_scope
    citations = retrieval.run(case.question, top_k, document_ids)
    expected = {(item.document_id, item.page) for item in case.expected}
    retrieved = [(item.document_id, item.page) for item in citations]
    relevant_positions = [
        position for position, key in enumerate(retrieved, start=1) if key in expected
    ]
    matched = len(set(retrieved) & expected)
    return EvaluationCaseResult(
        id=case.id,
        recall=round(matched / len(expected), 4) if expected else 0,
        reciprocal_rank=round(1 / relevant_positions[0], 4) if relevant_positions else 0,
        precision=round(matched / len(retrieved), 4) if retrieved else 0,
        retrieved=len(retrieved),
    )


def evaluate_retrieval_ablation(
    store: Any,
    cases: list[RetrievalEvalCase],
    top_k: int = 5,
) -> RetrievalAblationReport:
    """Chạy thực nghiệm bóc tách (Ablation Study) 4 cấu hình Retrieval:
    1. BM25 (SQLite FTS5 Full-Text)
    2. Dense (Sentence-Transformers MiniLM Cosine)
    3. Hybrid (BM25 + Dense RRF Fusion)
    4. Hybrid + Reranker (Cross-Encoder Re-ranking)
    """
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
            )
        )
    return RetrievalAblationReport(cases=len(cases), top_k=top_k, systems=systems_results)


def _average(values: Iterable[float]) -> float:
    """Hàm phụ trợ tính giá trị trung bình an toàn (tránh lỗi chia cho 0)."""

    items = list(values)
    return round(sum(items) / len(items), 4) if items else 0.0
