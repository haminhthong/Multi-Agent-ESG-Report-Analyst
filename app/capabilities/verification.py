import re
from typing import Any

from app.evidence_extractor import EvidenceExtractionAgent
from app.models import Citation, ESGFact, EvidenceConflict
from app.tools import AgentTools


class EvidenceVerificationAgent:
    """Năng lực Thẩm định Bằng chứng & Kiểm chứng Khẳng định (Evidence Verification).

    Nhiệm vụ:
    1. Kiểm tra tính hợp lệ hình thức của citation (page >= 1, min words, deduplication).
    2. Thẩm định độc lập các khẳng định (Claim Verification) xem có mâu thuẫn hay không.
    3. Xác nhận tính đầy đủ nguồn gốc (Provenance Validation).
    """

    @staticmethod
    def validate(citations: list[Citation]) -> list[Citation]:
        """Lọc và đánh dấu `validated = True` cho các citation đủ tiêu chuẩn hình thức."""
        valid: list[Citation] = []
        seen: set[tuple[str, int, str]] = set()
        for citation in citations:
            normalized = re.sub(r"\W+", " ", citation.excerpt.lower()).strip()
            signature = (citation.document_id, citation.page, normalized[:160])
            if citation.page < 1 or len(normalized.split()) < 3 or signature in seen:
                continue
            seen.add(signature)
            citation.validated = True
            citation.validation_status = "valid"
            valid.append(citation)
        return valid

    @staticmethod
    def audit_claims(claims: list[str], citations: list[Citation]) -> dict[str, Any]:
        """Đối soát danh sách nhận định với nội dung bằng chứng thực tế."""
        combined_text = " ".join(c.excerpt for c in citations)
        audits = []
        supported_count = 0
        for claim in claims:
            res = AgentTools.verify_claim(claim, combined_text)
            audits.append({"claim": claim, **res})
            if res["supported"]:
                supported_count += 1

        total = max(1, len(claims))
        return {
            "audits": audits,
            "supported_rate": round(supported_count / total, 4),
            "total_claims": len(claims),
            "unsupported_claims": [a["claim"] for a in audits if not a["supported"]],
        }

    @staticmethod
    def detect_conflicts(facts: list[ESGFact]) -> list[EvidenceConflict]:
        """Phát hiện mâu thuẫn số liệu công bố giữa các trang hoặc tài liệu."""
        return EvidenceExtractionAgent.detect_conflicts(facts)


EvidenceValidator = EvidenceVerificationAgent
