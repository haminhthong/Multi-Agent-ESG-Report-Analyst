"""Bounded capabilities used by the application workflow.

The package keeps orchestration-independent responsibilities small and testable.
Legacy classes in :mod:`app.agents` remain temporarily for backward compatibility.
"""

from app.capabilities.explanation import ExplanationAgent
from app.capabilities.planning import QueryPlanningAgent
from app.capabilities.retrieval import RetrievalAgent
from app.capabilities.verification import EvidenceValidator, EvidenceVerificationAgent

__all__ = [
    "EvidenceValidator",
    "EvidenceVerificationAgent",
    "ExplanationAgent",
    "QueryPlanningAgent",
    "RetrievalAgent",
]
