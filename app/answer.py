"""Tổng hợp câu trả lời có bằng chứng với fallback deterministic."""

from __future__ import annotations

from typing import Literal

from app.llm import LLMClient, validate_answer_grounding
from app.models import Citation, GreenwashingScreeningResult, PillarResult


class AnswerGenerator:
    """Sinh câu trả lời chỉ từ bằng chứng và kết quả audit đã có."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
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
        if self.llm and self.llm.is_available() and citations:
            rubric_summary = f"Coverage {overall_coverage}%. " + ", ".join(
                f"{pillar.pillar}: {pillar.disclosure_coverage}%" for pillar in pillars
            )
            payload: list[dict] = []
            for index, citation in enumerate(citations[:6], start=1):
                item = citation.model_dump()
                item["cid"] = f"[C{index}]"
                payload.append(item)

            answer = self.llm.synthesize_answer(
                question=question,
                citations=payload,
                rubric_summary=rubric_summary,
            )
            if answer and len(answer.strip()) > 20:
                grounded, _ = validate_answer_grounding(answer, payload)
                if grounded:
                    from app.grounding import CitationVerifier

                    claim_grounded, _ = CitationVerifier.verify_claim_grounding(
                        answer, citations[:6], llm_client=self.llm
                    )
                    if claim_grounded:
                        return answer

        return self.build_deterministic_answer(
            mode,
            pillars,
            overall_coverage,
            citations,
            question,
            screening_result,
        )

    @staticmethod
    def build_deterministic_answer(
        mode: Literal["qa", "audit"],
        pillars: list[PillarResult],
        overall_coverage: float,
        citations: list[Citation],
        question: str,
        screening_result: GreenwashingScreeningResult | None,
    ) -> str:
        if not citations:
            return (
                "No validated evidence was retrieved for this request. "
                "The system therefore does not make an ESG conclusion."
            )

        sources = ", ".join(
            f"[C{index}] [{citation.document_name}, page {citation.page}]"
            for index, citation in enumerate(citations[:6], start=1)
        )
        risk = screening_result.risk_level if screening_result else "not-run"

        if mode == "qa":
            excerpt = citations[0].excerpt[:220].strip()
            return (
                f"Evidence-grounded response to '{question}': {excerpt} [C1]\n\n"
                f"Evidence sources: {sources}. Screening risk: {risk}."
            )

        pillar_summary = ", ".join(
            f"{pillar.pillar}: {pillar.disclosure_coverage}%" for pillar in pillars
        )
        return (
            f"Disclosure coverage computed from indexed evidence: {overall_coverage}%.\n"
            f"Pillars: {pillar_summary}.\n"
            f"Screening risk: {risk}.\n\n"
            f"Evidence reviewed: {sources}.\n\n"
            "Coverage measures the presence of disclosure evidence in the indexed "
            "corpus, not the company's actual ESG performance."
        )
