from typing import Any

from app.domain.rubric_evaluator import EvidenceMatrixBuilder, RubricEvaluator
from app.evidence_extractor import EvidenceExtractionAgent
from app.models import Citation, CompanyComparisonCriterion, CompanyComparisonResult
from app.rubric import CRITERIA_DEFINITIONS, RubricCriterion
from app.store import Store


class CompanyComparisonService:
    """Dịch vụ so sánh chất lượng công bố ESG giữa các doanh nghiệp theo cùng rubric."""

    def __init__(
        self,
        rubric_evaluator: RubricEvaluator | None = None,
        evidence_matrix_builder: EvidenceMatrixBuilder | None = None,
    ):
        self.rubric_evaluator = rubric_evaluator or RubricEvaluator()
        self.evidence_matrix_builder = evidence_matrix_builder or EvidenceMatrixBuilder(
            self.rubric_evaluator
        )

    def run_comparison(
        self,
        companies: list[str],
        store: Store,
        criteria_ids: list[str] | None = None,
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> CompanyComparisonResult:
        defs = criteria_definitions or CRITERIA_DEFINITIONS
        target_criteria = [c for c in defs if not criteria_ids or c.id in criteria_ids]
        comp_rows: list[CompanyComparisonCriterion] = []
        coverage_summary: dict[str, float] = {}

        for company in companies:
            results = store.search(f"{company} ESG sustainability report", limit=12)
            cites = [
                Citation(
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    document_name=r["name"],
                    page=r["page"],
                    excerpt=r["text"],
                )
                for r in results
            ]
            facts = EvidenceExtractionAgent.extract_facts(cites)
            matrix = self.evidence_matrix_builder.build_evidence_matrix(cites, facts, defs)
            found_count = sum(1 for m in matrix if m.status == "found")
            cov = round((found_count / max(1, len(matrix))) * 100, 1)
            coverage_summary[company] = cov

        for crit in target_criteria:
            row_dict: dict[str, Any] = {}
            for company in companies:
                results = store.search(f"{company} {crit.name}", limit=4)
                cites = [
                    Citation(
                        chunk_id=r["chunk_id"],
                        document_id=r["document_id"],
                        document_name=r["name"],
                        page=r["page"],
                        excerpt=r["text"],
                    )
                    for r in results
                ]
                eval_res = self.rubric_evaluator.evaluate_criterion(crit, cites)
                row_dict[company] = {
                    "status": eval_res.status,
                    "value": eval_res.value,
                    "page": eval_res.citation.page if eval_res.citation else None,
                    "confidence": eval_res.confidence,
                }

            comp_rows.append(
                CompanyComparisonCriterion(
                    criterion_id=crit.id,
                    criterion_name=crit.name,
                    pillar=crit.pillar,
                    values_by_company=row_dict,
                )
            )

        findings = [
            f"So sánh {len(companies)} doanh nghiệp: "
            + ", ".join(f"{c}: {cov}% coverage" for c, cov in coverage_summary.items())
        ]
        return CompanyComparisonResult(
            companies=companies,
            criteria_matrix=comp_rows,
            coverage_summary=coverage_summary,
            findings=findings,
        )
