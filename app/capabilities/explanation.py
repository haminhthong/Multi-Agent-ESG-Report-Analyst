from typing import Literal

from app.llm import LLMClient, validate_answer_grounding
from app.models import Citation, GreenwashingScreeningResult, PillarResult


class ExplanationAgent:
    """Năng lực Tổng hợp Giải trình & Thẩm định Trích dẫn (Explanation Synthesis & Grounding).

    Nhiệm vụ:
    - Tổng hợp câu trả lời dựa trên trích đoạn bằng chứng đã qua xác thực.
    - Post-Generation Citation Grounding: Thẩm định nghiêm ngặt rằng mọi trích dẫn (Document, Page)
      trong câu trả lời do LLM sinh ra đều thuộc tập hợp bằng chứng đã truy xuất hợp lệ.
    - Deterministic Fallback: Tự động chuyển đổi sang bộ tổng hợp xác định khi offline ($0 cost).
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client

    def run(
        self,
        mode: Literal["qa", "audit"],
        pillars: list[PillarResult],
        overall_coverage: float,
        citations: list[Citation],
        question: str,
        screening_result: GreenwashingScreeningResult | None = None,
    ) -> str:
        """Tạo chuỗi giải thích rõ ràng kèm danh sách nguồn tài liệu và số trang tương ứng."""
        if self.llm and self.llm.is_available() and citations:
            rubric_summary = f"Coverage {overall_coverage}%. " + ", ".join(
                f"{p.pillar}: {p.disclosure_coverage}%" for p in pillars
            )
            # Chuẩn bị citation kèm citation IDs [C1], [C2]
            citation_payload = []
            for idx, c in enumerate(citations[:6], start=1):
                cd = c.model_dump()
                cd["cid"] = f"[C{idx}]"
                citation_payload.append(cd)

            llm_answer = self.llm.synthesize_answer(
                question=question,
                citations=citation_payload,
                rubric_summary=rubric_summary,
            )
            if llm_answer and len(llm_answer.strip()) > 20:
                is_grounded, _issues = validate_answer_grounding(llm_answer, citation_payload)
                if is_grounded:
                    return llm_answer
                # Fallback deterministic khi grounding thất bại (hallucinated page/C-id/số liệu)

        sources = (
            ", ".join(f"[{item.document_name}, trang {item.page}]" for item in citations[:6])
            or "không có citation"
        )

        risk_snippet = (
            f" [Screening Risk: {screening_result.risk_level}]" if screening_result else ""
        )

        if mode == "qa":
            if not citations:
                return (
                    f"Hệ thống không tìm thấy bằng chứng hợp lệ trong tài liệu để trả lời cho câu hỏi: '{question}'. "
                    "Kết quả này phản ánh khoảng trống thông tin trong các trang đã truy xuất."
                )
            key_metrics = [f for p in pillars for f in p.findings if "Hệ thống" not in f][:1]
            metric_snippet = f" Ghi nhận: {key_metrics[0]}." if key_metrics else ""
            excerpt_snippet = (
                f' Trích dẫn chính: "{citations[0].excerpt[:200]}..."' if citations else ""
            )
            return (
                f"Trả lời dựa trên bằng chứng truy xuất cho câu hỏi '{question}'{risk_snippet}: "
                f"Tìm thấy {len(citations)} đoạn văn bản nguồn tại {sources}.{metric_snippet}{excerpt_snippet}"
            )
        else:
            scores_str = ", ".join(
                f"{item.pillar}: coverage {item.disclosure_coverage}% (quality {item.evidence_quality}%)"
                for item in pillars
            )
            return (
                f"Hệ thống tìm thấy bằng chứng công bố cho {overall_coverage}% tổng số tiêu chí E/S/G kiểm tra{risk_snippet}. "
                f"Chi tiết từng trụ cột: {scores_str}. Nguồn trích dẫn: {sources}. "
                "Lưu ý: Kết quả phản ánh mức độ công bố thông tin trong các đoạn đã truy xuất, không phản ánh hiệu suất ESG tổng thể của doanh nghiệp."
            )
