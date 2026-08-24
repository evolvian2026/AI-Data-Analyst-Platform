"""Value formatting shared by the narrative, PDF and export layers."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P


def is_text_column(series: pd.Series) -> bool:
    """True for columns holding text.

    pandas infers a dedicated string dtype for text columns, so a bare
    ``dtype == object`` check silently misses them - and anything that depends
    on it (such as escaping exported values) would quietly stop running.
    """
    return bool(
        pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
    ) and not pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_datetime64_any_dtype(series)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not (
        isinstance(value, float) and (math.isnan(value) or math.isinf(value))
    )


def compact_number(value: float, currency: str = "") -> str:
    """Human-friendly magnitude: 12.5M, 4.2K, 1.1B."""
    if not is_number(value):
        return "n/a"
    sign = "-" if value < 0 else ""
    absolute = abs(float(value))
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if absolute >= threshold:
            return f"{sign}{currency}{absolute / threshold:,.2f}{suffix}".replace(".00", "")
    if absolute >= 1000:
        return f"{sign}{currency}{absolute:,.0f}"
    if absolute >= 1:
        return f"{sign}{currency}{absolute:,.2f}"
    if absolute == 0:
        return f"{currency}0"
    return f"{sign}{currency}{absolute:,.4g}"


def format_value(value: Any, semantic_type: str = "", currency: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%d %b %Y")
    if semantic_type == P.PERCENTAGE:
        return f"{float(value):,.1f}%"
    if semantic_type == P.CURRENCY:
        return compact_number(float(value), currency or "")
    if semantic_type == P.INTEGER and is_number(value):
        return f"{float(value):,.0f}"
    if is_number(value):
        return compact_number(float(value), currency if semantic_type == P.CURRENCY else "")
    return str(value)


def format_delta(pct: float | None) -> str:
    """Percentage change, switched to a multiple once a percentage stops reading."""
    if pct is None or not is_number(pct):
        return "n/a"
    if pct >= 300:
        return f"{1 + pct / 100:,.1f}x"
    return f"{'+' if pct >= 0 else ''}{pct:,.1f}%"


def percent(part: float, whole: float) -> float:
    if not whole:
        return 0.0
    return part / whole * 100.0


def safe_float(value: Any) -> float | None:
    """Convert numpy / pandas scalars to plain JSON-safe floats."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def jsonify(value: Any) -> Any:
    """Recursively convert numpy/pandas objects into JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(k): jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonify(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return safe_float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if isinstance(value, float):
        return safe_float(value)
    if isinstance(value, pd.Series):
        return jsonify(value.tolist())
    return value


def humanize_column(name: str) -> str:
    cleaned = str(name).replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count:,} {plural_form or singular + 's'}"
