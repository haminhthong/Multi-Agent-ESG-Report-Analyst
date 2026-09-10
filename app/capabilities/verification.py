"""Evidence validation and claim-support checks.

This capability validates citation metadata/excerpts and performs lightweight
claim-to-evidence matching. It must not be described as independent factual
verification of the issuer's ESG disclosure.
"""

from __future__ import annotations

import re
from typing import Any

from app.extraction.extractor import FactExtractor
from app.models import Citation, ESGFact, EvidenceConflict
from app.tools import AgentTools


class CitationVerifier:
    """Kiểm tra citation trước khi chuyển sang phân tích downstream."""

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
                # Legacy document/page references remain readable, but an
                # unreferenced factual sentence is never considered grounded.
                cids = cls._legacy_source_refs(claim_text, citations)
                if not cids:
                    all_grounded = False
                    claim_results.append(
                        {
                            "claim": claim_text,
                            "cids": [],
                            "grounded": False,
                            "reason": "missing_evidence_ids",
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
    def _legacy_source_refs(claim: str, citations: list[Citation]) -> list[int]:
        """Resolve old ``[Document, page N]`` references to citation positions."""
        page_numbers = [
            int(match.group(1))
            for match in re.finditer(r"(?:trang|page)\s*(\d+)", claim, re.IGNORECASE)
        ]
        if not page_numbers:
            return []
        document_hint = claim.split(",", 1)[0].strip(" []")
        refs: list[int] = []
        for page in page_numbers:
            for index, citation in enumerate(citations, start=1):
                same_page = citation.page == page
                same_document = (
                    not document_hint
                    or document_hint.lower() in citation.document_name.lower()
                    or citation.document_name.lower() in document_hint.lower()
                )
                if same_page and same_document:
                    refs.append(index)
                    break
        return refs

    @staticmethod
    def detect_conflicts(facts: list[ESGFact]) -> list[EvidenceConflict]:
        return FactExtractor.detect_conflicts(facts)


class AnswerValidator:
    """Kiểm tra grounding và citation của câu trả lời cuối."""

    @staticmethod
    def review(answer: str, citations: list[Citation]) -> dict[str, Any]:
        """Check references after all answer augmentations have been applied."""
        if not citations:
            is_abstention = any(
                phrase in answer.lower()
                for phrase in ("no validated evidence", "does not make an esg conclusion")
            )
            return {
                "passed": is_abstention,
                "issues": [] if is_abstention else ["missing_evidence_ids"],
                "citations": 0,
            }

        # Import lazily to avoid the llm -> capabilities dependency cycle.
        from app.llm import validate_answer_grounding

        payload = []
        for index, citation in enumerate(citations[:6], start=1):
            payload.append(
                {
                    "cid": f"[C{index}]",
                    "page": citation.page,
                    "excerpt": citation.excerpt,
                    "document_name": citation.document_name,
                }
            )
        passed, issues = validate_answer_grounding(
            answer,
            payload,
            # Derived rubric percentages are valid workflow outputs even when
            # the exact percentage is not printed in a source excerpt.
            check_numbers=False,
        )
        return {"passed": passed, "issues": issues, "citations": len(citations)}


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
