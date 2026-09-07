"""Grounded answer synthesis with a deterministic fallback."""

from __future__ import annotations

from typing import Literal

from app.llm import LLMClient, validate_answer_grounding
from app.models import Citation, GreenwashingScreeningResult, PillarResult


class ExplanationAgent:
    """Synthesize a response only from retrieved evidence and audit outputs."""

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
                    from app.capabilities.verification import EvidenceVerificationAgent

                    claim_grounded, _ = EvidenceVerificationAgent.verify_claim_grounding(
                        answer, citations[:6], llm_client=self.llm
                    )
                    if claim_grounded:
                        return answer

        return self._deterministic_answer(
            mode,
            pillars,
            overall_coverage,
            citations,
            question,
            screening_result,
        )

    @staticmethod
    def _deterministic_answer(
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
                f"Evidence-grounded response to '{question}': {excerpt} [C1] "
                f"Sources: {sources}. Screening risk: {risk}."
            )

        pillar_summary = ", ".join(
            f"{pillar.pillar} {pillar.disclosure_coverage}%" for pillar in pillars
        )
        return (
            f"Indexed-evidence disclosure coverage: {overall_coverage}%. [C1] "
            f"Pillars: {pillar_summary}. [C1] Screening risk: {risk}. [C1] "
            f"Sources: {sources}. [C1] Coverage measures disclosure evidence presence, "
            "not the company's underlying ESG performance. [C1]"
        )
