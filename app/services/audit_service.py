"""Compatibility layer re-exporting ESGAnalysisService as ESGAuditService."""

from app.services.esg_analysis_service import (
    ESGAnalysisAgent,
    ESGAnalysisService,
    ESGAuditAgent,
    ESGAuditService,
)

__all__ = [
    "ESGAnalysisAgent",
    "ESGAnalysisService",
    "ESGAuditAgent",
    "ESGAuditService",
]
