"""Unit normalizer for quantitative ESG metrics."""

from typing import Any


class UnitNormalizer:
    """Bộ chuẩn hóa đơn vị đo lường và giá trị số học cho các chỉ số ESG."""

    # Hệ số quy đổi về tCO2e cho phát thải GHG
    GHG_CONVERSIONS: dict[str, float] = {
        "ktco2e": 1000.0,
        "thousand metric tons": 1000.0,
        "thousand metric tons co2e": 1000.0,
        "mtco2e": 1000000.0,
        "million metric tons": 1000000.0,
        "million metric tons co2e": 1000000.0,
        "million tons": 1000000.0,
        "mmt": 1000000.0,
        "tco2e": 1.0,
        "co2e": 1.0,
        "metric tons": 1.0,
        "metric tons co2e": 1.0,
        "tons": 1.0,
        "tonnes": 1.0,
        "tons co2e": 1.0,
    }

    # Hệ số quy đổi về MWh cho năng lượng
    ENERGY_CONVERSIONS: dict[str, float] = {
        "gwh": 1000.0,
        "mwh": 1.0,
        "kwh": 0.001,
        "tj": 277.778,
        "gj": 0.277778,
        "megawatts": 1.0,
        "mw": 1.0,
    }

    @classmethod
    def normalize(
        cls, metric: str, raw_value: float | str | None, raw_unit: str | None
    ) -> tuple[float | None, str | None]:
        """Chuẩn hóa giá trị định lượng và đơn vị đo lường về đơn vị chuẩn (Canonical Base Unit)."""
        if raw_value is None:
            return None, raw_unit

        try:
            val_float = float(raw_value) if isinstance(raw_value, (int, float, str)) else None
        except (ValueError, TypeError):
            return None, raw_unit

        if val_float is None:
            return None, raw_unit

        unit_str = raw_unit.lower().strip() if raw_unit else ""

        if "emission" in metric or "scope" in metric or "co2" in unit_str or "ton" in unit_str:
            if unit_str == "%":
                return val_float, "%"
            for pattern, factor in cls.GHG_CONVERSIONS.items():
                if pattern in unit_str:
                    return round(val_float * factor, 4), "tCO2e"
            return val_float, "tCO2e" if "emission" in metric else (raw_unit or "tCO2e")

        if (
            "renewable" in metric
            or "energy" in metric
            or any(u in unit_str for u in ["mwh", "gwh", "kwh", "tj", "gj", "mw"])
        ):
            if unit_str == "%":
                return val_float, "%"
            for pattern, factor in cls.ENERGY_CONVERSIONS.items():
                if pattern in unit_str:
                    canonical_u = "MW" if "mw" in pattern and "mwh" not in pattern else "MWh"
                    return round(val_float * factor, 4), canonical_u
            return val_float, raw_unit or "MWh"

        if "%" in unit_str or "diversity" in metric:
            return val_float, "%"

        return val_float, raw_unit
