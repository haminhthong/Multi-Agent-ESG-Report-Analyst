import re
from dataclasses import dataclass
from app.models import RubricCriterion


@dataclass(frozen=True)
class PillarRubric:
    """Cấu hình từ khóa chủ đề (topics) và danh sách tiêu chí công bố (criteria) cho một trụ cột ESG."""

    topics: tuple[str, ...]
    criteria: dict[str, tuple[str, ...]]


# ==============================================================================
# BỘ TIÊU CHÍ CẤU TRÚC CHUẨN MỰC (STRUCTURED ESG CRITERIA)
# ==============================================================================
CRITERIA_DEFINITIONS: list[RubricCriterion] = [
    # Environment
    RubricCriterion(
        id="E_GHG_SCOPE_1_2",
        pillar="E",
        name="Phát thải Scope 1 và Scope 2",
        description="Công bố giá trị phát thải tuyệt đối Scope 1 và Scope 2 theo kỳ báo cáo",
        framework_reference="GRI 305-1 / GRI 305-2",
        required_evidence=["scope_1_value", "scope_2_value", "unit", "reporting_year"],
        metric_units=["tCO2e", "ktCO2e", "MtCO2e", "co2e", "tons", "tonnes"],
        mandatory=True,
    ),
    RubricCriterion(
        id="E_GHG_SCOPE_3",
        pillar="E",
        name="Phát thải Scope 3",
        description="Công bố phát thải gián tiếp trong chuỗi giá trị (Scope 3)",
        framework_reference="GRI 305-3",
        required_evidence=["scope_3_value", "unit"],
        metric_units=["tCO2e", "ktCO2e", "MtCO2e", "co2e"],
        mandatory=False,
    ),
    RubricCriterion(
        id="E_TARGETS",
        pillar="E",
        name="Mục tiêu giảm phát thải & Net-Zero",
        description="Cam kết mục tiêu giảm phát thải kèm năm đích (Target year) và năm cơ sở (Baseline year)",
        framework_reference="GRI 305-5 / TCFD",
        required_evidence=["target_statement", "target_year", "baseline_year"],
        metric_units=["%", "tCO2e", "net-zero"],
        mandatory=True,
    ),
    RubricCriterion(
        id="E_PERFORMANCE",
        pillar="E",
        name="Tiến độ thực hiện & Biến động phát thải",
        description="Số liệu so sánh tiến độ thực hiện giảm phát thải so với năm cơ sở",
        framework_reference="GRI 305-5",
        required_evidence=["current_value", "baseline_value", "change_percentage"],
        metric_units=["%", "tCO2e"],
        mandatory=False,
    ),
    RubricCriterion(
        id="E_RESOURCE_MANAGEMENT",
        pillar="E",
        name="Quản lý Năng lượng, Nước & Tiêu thụ Tài nguyên",
        description="Số liệu tiêu thụ năng lượng tái tạo, quản lý nguồn nước và rác thải",
        framework_reference="GRI 302 / GRI 303 / GRI 306",
        required_evidence=["resource_value", "unit"],
        metric_units=["MWh", "GWh", "GJ", "TJ", "m3", "m³", "ML", "%"],
        mandatory=False,
    ),
    # Social
    RubricCriterion(
        id="S_WORK_SAFETY",
        pillar="S",
        name="An toàn & Sức khỏe Lao động",
        description="Báo cáo số sự cố an toàn, tỷ lệ chấn thương hoặc số giờ huấn luyện an toàn",
        framework_reference="GRI 403-9",
        required_evidence=["safety_metric", "unit"],
        metric_units=["incidents", "rate per 200,000 hours", "hours", "fatalities"],
        mandatory=True,
    ),
    RubricCriterion(
        id="S_WORKFORCE",
        pillar="S",
        name="Quy mô Nhân sự & Đào tạo",
        description="Số lượng lao động, giờ đào tạo bình quân và mức đầu tư nhân lực",
        framework_reference="GRI 404-1",
        required_evidence=["employee_count", "training_hours"],
        metric_units=["employees", "hours", "person-hours"],
        mandatory=False,
    ),
    RubricCriterion(
        id="S_INCLUSION",
        pillar="S",
        name="Đa dạng & Bình đẳng giới",
        description="Tỷ lệ nữ giới trong nhân sự, cấp quản lý hoặc HĐQT",
        framework_reference="GRI 405-1",
        required_evidence=["diversity_percentage", "group"],
        metric_units=["%"],
        mandatory=False,
    ),
    RubricCriterion(
        id="S_HUMAN_RIGHTS",
        pillar="S",
        name="Quyền Con người & Lao động Trẻ em/Cưỡng bức",
        description="Chính sách và rà soát tuân thủ quyền con người trong hoạt động",
        framework_reference="GRI 412",
        required_evidence=["policy_statement", "due_diligence"],
        metric_units=["sites", "%"],
        mandatory=False,
    ),
    RubricCriterion(
        id="S_SUPPLY_CHAIN",
        pillar="S",
        name="Đánh giá ESG Chuỗi Cung ứng",
        description="Tỷ lệ nhà cung cấp được đánh giá theo tiêu chuẩn xã hội & môi trường",
        framework_reference="GRI 414-1",
        required_evidence=["supplier_count", "assessment_percentage"],
        metric_units=["suppliers", "%"],
        mandatory=False,
    ),
    # Governance
    RubricCriterion(
        id="G_BOARD_OVERSIGHT",
        pillar="G",
        name="Giám sát của Hội đồng Quản trị",
        description="Cơ cấu HĐQT, ủy ban ESG/bền vững và tính độc lập của các thành viên",
        framework_reference="GRI 2-9 / GRI 2-12",
        required_evidence=["committee_name", "board_independence"],
        metric_units=["%", "members"],
        mandatory=True,
    ),
    RubricCriterion(
        id="G_ETHICS",
        pillar="G",
        name="Đạo đức Kinh doanh & Bộ Quy tắc Ứng xử",
        description="Chính sách đạo đức, đào tạo tuân thủ cho cán bộ công nhân viên",
        framework_reference="GRI 2-23 / GRI 2-24",
        required_evidence=["code_of_conduct", "compliance_rate"],
        metric_units=["%", "employees"],
        mandatory=False,
    ),
    RubricCriterion(
        id="G_ANTI_CORRUPTION",
        pillar="G",
        name="Phòng chống Tham nhũng & Hối lộ",
        description="Chính sách phòng chống tham nhũng và kết quả kiểm tra/xử lý vi phạm",
        framework_reference="GRI 205-1 / GRI 205-3",
        required_evidence=["policy_statement", "confirmed_incidents"],
        metric_units=["incidents", "cases", "%"],
        mandatory=False,
    ),
    RubricCriterion(
        id="G_RISK_MANAGEMENT",
        pillar="G",
        name="Quản trị Rủi ro Khí hậu & ESG Enterprise Risk",
        description="Tích hợp rủi ro khí hậu (TCFD) vào khung quản trị rủi ro doanh nghiệp",
        framework_reference="GRI 2-12 / TCFD",
        required_evidence=["risk_framework", "assessment"],
        metric_units=[],
        mandatory=False,
    ),
    RubricCriterion(
        id="G_EXTERNAL_ASSURANCE",
        pillar="G",
        name="Bảo đảm Độc lập từ Bên thứ Ba",
        description="Tuyên bố hoặc báo cáo bảo đảm độc lập (Limited/Reasonable assurance) cho số liệu ESG",
        framework_reference="GRI 2-5 / ISAE 3000",
        required_evidence=["assurance_provider", "scope", "opinion_type"],
        metric_units=[],
        mandatory=True,
    ),
]


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
# CÁC MẪU BIỂU THỨC CHÍNH QUY (REGEX PATTERNS) NÂNG CAO
# ==============================================================================


# Nhận diện số liệu đo lường cụ thể kèm đơn vị thực tế (%, tCO2e, ktCO2e, MtCO2e, MWh, GWh, GJ, TJ, m3, ML, hours...)
METRIC_PATTERN = re.compile(
    r"\b\d+(?:[,.]\d+)?\s*"
    r"(?:%|tons?|tonnes?|tco2e|co2e|ktco2e|mtco2e|mwh|gwh|gj|tj|m3|m³|ml|hours?|"
    r"employees?|suppliers?|incidents?|fatalities)"
    r"(?=\s|[.,;:)]|$)",
    re.IGNORECASE,
)

# Nhận diện năm báo cáo hoặc năm mốc thời gian
YEAR_PATTERN = re.compile(r"\b20[12]\d\b")

# Nhận diện cam kết mục tiêu CÓ NGỮ CẢNH (không coi mọi năm đơn lẻ là target)
TARGET_PATTERN = re.compile(
    r"\b(?:target|goal|commit|aim|net[ -]?zero)\b.{0,80}?\b(?:20[2-5]\d)\b",
    re.IGNORECASE,
)

# Nhận diện có khai báo "năm cơ sở" (Baseline year)
BASELINE_PATTERN = re.compile(
    r"\b(?:baseline|base year|compared (?:with|to)|from 20[12]\d)\b",
    re.IGNORECASE,
)

# Nhận diện tuyên bố có sự kiểm toán/bảo đảm từ bên thứ ba độc lập
ASSURANCE_PATTERN = re.compile(
    r"\b(?:independent|external|limited|reasonable) assurance\b",
    re.IGNORECASE,
)

# Nhận diện Phủ định (Negation Patterns)
NEGATED_ASSURANCE_PATTERN = re.compile(
    r"(?:\b(?:no|not|without|lack(?:s|ed)?)\b.{0,40}?\b(?:independent|external)?\s*assurance\b|"
    r"\b(?:independent|external)?\s*assurance\b.{0,40}?\b(?:was not|not|missing|unprovided|not provided)\b)",
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
