"""Evidence validation and claim-support checks.

This capability validates citation metadata/excerpts and performs lightweight
claim-to-evidence matching. It must not be described as independent factual
verification of the issuer's ESG disclosure.
"""

from __future__ import annotations

import re
from typing import Any

from app.evidence_extractor import EvidenceExtractionAgent
from app.models import Citation, ESGFact, EvidenceConflict
from app.tools import AgentTools


class EvidenceVerificationAgent:
    """Validate retrieved evidence before downstream analysis."""

    @staticmethod
    def validate(citations: list[Citation]) -> list[Citation]:
        valid: list[Citation] = []
        seen: set[tuple[str, int, str]] = set()

        for citation in citations:
            normalized = re.sub(r"\W+", " ", citation.excerpt.lower()).strip()
            signature = (citation.document_id, citation.page, normalized[:160])

            if citation.page < 1:
                citation.validation_status = "rejected"
                citation.validated = False
                continue
            if len(normalized.split()) < 3:
                citation.validation_status = "rejected"
                citation.validated = False
                continue
            if not citation.document_id or not citation.document_name:
                citation.validation_status = "rejected"
                citation.validated = False
                continue
            if signature in seen:
                continue

            seen.add(signature)
            citation.validated = True
            citation.validation_status = "valid"
            valid.append(citation)

        return valid

    @staticmethod
    def audit_claims(claims: list[str], citations: list[Citation]) -> dict[str, Any]:
        """Estimate whether claim tokens are supported by retrieved excerpts."""
        combined_text = " ".join(c.excerpt for c in citations)
        audits: list[dict[str, Any]] = []
        supported_count = 0

        for claim in claims:
            result = AgentTools.verify_claim(claim, combined_text)
            audits.append({"claim": claim, **result})
            if result["supported"]:
                supported_count += 1

        total = max(1, len(claims))
        return {
            "audits": audits,
            "supported_rate": round(supported_count / total, 4),
            "total_claims": len(claims),
            "unsupported_claims": [a["claim"] for a in audits if not a["supported"]],
            "verification_scope": "retrieved_excerpt_support",
        }

    @classmethod
    def verify_claim_grounding(
        cls,
        answer: str,
        citations: list[Citation],
        llm_client: Any | None = None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Thẩm định tính grounding cấp claim đối chiếu trực tiếp với từng citation được dẫn chiếu."""
        claims = ClaimSplitter.split(answer)
        claim_results: list[dict[str, Any]] = []
        all_grounded = True

        for claim_text, cids in claims:
            if not cids:
                claim_results.append(
                    {
                        "claim": claim_text,
                        "cids": [],
                        "grounded": True,
                        "reason": "general_statement",
                    }
                )
                continue

            claim_grounded = True
            failure_reasons = []

            for cid in cids:
                cite_idx = cid - 1
                if cite_idx < 0 or cite_idx >= len(citations):
                    claim_grounded = False
                    failure_reasons.append(f"invalid_cid_C{cid}")
                    continue

                cite = citations[cite_idx]
                cite_text = cite.excerpt.lower()

                # 1. Fast Path: Kiểm tra số liệu định lượng
                claim_numbers = re.findall(r"\b\d+(?:[.,]\d+)?\b", claim_text)
                for num in claim_numbers:
                    if num == str(cid) and f"[C{num}]" in claim_text:
                        continue
                    if (
                        len(num) >= 2
                        and num not in cite_text
                        and num.replace(",", ".") not in cite_text
                    ):
                        claim_grounded = False
                        failure_reasons.append(f"unsupported_number_{num}_in_C{cid}")

                # 2. NLI Path: Nếu LLM khả dụng
                if llm_client and hasattr(llm_client, "is_available") and llm_client.is_available():
                    nli_ok = llm_client.verify_grounding(claim_text, cite.excerpt)
                    if not nli_ok:
                        claim_grounded = False
                        failure_reasons.append(f"nli_grounding_failed_for_C{cid}")

            if not claim_grounded:
                all_grounded = False

            claim_results.append(
                {
                    "claim": claim_text,
                    "cids": cids,
                    "grounded": claim_grounded,
                    "reasons": failure_reasons,
                }
            )

        return all_grounded, claim_results

    @staticmethod
    def detect_conflicts(facts: list[ESGFact]) -> list[EvidenceConflict]:
        return EvidenceExtractionAgent.detect_conflicts(facts)


class ClaimSplitter:
    """Tách câu trả lời thành từng claim con gắn với citation tag."""

    @staticmethod
    def split(text: str) -> list[tuple[str, list[int]]]:
        """Tách các mệnh đề và trích xuất danh sách citation index (ví dụ [C1], [C2])."""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
        claims = []
        for s in sentences:
            cids = [int(m.group(1)) for m in re.finditer(r"\[C(\d+)\]", s, re.IGNORECASE)]
            claims.append((s, cids))
        return claims


EvidenceValidator = EvidenceVerificationAgent
