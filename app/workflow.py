"""Application workflow for ESG analysis.

This module owns orchestration only. Domain capabilities remain in ``app.agents``
and infrastructure remains in ``app.store`` / ``app.document_service``.
Keeping orchestration here makes the request lifecycle explicit, testable, and
independent from the HTTP/CLI adapters.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Literal

from app.agents import (
    ESGAuditAgent,
    EvidenceVerificationAgent,
    ExplanationAgent,
    QueryPlanningAgent,
    RetrievalAgent,
)
from app.config import settings
from app.evidence_extractor import EvidenceExtractionAgent
from app.llm import LLMClient
from app.models import (
    AgentTraceStep,
    AnalysisResponse,
    AnalysisState,
    Citation,
    ESGFact,
    PillarResult,
    RetrievalPlan,
)
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
    "yearly_metrics": ("emissions", "tco2e", "202"),
    "progress": ("reduction", "progress", "decrease", "trajectory", "reduced", "%"),
    "targets": ("net_zero_target", "target", "net zero", "net-zero", "goal"),
    "target": ("net_zero_target", "target", "net zero", "net-zero", "goal"),
    "baseline": ("baseline", "base year", "baseline_year"),
    "assurance": ("assurance", "assured", "independent auditor", "verified"),
    "emissions": ("scope_1_emissions", "scope_2_emissions", "scope_3_emissions", "emission"),
    "metrics": ("scope_1_emissions", "scope_2_emissions", "tco2e", "mwh", "trir", "%"),
    "safety": ("work_safety", "trir", "injury", "safety", "fatalit"),
    "governance": ("board", "ethics", "compliance", "governance", "oversight"),
}


class ESGAnalysisPipeline:
    """Single application-level pipeline used by API, CLI, and evaluation code.

    The workflow is intentionally deterministic at the orchestration layer:

    1. validate request scope
    2. plan retrieval
    3. retrieve candidates
    4. verify citations
    5. extract structured facts and conflicts
    6. check required-evidence completeness
    7. score the ESG rubric and screening heuristics
    8. run optional temporal/comparison analysis
    9. verify extracted claims
    10. synthesize the grounded response

    LLM usage is optional and isolated inside capability implementations. The
    pipeline itself remains observable and reproducible.
    """

    def __init__(
        self,
        store: Store,
        llm_client: LLMClient | None = None,
        retrieval_mode: str | None = None,
    ) -> None:
        self.store = store
        self.llm = llm_client or LLMClient()
        self.planner = QueryPlanningAgent()
        self.retrieval = RetrievalAgent(store, mode=retrieval_mode)
        self.verifier = EvidenceVerificationAgent()
        self.extractor = EvidenceExtractionAgent()
        self.audit = ESGAuditAgent(llm_client=self.llm)
        self.analysis = self.audit  # compatibility with older callers
        self.explanation = ExplanationAgent(llm_client=self.llm)
        self.retrieval_mode = retrieval_mode or settings.retrieval_mode
        self.last_response: AnalysisResponse | None = None

    def run(
        self,
        question: str,
        top_k: int = 6,
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
            f"workflow.start request_id={state.request_id} mode={mode} retrieval={self.retrieval_mode}"
        )

        self._validate_scope(state)
        self._plan(state)
        self._retrieve(state)
        self._verify(state)
        self._extract(state)
        self._check_completeness(state)
        self._audit(state, focus_pillars)
        self._run_specialized_analysis(state)
        self._verify_claims(state)
        self._synthesize(state)
        self._build_limitations(state)

        evidence_quality, data_completeness, confidence = _aggregate_pillar_metrics(state.pillars)
        response = AnalysisResponse(
            mode=state.mode,
            agent_mode="agent_orchestrated",
            answer=state.answer,
            disclosure_coverage=state.overall_coverage,
            evidence_quality=evidence_quality,
            data_completeness=data_completeness,
            confidence=confidence,
            screening_signals=(state.screening_result.all_signals if state.screening_result else []),
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
            trace_steps=state.trace_steps,
        )
        self.last_response = response
        return response

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
            "Workflow",
            "Validate request and document scope",
            started,
            details={"document_scope": state.document_ids or [], "warnings": state.warnings},
        )

    def _plan(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.plan = self.planner.plan(
            state.user_question,
            mode=state.mode,
            document_ids=state.document_ids,
        )
        self._trace(
            state,
            "QueryPlanningAgent",
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
            plan = RetrievalPlan(
                intent="criterion_audit",
                subqueries=AUDIT_SUBQUERIES,
                required_evidence=state.plan.required_evidence,
                document_scope=state.document_ids,
            )
            state.raw_citations = self.retrieval.run_plan(plan, top_k=max(state.top_k, 12))
        else:
            state.raw_citations = self.retrieval.run_plan(state.plan, top_k=state.top_k)
        self._trace(
            state,
            "RetrievalAgent",
            "Retrieve hybrid evidence candidates",
            started,
            retrieved_chunks=len(state.raw_citations),
            details={"mode": self.retrieval_mode, "top_k": state.top_k},
        )

    def _verify(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.validated_citations = self.verifier.validate(state.raw_citations)
        self._trace(
            state,
            "EvidenceVerificationAgent",
            "Validate citation shape and provenance fields",
            started,
            retrieved_chunks=len(state.validated_citations),
            details={
                "accepted": len(state.validated_citations),
                "rejected": len(state.raw_citations) - len(state.validated_citations),
            },
        )

    def _extract(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.extracted_facts = self.extractor.extract_facts(state.validated_citations)
        state.conflicts = self.extractor.detect_conflicts(state.extracted_facts)
        self._trace(
            state,
            "EvidenceExtractionAgent",
            "Extract structured ESG facts and detect conflicts",
            started,
            retrieved_chunks=len(state.extracted_facts),
            details={"facts": len(state.extracted_facts), "conflicts": len(state.conflicts)},
        )

    def _check_completeness(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        satisfied: list[str] = []
        missing: list[str] = []
        for requirement in state.plan.required_evidence:
            target = satisfied if _requirement_satisfied(
                requirement, state.extracted_facts, state.validated_citations
            ) else missing
            target.append(requirement)
        state.evidence_completeness = {
            "required": state.plan.required_evidence,
            "satisfied": satisfied,
            "missing": missing,
            "status": "complete" if not missing else "incomplete",
        }
        self._trace(
            state,
            "EvidenceCompletenessGate",
            "Check required evidence",
            started,
            details=state.evidence_completeness,
        )

    def _audit(
        self,
        state: AnalysisState,
        focus_pillars: list[Literal["E", "S", "G"]] | None,
    ) -> None:
        started = time.perf_counter()
        pillars, overall_coverage, _ = self.audit.run(state.validated_citations)
        matrix = self.audit.build_evidence_matrix(
            state.validated_citations, state.extracted_facts
        )
        screening = self.audit.screen_greenwashing_signals(
            state.validated_citations, state.extracted_facts
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
        state.overall_coverage = overall_coverage
        state.evidence_matrix = matrix
        state.screening_result = screening
        self._trace(
            state,
            "ESGAuditAgent",
            "Evaluate disclosure rubric and screening heuristics",
            started,
            retrieved_chunks=len(matrix),
            details={
                "coverage": overall_coverage,
                "risk_level": screening.risk_level,
                "matrix_rows": len(matrix),
                "focus_pillars": focus_pillars or ["E", "S", "G"],
            },
        )

    def _run_specialized_analysis(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        details: dict[str, Any] = {"intent": state.plan.intent, "executed": False}

        if state.plan.intent == "temporal_trend":
            company = self._resolve_primary_company(state)
            state.temporal_analysis = self.audit.run_temporal_analysis(
                company,
                self.store,
                document_ids=state.document_ids,
            )
            details.update({"executed": True, "company": company, "analysis": "temporal"})
        elif state.plan.intent == "cross_document_compare":
            companies = self._resolve_companies(state.user_question, state.document_ids)
            if len(companies) >= 2:
                state.comparison = self.audit.run_comparison(companies, self.store)
                details.update(
                    {"executed": True, "companies": companies, "analysis": "comparison"}
                )
            else:
                state.warnings.append(
                    "Comparison intent detected but fewer than two companies could be resolved."
                )

        self._trace(
            state,
            "SpecializedAnalysis",
            "Run intent-specific analysis when required",
            started,
            details=details,
        )

    def _verify_claims(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        claims = _build_audit_claims(state.extracted_facts, state.pillars)
        state.verification_summary = self.verifier.audit_claims(
            claims, state.validated_citations
        )
        self._trace(
            state,
            "EvidenceVerificationAgent",
            "Verify extracted claims against retrieved evidence",
            started,
            details={
                "claims": len(claims),
                "supported_rate": state.verification_summary.get("supported_rate", 0.0),
            },
        )

    def _synthesize(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.answer = self.explanation.run(
            state.mode,
            state.pillars,
            state.overall_coverage,
            state.validated_citations,
            state.user_question,
            screening_result=state.screening_result,
        )
        if state.comparison:
            state.answer += "\n\nComparison: " + "; ".join(
                f"{company}: {coverage}% disclosure coverage"
                for company, coverage in state.comparison.coverage_summary.items()
            )
        self._trace(
            state,
            "ExplanationAgent",
            "Synthesize evidence-grounded response",
            started,
            details={
                "citations_available": len(state.validated_citations),
                "llm_available": self.llm.is_available(),
            },
        )

    def _build_limitations(self, state: AnalysisState) -> None:
        state.limitations = [
            "The analysis is limited to indexed documents and retrieved evidence chunks.",
            "Citation validation checks source metadata and excerpt shape; it is not independent third-party verification of the underlying ESG disclosure.",
            "Greenwashing output is a heuristic screening signal for analyst review, not a legal or fraud determination.",
        ]
        if state.evidence_completeness.get("status") == "incomplete":
            missing = state.evidence_completeness.get("missing", [])
            state.limitations.append("Missing required evidence: " + ", ".join(missing))
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
        agent: str,
        step: str,
        started: float,
        retrieved_chunks: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        state.trace_steps.append(
            AgentTraceStep(
                agent=agent,
                step=step,
                latency_ms=latency_ms,
                retrieved_chunks=retrieved_chunks,
                details=details or {},
            )
        )
        state.trace.append(f"{agent}: {step} ({latency_ms} ms)")


# Backward-compatible name for code that still thinks in terms of a supervisor.
SupervisorWorkflow = ESGAnalysisPipeline


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
