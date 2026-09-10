"""Chuẩn hóa đơn vị theo dimension cho số liệu ESG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class UnitDefinition:
    """Metadata đơn vị chuẩn; chỉ cho phép đổi trong cùng dimension."""

    dimension: str
    canonical_unit: str
    factor_to_canonical: float


class UnitNormalizer:
    """Chuẩn hóa giá trị mà không nhầm power, energy, emissions hoặc ratio."""

    UNIT_REGISTRY: ClassVar[dict[str, UnitDefinition]] = {
        # Khối lượng phát thải.
        "ktco2e": UnitDefinition("emissions_mass", "tCO2e", 1_000.0),
        "thousand metric tons": UnitDefinition("emissions_mass", "tCO2e", 1_000.0),
        "thousand metric tons co2e": UnitDefinition("emissions_mass", "tCO2e", 1_000.0),
        "mtco2e": UnitDefinition("emissions_mass", "tCO2e", 1_000_000.0),
        "million metric tons": UnitDefinition("emissions_mass", "tCO2e", 1_000_000.0),
        "million metric tons co2e": UnitDefinition("emissions_mass", "tCO2e", 1_000_000.0),
        "million tons": UnitDefinition("emissions_mass", "tCO2e", 1_000_000.0),
        "mmt": UnitDefinition("emissions_mass", "tCO2e", 1_000_000.0),
        "tco2e": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        "co2e": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        "metric tons co2e": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        "metric tons": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        "tonnes co2e": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        "tonnes": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        "tons co2e": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        "tons": UnitDefinition("emissions_mass", "tCO2e", 1.0),
        # Năng lượng: đơn vị chuẩn là MWh.
        "gwh": UnitDefinition("energy", "MWh", 1_000.0),
        "mwh": UnitDefinition("energy", "MWh", 1.0),
        "kwh": UnitDefinition("energy", "MWh", 0.001),
        "tj": UnitDefinition("energy", "MWh", 277.778),
        "gj": UnitDefinition("energy", "MWh", 0.277778),
        # Công suất tách riêng khỏi năng lượng; MW không được tự đổi thành MWh.
        "megawatts": UnitDefinition("power", "MW", 1.0),
        "megawatt": UnitDefinition("power", "MW", 1.0),
        "mw": UnitDefinition("power", "MW", 1.0),
        # Tỷ lệ và số đếm đã ở dạng chuẩn.
        "%": UnitDefinition("ratio", "%", 1.0),
    }

    # Tên cũ được giữ để đọc dữ liệu từ các bảng chuyển đổi trước đây.
    GHG_CONVERSIONS: ClassVar[dict[str, float]] = {
        key: definition.factor_to_canonical
        for key, definition in UNIT_REGISTRY.items()
        if definition.dimension == "emissions_mass"
    }
    ENERGY_CONVERSIONS: ClassVar[dict[str, float]] = {
        key: definition.factor_to_canonical
        for key, definition in UNIT_REGISTRY.items()
        if definition.dimension in {"energy", "power"}
    }

    @classmethod
    def _lookup_unit(cls, raw_unit: str | None) -> UnitDefinition | None:
        if not raw_unit:
            return None
        unit_str = re.sub(r"\s+", " ", raw_unit.lower().strip())
        for alias in sorted(cls.UNIT_REGISTRY, key=len, reverse=True):
            if unit_str == alias or re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", unit_str):
                return cls.UNIT_REGISTRY[alias]
        return None

    @classmethod
    def normalize(
        cls, metric: str, raw_value: float | str | None, raw_unit: str | None
    ) -> tuple[float | None, str | None]:
        """Trả về ``(normalized_value, normalized_unit)`` và giữ an toàn dimension."""
        if raw_value is None:
            return None, raw_unit
        try:
            value = float(raw_value)
        except (ValueError, TypeError):
            return None, raw_unit

        metric_lower = metric.lower()
        unit_definition = cls._lookup_unit(raw_unit)
        if raw_unit and raw_unit.strip() == "%":
            return value, "%"

        if unit_definition and unit_definition.dimension == "emissions_mass":
            return round(value * unit_definition.factor_to_canonical, 4), "tCO2e"
        if unit_definition and unit_definition.dimension == "power":
            return round(value * unit_definition.factor_to_canonical, 4), "MW"
        if unit_definition and unit_definition.dimension == "energy":
            return round(value * unit_definition.factor_to_canonical, 4), "MWh"

        if "%" in (raw_unit or "") or "diversity" in metric_lower:
            return value, "%" if raw_unit else None

        if any(token in metric_lower for token in ("emission", "scope", "co2")):
            # Không tự bịa đơn vị khi nguồn không cung cấp.
            return value, None
        if any(token in metric_lower for token in ("renewable", "energy")):
            return value, None
        return value, raw_unit
