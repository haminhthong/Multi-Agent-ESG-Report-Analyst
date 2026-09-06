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

    @staticmethod
    def detect_conflicts(facts: list[ESGFact]) -> list[EvidenceConflict]:
        return EvidenceExtractionAgent.detect_conflicts(facts)
