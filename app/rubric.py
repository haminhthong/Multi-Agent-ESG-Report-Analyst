import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import RubricCriterion

_RUBRIC_FILENAME = "climate_disclosure_v1.yaml"
_RUBRIC_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "rubrics" / _RUBRIC_FILENAME,
    Path(sys.prefix) / "rubrics" / _RUBRIC_FILENAME,
    Path.cwd() / "rubrics" / _RUBRIC_FILENAME,
)
CLIMATE_RUBRIC_PATH = next(
    (path for path in _RUBRIC_CANDIDATES if path.is_file()), _RUBRIC_CANDIDATES[0]
)
KNOWN_FACT_TYPES = {
    "scope_1_emissions",
    "scope_2_emissions",
    "scope_3_emissions",
    "net_zero_target",
    "renewable_energy",
    "work_safety",
    "gender_diversity",
    "supplier_assessment",
}


def load_climate_rubric(path: Path | None = None) -> tuple[str, list[RubricCriterion]]:
    """Nạp và kiểm tra rubric khí hậu phiên bản hóa từ một nguồn duy nhất."""
    rubric_path = path or CLIMATE_RUBRIC_PATH
    raw_text = rubric_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        payload: dict[str, Any] = yaml.safe_load(raw_text) or {}
    except ImportError:
        # File được commit cũng hợp lệ như JSON để công cụ nhẹ vẫn chạy khi chưa cài YAML.
        payload = json.loads(raw_text)

    version = str(payload.get("version") or "").strip()
    if not version:
        raise ValueError("Climate rubric must declare a version")

    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("Climate rubric must contain a non-empty criteria list")

    seen_ids: set[str] = set()
    loaded: list[RubricCriterion] = []
    for item in criteria:
        if not isinstance(item, dict):
            raise TypeError("Every climate rubric criterion must be a mapping")
        criterion_id = str(item.get("id") or "").strip()
        if not criterion_id or criterion_id in seen_ids:
            raise ValueError(f"Duplicate or missing climate criterion id: {criterion_id!r}")
        seen_ids.add(criterion_id)
        fact_types = [str(value) for value in item.get("fact_types", [])]
        unknown_facts = sorted(set(fact_types) - KNOWN_FACT_TYPES)
        if unknown_facts:
            raise ValueError(f"Unknown fact types for {criterion_id}: {unknown_facts}")
        required_fields = [str(value) for value in item.get("required_fields", [])]
        field_validators = {
            str(key): str(value) for key, value in (item.get("field_validators") or {}).items()
        }
        missing_validators = sorted(set(required_fields) - set(field_validators))
        if missing_validators:
            raise ValueError(
                f"Required fields without validators for {criterion_id}: {missing_validators}"
            )
        loaded.append(
            RubricCriterion(
                id=criterion_id,
                pillar=item.get("pillar", "E"),
                name=str(item.get("name") or criterion_id),
                description=str(item.get("description") or ""),
                framework_reference=item.get("framework_reference"),
                retrieval_keywords=[str(v) for v in item.get("retrieval_keywords", [])],
                retrieval_queries=[str(v) for v in item.get("retrieval_queries", [])],
                required_fields=required_fields,
                required_evidence=[str(v) for v in item.get("required_evidence", [])],
                metric_units=[str(v) for v in item.get("metric_units", [])],
                mandatory=bool(item.get("mandatory", False)),
                fact_types=fact_types,
                field_validators=field_validators,
                rubric_version=version,
            )
        )
    return version, loaded


@dataclass(frozen=True)
class PillarRubric:
    """Cấu hình từ khóa chủ đề (topics) và danh sách tiêu chí công bố (criteria) cho một trụ cột ESG."""

    topics: tuple[str, ...]
    criteria: dict[str, tuple[str, ...]]


RUBRICS = {
    "E": PillarRubric(
        topics=(
            "emission",
            "climate",
            "energy",
            "carbon",
            "water",
            "waste",
            "renewable",
            "biodiversity",
            "scope 1",
            "scope 2",
            "scope 3",
        ),
        criteria={
            "scope_1_2": ("scope 1", "scope 2"),
            "scope_3": ("scope 3",),
            "targets": ("target", "net zero", "net-zero", "goal", "commit"),
            "performance": ("reduced", "decreased", "increased", "progress"),
            "resources": ("water", "waste", "biodiversity", "renewable", "mwh", "gwh", "gj", "tj"),
        },
    ),
    "S": PillarRubric(
        topics=(
            "safety",
            "employee",
            "diversity",
            "community",
            "human rights",
            "training",
            "injury",
            "supplier",
            "fatalit",
            "gender",
        ),
        criteria={
            "safety": ("safety", "injury", "fatalit", "incidents"),
            "workforce": ("employee", "workforce", "training"),
            "inclusion": ("diversity", "inclusion", "gender", "women"),
            "human_rights": ("human rights", "forced labor", "child labor"),
            "supply_chain": ("supplier", "supply chain", "social criteria"),
        },
    ),
    "G": PillarRubric(
        topics=(
            "board",
            "ethics",
            "governance",
            "audit",
            "privacy",
            "compliance",
            "corruption",
            "risk management",
            "assurance",
            "independent",
        ),
        criteria={
            "oversight": ("board", "oversight", "committee"),
            "ethics": ("ethics", "code of conduct", "compliance"),
            "anti_corruption": ("anti-corruption", "anticorruption", "bribery"),
            "risk": ("risk management", "climate risk", "enterprise risk"),
            "assurance": ("assurance", "independent", "audit", "external assurance"),
        },
    ),
}

# Từ ngữ mang tính hứa hẹn suông, tham vọng chung chung nhưng thiếu bằng chứng số liệu cụ thể
VAGUE_WORDS = ("aim", "aspire", "committed", "ambition", "world-class", "leading", "strive")

# ==============================================================================
# CÁC MẪU BIỂU THỨC CHÍNH QUY (REGEX) NÂNG CAO
# ==============================================================================

# Nhận diện số liệu đo lường cụ thể kèm đơn vị thực tế (%, tCO2e, ktCO2e, MtCO2e, MWh, GWh, GJ, TJ, m3, ML, giờ...)
METRIC_PATTERN = re.compile(
    r"\b\d+(?:[,.]\d+)*\s*"
    r"(?:%|tons?|tonnes?|tco2e|co2e|ktco2e|mtco2e|mwh|gwh|gj|tj|m3|m³|ml|hours?|"
    r"employees?|suppliers?|incidents?|fatalities)"
    r"(?=\s|[.,;:)]|$)",
    re.IGNORECASE,
)

# Nhận diện năm báo cáo hoặc năm mốc thời gian
YEAR_PATTERN = re.compile(r"\b20[12]\d\b")

# Nhận diện cam kết mục tiêu CÓ NGỮ CẢNH (không coi mọi năm đơn lẻ là target)
TARGET_PATTERN = re.compile(
    r"\b(?:target|targets|goal|goals|commit|commits|committed|commitment|aim|aims|net[ -]?zero)\b.{0,80}?\b(?:20[2-5]\d)\b",
    re.IGNORECASE,
)

# Nhận diện có khai báo năm cơ sở.
BASELINE_PATTERN = re.compile(
    r"\b(?:baseline|base year|compared (?:with|to)|from 20[12]\d)\b",
    re.IGNORECASE,
)

# Nhận diện tuyên bố có sự kiểm toán/bảo đảm từ bên thứ ba độc lập
ASSURANCE_PATTERN = re.compile(
    r"\b(?:independent|external|limited|reasonable)\s+(?:assurance|assured|audit|audited)\b",
    re.IGNORECASE,
)

# Nhận diện mẫu phủ định.
NEGATED_ASSURANCE_PATTERN = re.compile(
    r"(?:\b(?:no|not|without|lack(?:s|ed)?)\b.{0,60}?\b(?:independent|external)?\s*(?:assurance|assured|audit|audited)\b|"
    r"\b(?:independent|external)?\s*(?:assurance|assured|audit|audited)\b.{0,60}?\b(?:was not|not|missing|unprovided|not provided|not conducted)\b)",
    re.IGNORECASE,
)

NEGATED_BASELINE_PATTERN = re.compile(
    r"(?:\b(?:no|not|without|lack(?:s|ed)?)\b.{0,40}?\b(?:baseline|base year)\b|"
    r"\b(?:baseline|base year)\b.{0,40}?\b(?:was not|not|missing|unspecified|not disclosed)\b)",
    re.IGNORECASE,
)

NEGATED_PERFORMANCE_PATTERN = re.compile(
    r"\b(?:not achieved|missed|failed|did not decrease|did not reduce|increased emissions)\b",
    re.IGNORECASE,
)


def normalize_number(text: str) -> str:
    """Chuẩn hóa dấu định dạng số theo ngữ cảnh (ví dụ: 1,234.5 -> 1234.5 hoặc 1.234,5 -> 1234.5)."""
    # Xử lý định dạng Châu Âu (1.234,5 -> 1234.5)
    if re.search(r"\b\d{1,3}(?:\.\d{3})+,\d+\b", text):
        return text.replace(".", "").replace(",", ".")
    # Xử lý định dạng chuẩn (1,234.5 -> 1234.5)
    if re.search(r"\b\d{1,3}(?:,\d{3})+\.\d+\b", text):
        return text.replace(",", "")
    return text


# Tiêu chí review đang dùng được nạp từ rubric khí hậu phiên bản hóa.
CLIMATE_RUBRIC_VERSION, CLIMATE_CRITERIA_DEFINITIONS = load_climate_rubric()
CRITERIA_DEFINITIONS = CLIMATE_CRITERIA_DEFINITIONS
DEFAULT_CRITERIA_DEFINITIONS = CLIMATE_CRITERIA_DEFINITIONS

LEGACY_CRITERION_ALIASES: dict[str, str] = {
    "E_GHG_SCOPE_1_2": "CLM_GHG_SCOPE_1",
    "E_GHG_SCOPE_3": "CLM_GHG_SCOPE_3",
    "E_TARGETS": "CLM_TARGET",
    "E_TARGET_SETTING": "CLM_TARGET",
    "E_PERFORMANCE": "CLM_PROGRESS",
    "E_RENEWABLE_ENERGY": "CLM_PROGRESS",
    "S_HEALTH_SAFETY": "CLM_GHG_SCOPE_1",
    "S_WORK_SAFETY": "CLM_GHG_SCOPE_1",
    "S_DIVERSITY_INCLUSION": "CLM_PROGRESS",
    "S_SUPPLY_CHAIN_LABOR": "CLM_METHOD_BOUNDARY",
    "G_EXTERNAL_ASSURANCE": "CLM_ASSURANCE",
}


def resolve_criterion_id(criterion_id: str) -> str:
    """Đổi ID tiêu chí cũ sang ID của rubric phiên bản hiện hành."""
    return LEGACY_CRITERION_ALIASES.get(criterion_id, criterion_id)
