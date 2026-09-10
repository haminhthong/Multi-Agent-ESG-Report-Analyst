"""Pipeline tuần tự cho phân tích ESG có bằng chứng."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Literal

from app.capabilities import (
    AnswerGenerator,
    AnswerValidator,
    CitationVerifier,
    EvidenceRetriever,
    build_retrieval_plan,
)
from app.config import settings
from app.domain.evidence_completeness import EvidenceCompletenessGate
from app.extraction.extractor import FactExtractor
from app.llm import LLMClient
from app.models import (
    AnalysisResponse,
    AnalysisState,
    Citation,
    CriterionEvidenceBundle,
    ESGFact,
    PillarResult,
    RetrievalPlan,
)
from app.services.esg_analysis_service import ESGAnalysisService
from app.store import Store

AUDIT_SUBQUERIES = [
    "Scope 1 Scope 2 direct indirect greenhouse gas emissions tCO2e",
    "Scope 3 value chain supply chain indirect emissions",
    "net zero reduction target goal baseline year 2030 2050",
    "renewable electricity wind solar capacity MWh GWh",
    "worker safety TRIR total recordable incident rate fatalities",
    "female women gender diversity workforce representation",
    "supplier social environmental assessment evaluation",
    "board climate oversight ethics compliance external assurance independent auditor",
]

_EVIDENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "scope_1_2": ("scope_1_emissions", "scope_2_emissions", "scope 1", "scope 2"),
    "scope_1": ("scope_1_emissions", "scope 1", "scope1"),
    "scope_2": ("scope_2_emissions", "scope 2", "scope2"),
    "scope_3": ("scope_3_emissions", "scope 3", "scope3"),
    "target": ("net zero", "net-zero", "target", "reduction goal"),
    "targets": ("net zero", "net-zero", "target", "reduction goal"),
    "net_zero_target": ("net zero", "net-zero", "target", "carbon neutral"),
    "baseline": ("baseline", "base year", "baseline year"),
    "progress": ("reduction", "progress", "historical", "trajectory"),
    "assurance": ("assurance", "assured", "independent auditor", "verified"),
    "emissions": (
        "scope_1_emissions",
        "scope_2_emissions",
        "scope_3_emissions",
        "emission",
        "tco2e",
    ),
    "metrics": ("scope_1_emissions", "scope_2_emissions", "tco2e", "mwh", "trir", "%"),
    "safety": ("work_safety", "trir", "injury", "safety", "fatalit"),
    "governance": ("board", "ethics", "compliance", "governance", "oversight"),
}


class ESGPipeline:
    """Đường chạy chung cho API, CLI và evaluation adapters."""

    def __init__(
        self,
        store: Store,
        llm_client: LLMClient | None = None,
        retrieval_mode: str | None = None,
        audit_service: ESGAnalysisService | None = None,
    ) -> None:
        self.store = store
        self.llm = llm_client or LLMClient()
        self.retrieval = EvidenceRetriever(store, mode=retrieval_mode)
        self.verifier = CitationVerifier()
        self.answer_validator = AnswerValidator()
        self.extractor = FactExtractor()
        self.audit = audit_service or ESGAnalysisService(llm_client=self.llm)
        self.answer_generator = AnswerGenerator(llm_client=self.llm)
        self.completeness_gate = EvidenceCompletenessGate()
        self.retrieval_mode = retrieval_mode or settings.retrieval_mode
        self.last_response: AnalysisResponse | None = None

    def run(
        self,
        question: str,
        top_k: int = 5,
        document_ids: list[str] | None = None,
        mode: Literal["qa", "audit"] = "qa",
        focus_pillars: list[Literal["E", "S", "G"]] | None = None,
    ) -> AnalysisResponse:
        state = AnalysisState(
            request_id=str(uuid.uuid4()),
            user_question=question,
            mode=mode,
            document_ids=document_ids,
            top_k=top_k,
        )
        state.trace.append(
            f"pipeline.start request_id={state.request_id} mode={mode} retrieval={self.retrieval_mode}"
        )

        # Luồng chính cố định giúp dễ kiểm thử và không để LLM điều khiển pipeline.
        self._validate_scope(state)
        self._plan(state)
        self._retrieve(state)
        if state.raw_citations:
            self._verify(state)
        if state.validated_citations:
            self._extract(state)
        self._check_completeness(state)
        self._audit(state, focus_pillars)
        if state.plan and state.plan.intent in {"temporal_trend", "cross_document_compare"}:
            self._run_specialized_analysis(state)
        self._verify_claims(state)
        self._synthesize(state)
        self._review_answer(state)
        self._build_limitations(state)

        evidence_quality, data_completeness, confidence = _aggregate_pillar_metrics(state.pillars)
        response_status = (
            "incomplete"
            if state.evidence_completeness.get("status") == "incomplete"
            else "completed"
        )
        response = AnalysisResponse(
            mode=state.mode,
            request_id=state.request_id,
            status=response_status,
            answer=state.answer,
            disclosure_coverage=state.overall_coverage,
            evidence_quality=evidence_quality,
            data_completeness=data_completeness,
            confidence=confidence,
            screening_signals=(
                state.screening_result.all_signals if state.screening_result else []
            ),
            pillars=state.pillars,
            citations=state.validated_citations,
            verification_summary=state.verification_summary,
            trace=state.trace,
            limitations=state.limitations,
            plan=state.plan,
            evidence_matrix=state.evidence_matrix,
            extracted_facts=state.extracted_facts,
            conflicts=state.conflicts,
            screening_result=state.screening_result,
            temporal_analysis=state.temporal_analysis,
            comparison=state.comparison,
            evidence_completeness=state.evidence_completeness,
            claims=state.claims,
            criterion_bundles=state.criterion_bundles,
        )
        self.last_response = response
        return response

    @staticmethod
    def _merge_citations(
        primary: list[Citation], extra: list[Citation], limit: int
    ) -> list[Citation]:
        merged: list[Citation] = []
        seen: set[tuple[str, int, str]] = set()
        for cite in primary + extra:
            sig = (cite.document_id, cite.page, " ".join(cite.excerpt.split())[:120].lower())
            if sig not in seen:
                seen.add(sig)
                merged.append(cite)
            if len(merged) >= limit:
                break
        return merged

    def _validate_scope(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        if state.document_ids:
            existing = {doc["id"] for doc in self.store.documents()}
            unknown = [doc_id for doc_id in state.document_ids if doc_id not in existing]
            if unknown:
                state.warnings.append("Unknown document ids: " + ", ".join(unknown))
                state.document_ids = [doc_id for doc_id in state.document_ids if doc_id in existing]
        self._trace(
            state,
            "Pipeline",
            "Validate request and document scope",
            started,
            details={"document_scope": state.document_ids or [], "warnings": state.warnings},
        )

    def _plan(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.plan = build_retrieval_plan(
            state.user_question,
            mode=state.mode,
            document_ids=state.document_ids,
        )
        state.plan.original_question = state.user_question
        state.plan.canonical_query = state.user_question
        self._trace(
            state,
            "Planner",
            "Build retrieval plan",
            started,
            details={
                "intent": state.plan.intent,
                "subqueries": len(state.plan.subqueries),
                "required_evidence": state.plan.required_evidence,
            },
        )

    def _retrieve(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        if state.mode == "audit":
            from app.rubric import CRITERIA_DEFINITIONS

            # Criterion-level audit retrieval: đảm bảo mọi tiêu chí chuẩn mực đều được truy xuất bằng chứng chuyên biệt
            criterion_cites: list[Citation] = []
            state.criterion_bundles = []
            for crit in CRITERIA_DEFINITIONS:
                crit_query = f"{crit.name} {' '.join(crit.retrieval_keywords[:3])}"
                sub_cites = self.retrieval.run(crit_query, top_k=3, document_ids=state.document_ids)
                criterion_cites.extend(sub_cites)
                state.criterion_bundles.append(
                    CriterionEvidenceBundle(
                        criterion_id=crit.id,
                        query=crit_query,
                        citation_ids=[_citation_key(cite) for cite in sub_cites],
                        completeness_status="complete" if sub_cites else "missing",
                    )
                )

            plan = RetrievalPlan(
                intent="criterion_audit",
                original_question=state.user_question,
                canonical_query=state.user_question,
                subqueries=AUDIT_SUBQUERIES,
                required_evidence=state.plan.required_evidence,
                document_scope=state.document_ids,
                criteria=[criterion.id for criterion in CRITERIA_DEFINITIONS],
                metrics=state.plan.metrics,
                reporting_years=state.plan.reporting_years,
                requires_numeric=state.plan.requires_numeric,
            )
            core_cites = self.retrieval.run_plan(plan, top_k=max(state.top_k, 12))
            state.raw_citations = self._merge_citations(
                core_cites, criterion_cites, limit=max(state.top_k * 4, 30)
            )
        else:
            state.raw_citations = self.retrieval.run_plan(state.plan, top_k=state.top_k)
        self._trace(
            state,
            "Evidence",
            "Retrieve hybrid evidence candidates (criterion-level audit)"
            if state.mode == "audit"
            else "Retrieve hybrid evidence candidates",
            started,
            retrieved_chunks=len(state.raw_citations),
            details={"mode": self.retrieval_mode, "top_k": len(state.raw_citations)},
        )

    def _verify(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.validated_citations = self.verifier.validate(state.raw_citations)
        self._trace(
            state,
            "Evidence",
            "Validate citation metadata and excerpt shape",
            started,
            retrieved_chunks=len(state.validated_citations),
            details={
                "accepted": len(state.validated_citations),
                "rejected": len(state.raw_citations) - len(state.validated_citations),
                "scope": "retrieved-evidence validation",
            },
        )

    def _extract(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.extracted_facts = self.extractor.extract_facts(state.validated_citations)
        state.conflicts = self.extractor.detect_conflicts(state.extracted_facts)
        _attach_facts_to_criterion_bundles(state)

        self._trace(
            state,
            "Evidence",
            "Extract structured ESG facts and detect conflicts",
            started,
            retrieved_chunks=len(state.extracted_facts),
            details={"facts": len(state.extracted_facts), "conflicts": len(state.conflicts)},
        )

    def _targeted_retrieval_retry(self, state: AnalysisState) -> None:
        """Kích hoạt targeted retrieval retry cho các khía cạnh bằng chứng còn thiếu."""
        if not state.evidence_completeness:
            return

        missing_reqs = list(state.evidence_completeness.missing) + list(
            state.evidence_completeness.partial
        )
        if not missing_reqs:
            return

        retry_queries: list[str] = []
        for req in missing_reqs[:3]:
            aliases = _EVIDENCE_ALIASES.get(req, (req.replace("_", " "),))
            retry_queries.append(" ".join(aliases[:3]))

        if not retry_queries:
            return

        started = time.perf_counter()
        retry_plan = RetrievalPlan(
            intent=state.plan.intent if state.plan else "fact_lookup",
            original_question=state.user_question,
            canonical_query=" ".join(retry_queries),
            subqueries=retry_queries,
            document_scope=state.document_ids,
        )
        retry_citations = self.retrieval.run_plan(retry_plan, top_k=4)
        validated_retry = self.verifier.validate(retry_citations)

        new_cites = [
            c
            for c in validated_retry
            if not any(
                c.document_id == ex.document_id
                and c.page == ex.page
                and c.excerpt[:80] == ex.excerpt[:80]
                for ex in state.validated_citations
            )
        ]
        if new_cites:
            state.validated_citations.extend(new_cites)
            new_facts = self.extractor.extract_facts(new_cites)
            if new_facts:
                state.extracted_facts.extend(new_facts)
                state.conflicts = self.extractor.detect_conflicts(state.extracted_facts)

            # Thẩm định lại completeness sau khi thu hồi thêm bằng chứng
            state.evidence_completeness = self.completeness_gate.check(
                state.plan.required_evidence if state.plan else [],
                state.extracted_facts,
                state.validated_citations,
            )

        self._trace(
            state,
            "EvidenceCompletenessGate",
            "Targeted retrieval retry for missing evidence",
            started,
            retrieved_chunks=len(new_cites),
            details={
                "missing_targeted": missing_reqs,
                "new_citations": len(new_cites),
                "recheck_status": state.evidence_completeness.status,
            },
        )

    def _check_completeness(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        state.evidence_completeness = self.completeness_gate.check(
            state.plan.required_evidence,
            state.extracted_facts,
            state.validated_citations,
        )

        # Active Completeness Gate: Tự động chạy targeted retry nếu thiếu bằng chứng
        if state.evidence_completeness.status == "incomplete" and (
            state.evidence_completeness.missing or state.evidence_completeness.partial
        ):
            self._targeted_retrieval_retry(state)

        self._trace(
            state,
            "EvidenceCompletenessGate",
            "Check required evidence",
            started,
            details=state.evidence_completeness.model_dump()
            if hasattr(state.evidence_completeness, "model_dump")
            else state.evidence_completeness,
        )

    def _audit(
        self,
        state: AnalysisState,
        focus_pillars: list[Literal["E", "S", "G"]] | None,
    ) -> None:
        started = time.perf_counter()
        pillars, overall_coverage, _ = self.audit.run(
            state.validated_citations,
            facts=state.extracted_facts,
            run_screening=state.mode == "audit",
        )
        matrix = self.audit.build_scoped_evidence_matrix(
            state.validated_citations, state.extracted_facts, state.criterion_bundles
        )
        screening = (
            self.audit.screen_greenwashing_signals(state.validated_citations, state.extracted_facts)
            if state.mode == "audit"
            else None
        )

        if focus_pillars:
            selected = set(focus_pillars)
            pillars = [pillar for pillar in pillars if pillar.pillar in selected]
            matrix = [row for row in matrix if row.pillar in selected]
            overall_coverage = (
                round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1)
                if pillars
                else 0.0
            )

        state.pillars = pillars
        state.evidence_matrix = matrix
        state.screening_result = screening
        state.overall_coverage = overall_coverage
        self._trace(
            state,
            "Analysis",
            "Evaluate rubric and screen greenwashing risk",
            started,
            retrieved_chunks=len(matrix),
            details={
                "coverage": overall_coverage,
                "risk_level": screening.risk_level if screening else "UNKNOWN",
                "evidence_matrix_rows": len(matrix),
            },
        )

    def _run_specialized_analysis(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        details: dict[str, Any] = {"executed": False, "analysis": state.plan.intent}

        if state.plan.intent == "temporal_trend":
            company = self._resolve_primary_company(state)
            state.temporal_analysis = self.audit.run_temporal_analysis(
                company,
                self.store,
                metric=(state.plan.metrics[0] if state.plan.metrics else "scope_1_emissions"),
                document_ids=state.document_ids,
            )
            details.update({"executed": True, "company": company, "analysis": "temporal"})
        elif state.plan.intent == "cross_document_compare":
            companies = self._resolve_companies(state.user_question, state.document_ids)
            if len(companies) >= 2:
                state.comparison = self.audit.run_comparison(
                    companies,
                    self.store,
                    criteria_ids=state.plan.criteria,
                )
                details.update({"executed": True, "companies": companies, "analysis": "comparison"})
            else:
                state.warnings.append(
                    "Comparison intent detected but fewer than two companies could be resolved."
                )

        self._trace(
            state,
            "Analysis",
            "Run intent-specific analysis when required",
            started,
            details=details,
        )

    def _verify_claims(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        claims = _build_audit_claims(state.extracted_facts, state.pillars)
        state.claims = [
            {
                "text": claim,
                "evidence_ids": [
                    _citation_key(cite)
                    for cite in state.validated_citations
                    if _claim_overlaps_citation(claim, cite)
                ],
            }
            for claim in claims
        ]
        state.verification_summary = self.verifier.audit_claims(
            claims,
            state.validated_citations,
        )
        audits = {
            item.get("claim"): item
            for item in state.verification_summary.get("audits", [])
            if isinstance(item, dict)
        }
        for claim in state.claims:
            audit = audits.get(claim.get("text"), {})
            claim["supported"] = bool(audit.get("supported", False))
            claim["support_score"] = audit.get("keyword_overlap", 0.0)
        self._trace(
            state,
            "Answer",
            "Check extracted claim support in retrieved excerpts",
            started,
            details={
                "claims": len(claims),
                "supported_rate": state.verification_summary.get("supported_rate", 0.0),
            },
        )

    def _synthesize(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.answer = self.answer_generator.run(
            state.mode,
            state.pillars,
            state.overall_coverage,
            state.validated_citations,
            state.user_question,
            screening_result=state.screening_result,
        )
        self._trace(
            state,
            "Answer",
            "Synthesize evidence-grounded response",
            started,
            details={
                "citations_available": len(state.validated_citations),
                "llm_available": self.llm.is_available(),
            },
        )

    def _review_answer(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        review = self.answer_validator.review(state.answer, state.validated_citations)
        if not review["passed"]:
            state.warnings.append(
                "[ANSWER_REVIEW] Answer was regenerated because it was not fully grounded: "
                + ", ".join(review["issues"])
            )
            state.answer = self.answer_generator._deterministic_answer(
                state.mode,
                state.pillars,
                state.overall_coverage,
                state.validated_citations,
                state.user_question,
                state.screening_result,
            )
            review = self.answer_validator.review(state.answer, state.validated_citations)
            if not review["passed"]:
                state.answer = (
                    "The retrieved evidence was insufficient to produce a fully grounded answer. "
                    "No ESG conclusion is made."
                )
                review = self.answer_validator.review(state.answer, state.validated_citations)

        state.verification_summary["answer_review"] = review
        self._trace(
            state,
            "Answer",
            "Review final answer references and grounding contract",
            started,
            details=review,
        )

    def _build_limitations(self, state: AnalysisState) -> None:
        state.limitations = [
            "Analysis is limited to indexed documents and retrieved evidence chunks.",
            "Citation validation checks metadata and retrieved excerpts; it is not independent third-party verification of the issuer's ESG disclosure.",
            "Greenwashing output is a heuristic screening signal for analyst review, not a legal or fraud determination.",
        ]
        if state.evidence_completeness.get("status") == "incomplete":
            state.limitations.append(
                "[MISSING_EVIDENCE] Missing required evidence: "
                + ", ".join(state.evidence_completeness.get("missing", []))
            )
        if state.mode == "audit":
            state.limitations.append(
                "Disclosure coverage measures evidence presence in the indexed corpus, not corporate ESG performance."
            )
        state.limitations.extend(state.warnings)

    def _resolve_primary_company(self, state: AnalysisState) -> str:
        if state.document_ids:
            for document_id in state.document_ids:
                doc = self.store.get_document(document_id)
                if doc and doc.get("company"):
                    return str(doc["company"])
        for citation in state.validated_citations:
            doc = self.store.get_document(citation.document_id)
            if doc and doc.get("company"):
                return str(doc["company"])
        return "Company"

    def _resolve_companies(
        self,
        question: str,
        document_ids: list[str] | None,
    ) -> list[str]:
        companies: list[str] = []
        seen: set[str] = set()

        def add(name: str | None) -> None:
            if not name:
                return
            clean = name.strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                companies.append(clean)

        if document_ids:
            for document_id in document_ids:
                doc = self.store.get_document(document_id)
                if doc:
                    add(doc.get("company"))

        for doc in self.store.documents():
            company = doc.get("company")
            if company and company.lower() in question.lower():
                add(company)

        match = re.search(
            r"(.+?)\s+(?:vs\.?|versus|so sánh với|đối chiếu với)\s+(.+)",
            question,
            re.IGNORECASE,
        )
        if match:
            for raw in match.groups():
                token = re.sub(
                    r"\b(?:compare|so sánh|đối chiếu|emissions?|esg|report)\b",
                    "",
                    raw,
                    flags=re.IGNORECASE,
                ).strip(" ,.")
                if token and len(token.split()) <= 4:
                    add(token)
        return companies[:10]

    @staticmethod
    def _trace(
        state: AnalysisState,
        stage: str,
        step: str,
        started: float,
        retrieved_chunks: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        suffix = f", chunks={retrieved_chunks}" if retrieved_chunks else ""
        state.trace.append(f"{stage}: {step} ({latency_ms} ms{suffix})")


def _citation_key(citation: Citation) -> str:
    """Trả về định danh evidence ổn định, không dùng numeric chunk id làm provenance."""
    return (
        citation.evidence_id
        or citation.stable_chunk_id
        or (
            f"{citation.document_id}:p{citation.page}:{citation.block_id or citation.chunk_id or 'text'}"
        )
    )


def _attach_facts_to_criterion_bundles(state: AnalysisState) -> None:
    """Gắn fact với bundle đúng phạm vi bằng provenance của citation."""
    for bundle in state.criterion_bundles:
        citation_ids = set(bundle.citation_ids)
        fact_ids = [
            fact.fact_id
            for fact in state.extracted_facts
            if fact.fact_id
            and fact.source is not None
            and _citation_key(fact.source) in citation_ids
        ]
        bundle.fact_ids = list(dict.fromkeys(fact_ids))
        if bundle.citation_ids and fact_ids:
            bundle.completeness_status = "complete"
        elif bundle.citation_ids:
            bundle.completeness_status = "partial"


def _claim_overlaps_citation(claim: str, citation: Citation) -> bool:
    """Xác định claim có liên hệ tối thiểu với excerpt trước khi gắn citation."""
    claim_tokens = {
        token.lower() for token in re.findall(r"[a-zA-ZÀ-ỹ0-9_]+", claim) if len(token) > 3
    }
    excerpt = citation.excerpt.lower()
    return any(token in excerpt for token in claim_tokens)


def _requirement_satisfied(
    requirement: str,
    facts: list[ESGFact],
    citations: list[Citation],
) -> bool:
    requirement = requirement.lower().strip()
    tokens = (requirement, *_EVIDENCE_ALIASES.get(requirement, ()))
    for token in dict.fromkeys(tokens):
        lowered = token.lower()
        for fact in facts:
            metric = fact.metric.lower()
            unit = (fact.unit or "").lower()
            if lowered in metric or metric in lowered or (unit and lowered in unit):
                return True
            if lowered in ("year", "reporting_year") and fact.year is not None:
                return True
            if lowered == "baseline_year" and fact.baseline_year is not None:
                return True
        if any(lowered in citation.excerpt.lower() for citation in citations):
            return True
    return False


def _build_audit_claims(facts: list[ESGFact], pillars: list[PillarResult]) -> list[str]:
    claims: list[str] = []
    for fact in facts:
        if fact.value is None:
            continue
        unit = f" {fact.unit}" if fact.unit else ""
        year = f" in {fact.year}" if fact.year else ""
        claims.append(f"{fact.metric}: {fact.value}{unit}{year}")
        if len(claims) >= 8:
            return claims

    for pillar in pillars:
        for criterion in pillar.criteria_results:
            if criterion.status in ("found", "partial") and criterion.value:
                claims.append(f"{criterion.criterion_id}: {criterion.value}")
            if len(claims) >= 8:
                return claims
    return claims


def _aggregate_pillar_metrics(pillars: list[PillarResult]) -> tuple[float, float, float]:
    if not pillars:
        return 0.0, 0.0, 0.0
    evidence_quality = round(sum(p.evidence_quality for p in pillars) / len(pillars), 1)
    completeness = round(sum(p.data_completeness for p in pillars) / len(pillars), 1)
    confidence = round(sum(p.confidence for p in pillars) / len(pillars), 2)
    return evidence_quality, completeness, confidence
