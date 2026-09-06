from typing import Any, Literal

from app.models import (
    Citation,
    ESGFact,
    EvidenceCompletenessResult,
    EvidenceRequirement,
    EvidenceRequirementResult,
)
from app.rubric import BASELINE_PATTERN, METRIC_PATTERN, YEAR_PATTERN

DEFAULT_REQUIREMENTS: dict[str, EvidenceRequirement] = {
    "scope_1": EvidenceRequirement(
        name="scope_1",
        fact_types=["scope_1_emissions"],
        keywords=["scope 1", "scope1", "direct greenhouse gas"],
        requires_numeric_value=True,
        requires_year=True,
    ),
    "scope_2": EvidenceRequirement(
        name="scope_2",
        fact_types=["scope_2_emissions"],
        keywords=["scope 2", "scope2", "indirect greenhouse gas"],
        requires_numeric_value=True,
        requires_year=True,
    ),
    "scope_3": EvidenceRequirement(
        name="scope_3",
        fact_types=["scope_3_emissions"],
        keywords=["scope 3", "scope3", "value chain emissions"],
        requires_numeric_value=True,
    ),
    "scope_1_2": EvidenceRequirement(
        name="scope_1_2",
        fact_types=["scope_1_emissions", "scope_2_emissions"],
        keywords=["scope 1", "scope 2", "scope1", "scope2"],
        requires_numeric_value=True,
    ),
    "yearly_metrics": EvidenceRequirement(
        name="yearly_metrics",
        fact_types=["scope_1_emissions", "scope_2_emissions", "scope_3_emissions"],
        keywords=["emissions", "tco2e", "202"],
        requires_year=True,
    ),
    "targets": EvidenceRequirement(
        name="targets",
        fact_types=["net_zero_target"],
        keywords=["net zero", "net-zero", "target", "goal"],
    ),
    "target": EvidenceRequirement(
        name="target",
        fact_types=["net_zero_target"],
        keywords=["net zero", "net-zero", "target", "goal"],
    ),
    "net_zero_target": EvidenceRequirement(
        name="net_zero_target",
        fact_types=["net_zero_target"],
        keywords=["net zero", "net-zero", "target", "carbon neutral"],
    ),
    "baseline": EvidenceRequirement(
        name="baseline",
        fact_types=["scope_1_emissions", "scope_2_emissions", "net_zero_target"],
        keywords=["baseline", "base year", "baseline_year"],
        requires_baseline=True,
    ),
    "assurance": EvidenceRequirement(
        name="assurance",
        fact_types=[],
        keywords=["assurance", "assured", "independent auditor", "external assurance", "verified"],
    ),
    "safety": EvidenceRequirement(
        name="safety",
        fact_types=["work_safety"],
        keywords=["safety", "trir", "injury", "fatalit", "workforce"],
        requires_numeric_value=True,
    ),
    "governance": EvidenceRequirement(
        name="governance",
        fact_types=[],
        keywords=["board", "ethics", "compliance", "governance", "oversight"],
    ),
    "progress": EvidenceRequirement(
        name="progress",
        fact_types=[],
        keywords=["reduction", "progress", "decrease", "trajectory", "reduced", "%"],
    ),
    "emissions": EvidenceRequirement(
        name="emissions",
        fact_types=["scope_1_emissions", "scope_2_emissions", "scope_3_emissions"],
        keywords=["emission", "tco2e", "greenhouse"],
    ),
    "metrics": EvidenceRequirement(
        name="metrics",
        fact_types=["scope_1_emissions", "scope_2_emissions", "renewable_energy", "work_safety"],
        keywords=["scope_1_emissions", "scope_2_emissions", "tco2e", "mwh", "trir", "%"],
    ),
}


class EvidenceCompletenessGate:
    """Cổng thẩm định chất lượng và tính đầy đủ của bằng chứng (Quality Gate).

    Không chỉ dừng lại ở việc so khớp từ khóa đơn thuần (token matching),
    cổng này xác thực có cấu trúc:
    - Có số liệu định lượng (numeric value) hay không nếu yêu cầu.
    - Có năm báo cáo (reporting year) rõ ràng hay không.
    - Có năm cơ sở (baseline year) hay không đối với các chỉ tiêu đối sánh.
    """

    def __init__(self, requirements: dict[str, EvidenceRequirement] | None = None):
        self.requirements = requirements or DEFAULT_REQUIREMENTS

    def evaluate_requirement(
        self,
        req: str | EvidenceRequirement,
        facts: list[ESGFact],
        citations: list[Citation],
    ) -> EvidenceRequirementResult:
        if isinstance(req, EvidenceRequirement):
            spec = req
            req_name = spec.name
        else:
            req_name = str(req)
            req_key = req_name.lower().strip()
            spec = self.requirements.get(
                req_key,
                EvidenceRequirement(
                    name=req_name,
                    fact_types=[req_key],
                    keywords=[req_key, req_key.replace("_", " ")],
                ),
            )

        matched_fact_ids: list[str] = []
        matched_citation_ids: list[str] = []
        missing_aspects: list[str] = []

        has_numeric = False
        has_unit = False
        has_year = False
        has_baseline = False

        # 1. Kiểm tra đối chiếu với danh mục Facts
        for idx, f in enumerate(facts):
            fact_id = f.fact_id or f"fact_{idx}_{f.metric}"
            metric_l = f.metric.lower()

            fact_type_matched = any(
                ft.lower() in metric_l or metric_l in ft.lower() for ft in spec.fact_types
            )
            keyword_matched = any(kw.lower() in metric_l for kw in spec.keywords)

            if fact_type_matched or keyword_matched:
                matched_fact_ids.append(fact_id)
                if f.value is not None:
                    has_numeric = True
                if f.unit:
                    has_unit = True
                if f.year is not None:
                    has_year = True
                fact_text = getattr(f, "evidence_text", None) or (f.source.excerpt if f.source else "")
                if f.baseline_year is not None or BASELINE_PATTERN.search(fact_text.lower()):
                    has_baseline = True

        # 2. Kiểm tra đối chiếu với danh mục Citations
        citation_keyword_hit = False
        for c in citations:
            text = c.excerpt.lower()
            if any(kw.lower() in text for kw in spec.keywords):
                citation_keyword_hit = True
                matched_citation_ids.append(f"cite_p{c.page}_{c.chunk_id or 0}")
                if METRIC_PATTERN.search(text):
                    has_numeric = True
                if YEAR_PATTERN.search(text):
                    has_year = True
                if BASELINE_PATTERN.search(text):
                    has_baseline = True

        if spec.requires_numeric_value and not has_numeric:
            missing_aspects.append("numeric_value")
        if getattr(spec, "requires_unit", False) and not has_unit:
            missing_aspects.append("unit")
        if spec.requires_year and not has_year:
            missing_aspects.append("year")
        if spec.requires_baseline and not has_baseline:
            missing_aspects.append("baseline")

        # Xác định trạng thái đáp ứng
        if matched_fact_ids:
            if not missing_aspects:
                return EvidenceRequirementResult(
                    requirement=req_name,
                    status="satisfied",
                    matched_fact_ids=matched_fact_ids,
                    matched_citation_ids=matched_citation_ids,
                    confidence=0.95,
                )
            else:
                return EvidenceRequirementResult(
                    requirement=req_name,
                    status="partial",
                    matched_fact_ids=matched_fact_ids,
                    matched_citation_ids=matched_citation_ids,
                    confidence=0.70,
                    missing_aspects=missing_aspects,
                )

        if citation_keyword_hit:
            if not missing_aspects:
                return EvidenceRequirementResult(
                    requirement=req_name,
                    status="satisfied",
                    matched_fact_ids=[],
                    matched_citation_ids=matched_citation_ids,
                    confidence=0.85,
                )
            else:
                return EvidenceRequirementResult(
                    requirement=req_name,
                    status="partial",
                    matched_fact_ids=[],
                    matched_citation_ids=matched_citation_ids,
                    confidence=0.60,
                    missing_aspects=missing_aspects,
                )

        return EvidenceRequirementResult(
            requirement=req_name,
            status="missing",
            confidence=0.0,
            missing_aspects=["not_found_in_evidence"],
        )

    def check(
        self,
        required_evidence: list[str] | list[EvidenceRequirement],
        facts: list[ESGFact],
        citations: list[Citation],
    ) -> EvidenceCompletenessResult:
        """Thực thi kiểm tra toàn diện danh mục yêu cầu bằng chứng."""
        results: list[EvidenceRequirementResult] = []
        satisfied: list[str] = []
        partial: list[str] = []
        missing: list[str] = []
        req_names: list[str] = []

        for req in required_evidence:
            req_name = req.name if isinstance(req, EvidenceRequirement) else str(req)
            req_names.append(req_name)
            res = self.evaluate_requirement(req, facts, citations)
            results.append(res)
            if res.status == "satisfied":
                satisfied.append(req_name)
            elif res.status == "partial":
                partial.append(req_name)
            else:
                missing.append(req_name)

        status: Literal["complete", "incomplete"] = (
            "complete" if not missing and not partial else "incomplete"
        )
        total = len(req_names)
        score = round(len(satisfied) / total, 2) if total > 0 else 1.0

        return EvidenceCompletenessResult(
            requirements=results,
            satisfied_count=len(satisfied),
            partial_count=len(partial),
            missing_count=len(missing),
            completeness_score=score,
            status=status,
            required=req_names,
            satisfied=satisfied,
            partial=partial,
            missing=missing,
            results=[r.model_dump() for r in results],
        )

    def is_satisfied(
        self, req_name: str, facts: list[ESGFact], citations: list[Citation]
    ) -> bool:
        """Kiểm tra nhanh tính thỏa mãn (hỗ trợ tương thích ngược)."""
        res = self.evaluate_requirement(req_name, facts, citations)
        return res.status in ("satisfied", "partial")
