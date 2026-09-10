"""Bộ điều phối trích xuất fact từ chunk bằng chứng ESG chưa cấu trúc."""

import hashlib
import re

from app.extraction.fact_validator import detect_conflicts
from app.extraction.metric_detector import FACT_PATTERNS
from app.extraction.unit_normalizer import UnitNormalizer
from app.extraction.value_parser import parse_numeric_value
from app.extraction.year_resolver import (
    extract_methodology,
    extract_year_for_span,
    resolve_target_year,
)
from app.models import Citation, ESGFact, EvidenceConflict
from app.rubric import TARGET_PATTERN, YEAR_PATTERN


class FactExtractor:
    """Năng lực Trích xuất Sự thật ESG có Cấu trúc (Structured ESG Fact Extraction).

    Nhiệm vụ:
    1. Quét các đoạn trích dẫn (Citations) được truy xuất để trích xuất số liệu ESG có cấu trúc.
    2. Chuẩn hóa đơn vị đo lường (tCO2e, %, MWh, etc.) và lưu vết song song raw và normalized.
    3. Xác định năm báo cáo cục bộ theo metric span (tránh nhầm năm cơ sở).
    4. Gắn citation nguồn (Provenance) và tính độ tin cậy trích xuất (Confidence Score).
    5. Phát hiện mâu thuẫn số liệu đa chiều (Multidimensional Conflict Detection).
    """

    @classmethod
    def extract_facts(cls, citations: list[Citation]) -> list[ESGFact]:
        """Trích xuất danh sách các đối tượng ESGFact từ tập citation."""
        facts: list[ESGFact] = []

        for cite in citations:
            text = cite.excerpt
            doc_year = cite.document_year
            if doc_year is None:
                year_match = YEAR_PATTERN.search(text)
                doc_year = int(year_match.group(0)) if year_match else None

            # 1. Tìm năm cơ sở toàn văn bản
            baseline_match = re.search(
                r"(?:\b(?:baseline|base year|from)\s*(20[12]\d)\b|\b(20[12]\d)\s*(?:baseline|base year)\b)",
                text,
                re.IGNORECASE,
            )
            global_baseline = (
                int(baseline_match.group(1) or baseline_match.group(2)) if baseline_match else None
            )

            # 2. Quét các mẫu metric định lượng
            for metric_key, pattern in FACT_PATTERNS.items():
                for match in pattern.finditer(text):
                    groups = [g for g in match.groups() if g is not None]
                    raw_val = groups[0] if groups else None
                    raw_unit = groups[1] if len(groups) > 1 else None
                    if not raw_val:
                        continue
                    if metric_key == "supplier_assessment" and not raw_unit:
                        raw_unit = "suppliers"
                    numeric_val = parse_numeric_value(raw_val)

                    # Xác định năm gắn cục bộ với span của metric
                    m_start, m_end = match.span()
                    local_year, baseline_year = extract_year_for_span(
                        text, m_start, m_end, global_baseline=global_baseline
                    )
                    methodology = extract_methodology(text, m_start, m_end)

                    # Chuẩn hóa đơn vị qua UnitNormalizer
                    norm_val, norm_unit = UnitNormalizer.normalize(
                        metric_key, numeric_val, raw_unit
                    )

                    has_unit = bool(raw_unit or norm_unit)
                    has_year = bool(local_year or doc_year)
                    confidence = 0.70 + (0.15 if has_unit else 0.0) + (0.15 if has_year else 0.0)

                    fact = ESGFact(
                        metric=metric_key,
                        value=numeric_val,
                        unit=raw_unit.strip()
                        if raw_unit
                        else ("%" if "target" in metric_key or "diversity" in metric_key else None),
                        year=local_year or doc_year,
                        reporting_year=local_year or doc_year,
                        page=cite.page,
                        chunk_id=_chunk_reference(cite),
                        baseline_year=baseline_year,
                        source=cite,
                        company=cite.company,
                        document_id=cite.document_id,
                        confidence=round(confidence, 2),
                        raw_value=numeric_val,
                        raw_unit=raw_unit.strip() if raw_unit else None,
                        normalized_value=norm_val,
                        normalized_unit=norm_unit,
                        methodology=methodology,
                        evidence_span_id=_evidence_span_id(cite),
                        evidence_text=text,
                    )
                    fact.fact_id = _fact_id(fact)
                    facts.append(fact)

            # 3. Quét thêm cam kết Target / Net-zero nếu chưa được trích xuất
            # P0: Không bao giờ gán mặc định target_year = 2030 khi tài liệu không công bố!
            has_net_zero = bool(
                re.search(
                    r"\b(?:net[ -]?zero|carbon[ -]?neutral|zero\s*emissions)\b",
                    text,
                    re.IGNORECASE,
                )
            )
            if (TARGET_PATTERN.search(text) or has_net_zero) and not any(
                f.metric == "net_zero_target" and f.source == cite for f in facts
            ):
                target_m = TARGET_PATTERN.search(text) or re.search(
                    r"\b(?:net[ -]?zero|carbon[ -]?neutral|zero\s*emissions)\b", text, re.IGNORECASE
                )
                target_span = target_m.span() if target_m else None
                target_year = resolve_target_year(
                    text,
                    target_span=target_span,
                    reporting_year=doc_year,
                    baseline_year=global_baseline,
                )
                fact = ESGFact(
                    metric="net_zero_target",
                    value=target_year if target_year is not None else "disclosed",
                    unit="year" if target_year is not None else "commitment",
                    year=doc_year,
                    reporting_year=doc_year,
                    page=cite.page,
                    chunk_id=_chunk_reference(cite),
                    target_year=target_year,
                    baseline_year=global_baseline,
                    source=cite,
                    company=cite.company,
                    document_id=cite.document_id,
                    confidence=0.88 if global_baseline else 0.75,
                    raw_value=target_year if target_year is not None else "disclosed",
                    raw_unit="year" if target_year is not None else "commitment",
                    normalized_value=float(target_year) if target_year is not None else None,
                    normalized_unit="year" if target_year is not None else "commitment",
                    evidence_span_id=_evidence_span_id(cite),
                    evidence_text=text,
                )
                fact.fact_id = _fact_id(fact)
                facts.append(fact)

        return facts

    @classmethod
    def detect_conflicts(cls, facts: list[ESGFact]) -> list[EvidenceConflict]:
        """Phát hiện mâu thuẫn số liệu công bố đa chiều."""
        return detect_conflicts(facts)


def _evidence_span_id(citation: Citation) -> str:
    """Tạo định danh bằng chứng deterministic cho lineage của fact."""
    if citation.evidence_id:
        return citation.evidence_id
    source_key = citation.stable_chunk_id or citation.block_id or str(citation.chunk_id or "")
    if not source_key:
        source_key = hashlib.sha256(citation.excerpt.encode("utf-8")).hexdigest()[:16]
    return f"{citation.document_id}:p{citation.page}:{source_key}"


def _chunk_reference(citation: Citation) -> str | None:
    """Ưu tiên định danh chunk ổn định để provenance không phụ thuộc thứ tự SQLite."""
    if citation.stable_chunk_id:
        return citation.stable_chunk_id
    if citation.block_id:
        return citation.block_id
    return str(citation.chunk_id) if citation.chunk_id is not None else None


def _fact_id(fact: ESGFact) -> str:
    """Gộp mọi chiều ngữ nghĩa để các công bố khác nhau không ghi đè lên nhau."""
    identity = "|".join(
        [
            str(fact.document_id or ""),
            fact.metric,
            str(fact.reporting_year or ""),
            str(fact.baseline_year or ""),
            str(fact.target_year or ""),
            str(fact.raw_value if fact.raw_value is not None else fact.value),
            str(fact.raw_unit or fact.unit or ""),
            str(fact.normalized_unit or ""),
            str(fact.methodology or ""),
            str(fact.organizational_boundary or ""),
            str(fact.evidence_span_id or ""),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
