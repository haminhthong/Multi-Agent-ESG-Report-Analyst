"""Fact validation and multidimensional conflict detection."""

from app.models import ESGFact, EvidenceConflict


def detect_conflicts(facts: list[ESGFact]) -> list[EvidenceConflict]:
    """Phát hiện mâu thuẫn số liệu công bố đa chiều (Multidimensional Conflict Detection):

    Khóa phân nhóm đa chiều: (company, metric, year, methodology, organizational_boundary, unit).
    Tránh báo động mâu thuẫn giả giữa các công ty khác nhau (ví dụ Boeing vs Alcoa),
    hoặc giữa Scope 2 location-based vs market-based hoặc Gross vs Net.
    So sánh trên normalized_value theo normalized_unit chuẩn.
    """
    conflicts: list[EvidenceConflict] = []
    groups: dict[
        tuple[str, str, int | None, str | None, str | None, str | None], list[ESGFact]
    ] = {}

    for fact in facts:
        val = fact.normalized_value if fact.normalized_value is not None else fact.value
        if val is None or not isinstance(val, (int, float)):
            continue
        company = (
            fact.company
            or (fact.source.company if fact.source else None)
            or (fact.source.document_id if fact.source else "default_entity")
        )
        unit = fact.normalized_unit or fact.unit
        key = (
            company,
            fact.metric,
            fact.reporting_year or fact.year,
            fact.methodology,
            fact.organizational_boundary,
            unit,
        )
        groups.setdefault(key, []).append(fact)

    for (company, metric, year, methodology, boundary, unit), fact_list in groups.items():
        if len(fact_list) < 2:
            continue

        values = [
            float(f.normalized_value if f.normalized_value is not None else f.value)  # type: ignore[arg-type]
            for f in fact_list
            if isinstance(
                f.normalized_value if f.normalized_value is not None else f.value,
                (int, float),
            )
        ]
        if not values:
            continue

        min_val, max_val = min(values), max(values)
        # Nếu chênh lệch tương đối lớn hơn 1%
        if min_val > 0 and (max_val - min_val) / min_val > 0.01:
            severity = "high" if (max_val - min_val) / min_val > 0.10 else "medium"
            meth_desc = f" [{methodology}]" if methodology else ""
            comp_desc = f" [{company}]" if company and company != "default_entity" else ""
            disclosures = [
                {
                    "document": f.source.document_name if f.source else "unknown",
                    "page": f.source.page if f.source else 0,
                    "value": f.value,
                    "unit": f.unit,
                    "normalized_value": f.normalized_value,
                    "normalized_unit": f.normalized_unit,
                    "methodology": f.methodology,
                    "excerpt": f.source.excerpt[:150] if f.source else "",
                }
                for f in fact_list
            ]
            desc = (
                f"Mâu thuẫn số liệu công bố cho chỉ tiêu '{metric}'{meth_desc}{comp_desc} (năm {year or 'không xác định'}): "
                + " so với ".join(
                    f"trang {d['page']} ({d['value']} {d.get('unit') or ''})" for d in disclosures
                )
            )

            conflicts.append(
                EvidenceConflict(
                    metric=metric,
                    year=year,
                    disclosures=disclosures,
                    severity=severity,
                    description=desc,
                )
            )
            # Đánh dấu trạng thái conflict cho các fact
            for f in fact_list:
                f.status = "CONFLICT"
                f.validation_status = "conflict"
                f.verification_status = "conflict"

    return conflicts
