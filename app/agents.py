"""Compatibility re-export layer for legacy callers.

All core capabilities, domain models, services, and workflows have been modularized:
- Capabilities: app.capabilities (planning, retrieval, verification, explanation)
- Document Intelligence: app.document_intelligence
- Domain: app.domain (rubric_evaluator, screening, evidence_completeness, temporal_analysis, company_comparison)
- Services: app.services.audit_service
- Workflow: app.workflow
"""

from app.agent_runtime import AgentGraphSupervisor, AgentNode
from app.capabilities.explanation import ExplanationAgent
from app.capabilities.planning import QueryPlanningAgent
from app.capabilities.retrieval import RetrievalAgent
from app.capabilities.verification import (
    AnswerReviewAgent,
    EvidenceValidator,
    EvidenceVerificationAgent,
)
from app.document_intelligence import DocumentAgent, DocumentIntelligenceAgent
from app.domain.evidence_completeness import EvidenceCompletenessGate
from app.evidence_extractor import EvidenceExtractionAgent
from app.services.audit_service import ESGAuditService
from app.workflow import AnalysisWorkflow, SupervisorAgent

# Backward compatibility aliases
ESGAuditAgent = ESGAuditService
ESGAnalysisAgent = ESGAuditService


def _requirement_satisfied(req: str, facts: list, citations: list) -> bool:
    """Helper tương thích ngược cho việc kiểm tra yêu cầu bằng chứng."""
    return EvidenceCompletenessGate().is_satisfied(req, facts, citations)


__all__ = [
    "AgentGraphSupervisor",
    "AgentNode",
    "AnalysisWorkflow",
    "AnswerReviewAgent",
    "DocumentAgent",
    "DocumentIntelligenceAgent",
    "ESGAnalysisAgent",
    "ESGAuditAgent",
    "ESGAuditService",
    "EvidenceExtractionAgent",
    "EvidenceValidator",
    "EvidenceVerificationAgent",
    "ExplanationAgent",
    "QueryPlanningAgent",
    "RetrievalAgent",
    "SupervisorAgent",
]
