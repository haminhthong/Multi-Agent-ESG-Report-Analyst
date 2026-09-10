import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.grounding import CitationVerifier


class AnswerEvalCase(BaseModel):
    """Trường hợp kiểm thử chất lượng câu trả lời và trích dẫn."""

    id: str
    question: str
    query_scope: list[str] | None = None
    expected_topics: list[str] = Field(default_factory=list)
    expected_numbers: list[str] = Field(default_factory=list)
    expected_evidence: list[dict[str, Any]] = Field(default_factory=list)


class CaseAnswerMetric(BaseModel):
    """Kết quả đo lường chất lượng câu trả lời cho một câu hỏi."""

    id: str
    citation_correctness: float
    faithfulness: float
    completeness: float
    unsupported_claim_rate: float
    cited_count: int
    unsupported_claims: list[str] = Field(default_factory=list)
    gold_citation_precision: float | None = None
    gold_citation_recall: float | None = None


class AnswerEvaluationReport(BaseModel):
    """Báo cáo tổng hợp chất lượng câu trả lời (RAG Triad & Hallucination Guardrails)."""

    cases: int
    faithfulness: float
    citation_correctness: float
    completeness: float
    unsupported_claim_rate: float
    gold_citation_precision: float | None = None
    gold_citation_recall: float | None = None
    details: list[CaseAnswerMetric]


def load_answer_eval_cases(path: Path) -> list[AnswerEvalCase]:
    """Nạp danh sách các ca kiểm thử câu trả lời từ file JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [AnswerEvalCase.model_validate(item) for item in data]


def evaluate_answer_quality(
    pipeline: Any,
    cases: list[AnswerEvalCase],
    top_k: int = 5,
) -> AnswerEvaluationReport:
    """Thực thi đánh giá toàn bộ test suite về chất lượng câu trả lời:
    - Citation Correctness: Tính chính xác của trích dẫn (tài liệu, số trang thực).
    - Answer Faithfulness: Tỷ lệ các khẳng định được hỗ trợ bởi bằng chứng (Groundedness).
    - Answer Completeness: Mức độ bao phủ các ý và số liệu kỳ vọng.
    - Unsupported Claim Rate: Tỷ lệ khẳng định không có căn cứ (Hallucination rate).
    """
    results: list[CaseAnswerMetric] = []
    for case in cases:
        resp = pipeline.run(
            question=case.question,
            top_k=top_k,
            document_ids=case.query_scope,
            mode="qa",
        )
        metric = _evaluate_single_answer(resp, case)
        results.append(metric)

    return AnswerEvaluationReport(
        cases=len(results),
        faithfulness=_average(r.faithfulness for r in results),
        citation_correctness=_average(r.citation_correctness for r in results),
        completeness=_average(r.completeness for r in results),
        unsupported_claim_rate=_average(r.unsupported_claim_rate for r in results),
        gold_citation_precision=_average(
            [r.gold_citation_precision for r in results if r.gold_citation_precision is not None]
        )
        if any(r.gold_citation_precision is not None for r in results)
        else None,
        gold_citation_recall=_average(
            [r.gold_citation_recall for r in results if r.gold_citation_recall is not None]
        )
        if any(r.gold_citation_recall is not None for r in results)
        else None,
        details=results,
    )


def _evaluate_single_answer(response: Any, case: AnswerEvalCase) -> CaseAnswerMetric:
    """Đánh giá chi tiết một câu trả lời đơn lẻ."""
    answer_text = response.answer
    citations = response.citations

    # 1. Đo độ đúng của citation và mức neo vào bằng chứng chuẩn.
    cited_references = re.findall(r"\[([^,]+),\s*trang\s*(\d+)\]", answer_text, re.IGNORECASE)
    valid_citations = 0
    available_pages = {(c.document_name.lower(), c.page) for c in citations}
    for c in citations:
        available_pages.add((c.document_id.lower(), c.page))

    if cited_references:
        for doc_name, page_str in cited_references:
            page = int(page_str)
            if any(doc_name.lower() in p[0] and page == p[1] for p in available_pages):
                valid_citations += 1
        citation_corr = round(valid_citations / len(cited_references), 4)
    else:
        citation_corr = 1.0 if not citations else 0.5

    # Chỉ số citation chuẩn: Precision và Recall so với expected_evidence.
    gold_precision: float | None = None
    gold_recall: float | None = None
    if case.expected_evidence:
        expected_set = {
            (str(e.get("document_id", "")).lower(), int(e.get("page", 0)))
            for e in case.expected_evidence
        }
        retrieved_set = {(str(c.document_id).lower(), c.page) for c in citations}
        matched = expected_set.intersection(retrieved_set)
        gold_precision = round(len(matched) / max(1, len(retrieved_set)), 4)
        gold_recall = round(len(matched) / max(1, len(expected_set)), 4)

    # 2. Đo tính trung thành và tỷ lệ claim không có bằng chứng.
    sentences = [s.strip() for s in re.split(r"[.\n]+", answer_text) if len(s.strip()) > 15]
    factual_sentences = [
        s for s in sentences if any(char.isdigit() for char in s) or len(s.split()) >= 6
    ]

    combined_evidence = " ".join(c.excerpt for c in citations)
    supported_count = 0
    unsupported: list[str] = []

    for s in factual_sentences:
        res = CitationVerifier.verify_claim(s, combined_evidence)
        if res["supported"]:
            supported_count += 1
        else:
            if any(
                p in s.lower()
                for p in (
                    "không tìm thấy",
                    "dựa trên bằng chứng",
                    "mức độ công bố",
                    "trích dẫn",
                    "đoạn văn bản nguồn",
                    "ghi nhận:",
                )
            ):
                supported_count += 1
            else:
                unsupported.append(s)

    total_facts = max(1, len(factual_sentences))
    faithfulness = round(supported_count / total_facts, 4)
    unsupported_rate = round(len(unsupported) / total_facts, 4)

    # 3. Đo mức độ đầy đủ của câu trả lời.
    matched_topics = sum(1 for t in case.expected_topics if t.lower() in answer_text.lower())
    matched_numbers = sum(1 for n in case.expected_numbers if n.lower() in answer_text.lower())
    total_expectations = len(case.expected_topics) + len(case.expected_numbers)

    if total_expectations > 0:
        completeness = round((matched_topics + matched_numbers) / total_expectations, 4)
    else:
        completeness = 1.0 if len(citations) > 0 else 0.0

    return CaseAnswerMetric(
        id=case.id,
        citation_correctness=citation_corr,
        faithfulness=faithfulness,
        completeness=completeness,
        unsupported_claim_rate=unsupported_rate,
        cited_count=len(cited_references),
        unsupported_claims=unsupported,
        gold_citation_precision=gold_precision,
        gold_citation_recall=gold_recall,
    )


def _average(values: Iterable[float]) -> float:
    items = list(values)
    return round(sum(items) / len(items), 4) if items else 0.0
