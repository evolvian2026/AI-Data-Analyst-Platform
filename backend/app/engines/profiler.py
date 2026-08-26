"""Data profiling / semantic type inference.

Types are inferred from the *values*, not from the column name, so the engine
works on any dataset without a hardcoded schema.  Column names are only used as
a weak tie-breaker when the values are ambiguous.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.engines.sanitize import neutralize_text

# --- semantic types ---------------------------------------------------------
INTEGER = "integer"
DECIMAL = "decimal"
CURRENCY = "currency"
PERCENTAGE = "percentage"
DATE = "date"
DATETIME = "datetime"
TIME = "time"
CATEGORICAL = "categorical"
TEXT = "text"
BOOLEAN = "boolean"
IDENTIFIER = "identifier"
GEOGRAPHIC = "geographic"
EMAIL = "email"
URL = "url"
UNKNOWN = "unknown"

NUMERIC_TYPES = {INTEGER, DECIMAL, CURRENCY, PERCENTAGE}
TEMPORAL_TYPES = {DATE, DATETIME, TIME}

# --- analytical roles -------------------------------------------------------
MEASURE = "measure"
DIMENSION = "dimension"
TIME_DIMENSION = "time"
IDENTIFIER_ROLE = "identifier"
DESCRIPTIVE = "descriptive"

CURRENCY_SYMBOLS = "₹$€£¥₩₽₺₪R$"
_CURRENCY_RE = re.compile(rf"^\s*[-+(]?\s*[{re.escape(CURRENCY_SYMBOLS)}]\s*[\d,.\s]+\)?\s*$")
_CURRENCY_CODE_RE = re.compile(
    r"^\s*[-+]?\s*(INR|USD|EUR|GBP|JPY|AUD|CAD|CHF|CNY|SGD|AED|ZAR)\s*[\d,.\s]+$", re.IGNORECASE
)
_PERCENT_RE = re.compile(r"^\s*[-+]?\d[\d,]*(\.\d+)?\s*%\s*$")
_NUMBER_RE = re.compile(r"^\s*[-+(]?\s*\d[\d,\s]*(\.\d+)?\)?\s*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_ID_LIKE_RE = re.compile(r"^[A-Za-z]{1,6}[-_ ]?\d{2,}$")
_TIME_RE = re.compile(r"^\s*([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?(\s*[APap][Mm])?\s*$")

_BOOLEAN_SETS = [
    {"true", "false"}, {"yes", "no"}, {"y", "n"}, {"1", "0"},
    {"t", "f"}, {"active", "inactive"}, {"pass", "fail"}, {"on", "off"},
]

_ID_NAME_HINTS = ("id", "code", "no", "number", "ref", "key", "uuid", "guid", "sku", "isbn", "roll")
_GEO_NAME_HINTS = (
    "country", "state", "province", "city", "region", "district", "zone", "territory",
    "location", "area", "branch", "store", "site", "market", "postcode", "zipcode",
    "zip", "pincode", "county", "continent", "address",
)
_GEO_VALUE_HINTS = {
    "north", "south", "east", "west", "central", "northeast", "northwest",
    "southeast", "southwest", "apac", "emea", "amer", "latam", "anz",
}
_DATE_NAME_HINTS = ("date", "day", "month", "year", "quarter", "period", "time", "week", "timestamp", "dt")
_MEASURE_NAME_HINTS = (
    "amount", "revenue", "sales", "price", "cost", "profit", "margin", "qty", "quantity",
    "total", "value", "salary", "score", "marks", "count", "spend", "budget", "balance",
    "rate", "units", "hours", "age", "weight", "height", "duration", "income", "expense",
    "discount", "tax", "fee", "volume", "gdp", "population",
)


@dataclass
class ColumnProfile:
    name: str
    position: int
    dtype: str
    semantic_type: str
    role: str
    count: int
    missing: int
    missing_pct: float
    unique: int
    unique_pct: float
    is_constant: bool
    sample_values: list[Any] = field(default_factory=list)
    top_values: list[dict[str, Any]] = field(default_factory=list)
    numeric_stats: dict[str, Any] = field(default_factory=dict)
    temporal_stats: dict[str, Any] = field(default_factory=dict)
    currency_symbol: str = ""
    aggregation: str = ""
    additive: bool = False
    non_negative: bool = True
    confidence: float = 1.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "dtype": self.dtype,
            "semantic_type": self.semantic_type,
            "role": self.role,
            "count": self.count,
            "missing": self.missing,
            "missing_pct": round(self.missing_pct, 2),
            "unique": self.unique,
            "unique_pct": round(self.unique_pct, 2),
            "is_constant": self.is_constant,
            "sample_values": self.sample_values,
            "top_values": self.top_values,
            "numeric_stats": self.numeric_stats,
            "temporal_stats": self.temporal_stats,
            "currency_symbol": self.currency_symbol,
            "aggregation": self.aggregation,
            "additive": self.additive,
            "non_negative": self.non_negative,
            "confidence": round(self.confidence, 2),
            "notes": self.notes,
        }


# --- value level helpers ----------------------------------------------------

def _clean_number(value: str) -> float | None:
    text = value.strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(rf"[{re.escape(CURRENCY_SYMBOLS)}]", "", text)
    text = re.sub(r"(?i)^(INR|USD|EUR|GBP|JPY|AUD|CAD|CHF|CNY|SGD|AED|ZAR)\s*", "", text)
    text = text.replace("%", "").replace(",", "").replace(" ", "").replace(" ", "")
    if not text or text in {"-", "+", "."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def to_numeric_series(series: pd.Series) -> pd.Series:
    """Best-effort numeric conversion that understands currency and percents."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    converted = series.map(
        lambda v: _clean_number(v) if isinstance(v, str) else (v if isinstance(v, (int, float, np.number)) else None)
    )
    return pd.to_numeric(converted, errors="coerce")


def to_datetime_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    # Bare four-digit years must not be read as epoch nanoseconds.
    numeric = pd.to_numeric(series, errors="coerce")
    non_null = numeric.dropna()
    if len(non_null) and _looks_like_year(non_null):
        try:
            return pd.to_datetime(
                numeric.astype("Int64").astype("string"), format="%Y", errors="coerce"
            )
        except (ValueError, TypeError):
            pass
    with pd.option_context("mode.chained_assignment", None):
        try:
            parsed = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)
        except (ValueError, TypeError):
            try:
                parsed = pd.to_datetime(series, errors="coerce")
            except (ValueError, TypeError):
                return pd.Series([pd.NaT] * len(series), index=series.index)
    return parsed


def _ratio(matches: int, total: int) -> float:
    return matches / total if total else 0.0


def _detect_currency_symbol(values: list[str]) -> str:
    for value in values:
        for symbol in CURRENCY_SYMBOLS:
            if symbol in value:
                return symbol
    return ""


def infer_semantic_type(series: pd.Series, name: str) -> tuple[str, float, str, list[str]]:
    """Return (semantic_type, confidence, currency_symbol, notes)."""
    notes: list[str] = []
    lowered = str(name).strip().lower()
    non_null = series.dropna()
    total = len(non_null)
    if total == 0:
        return UNKNOWN, 0.0, "", ["Column is entirely empty."]

    unique = non_null.nunique(dropna=True)
    unique_ratio = unique / total

    # --- native dtypes come first ------------------------------------------
    if pd.api.types.is_bool_dtype(series):
        return BOOLEAN, 1.0, "", notes
    if pd.api.types.is_datetime64_any_dtype(series):
        has_time = bool((non_null.dt.hour.ne(0) | non_null.dt.minute.ne(0) | non_null.dt.second.ne(0)).any())
        return (DATETIME if has_time else DATE), 1.0, "", notes

    sample = non_null.sample(min(total, 2000), random_state=7) if total > 2000 else non_null
    string_values = [str(v).strip() for v in sample.tolist()]
    sample_size = len(string_values)

    lowered_values = {v.lower() for v in string_values}
    if unique <= 3 and any(lowered_values <= bset or lowered_values == bset for bset in _BOOLEAN_SETS):
        return BOOLEAN, 0.95, "", notes

    if _ratio(sum(1 for v in string_values if _EMAIL_RE.match(v)), sample_size) > 0.8:
        return EMAIL, 0.95, "", notes
    if _ratio(sum(1 for v in string_values if _URL_RE.match(v)), sample_size) > 0.8:
        return URL, 0.95, "", notes

    percent_ratio = _ratio(sum(1 for v in string_values if _PERCENT_RE.match(v)), sample_size)
    if percent_ratio > 0.7:
        return PERCENTAGE, 0.9 + 0.1 * percent_ratio, "", notes

    currency_ratio = _ratio(
        sum(1 for v in string_values if _CURRENCY_RE.match(v) or _CURRENCY_CODE_RE.match(v)), sample_size
    )
    if currency_ratio > 0.7:
        return CURRENCY, min(1.0, 0.85 + currency_ratio * 0.15), _detect_currency_symbol(string_values), notes

    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if len(numeric) == 0:
            return UNKNOWN, 0.2, "", notes
        if _name_suggests_percentage(lowered) and numeric.between(-100, 100).mean() > 0.95:
            return PERCENTAGE, 0.75, "", ["Numeric values with a percentage-style column name."]
        is_integral = bool(np.all(np.equal(np.mod(numeric.to_numpy(dtype=float), 1), 0)))
        if is_integral:
            # A numeric column of near-unique integers with an id-ish name is a key.
            if unique_ratio > 0.9 and _name_suggests_id(lowered):
                return IDENTIFIER, 0.85, "", ["Near-unique integers with an identifier-style name."]
            if lowered in {"year"} or (
                _looks_like_year(numeric) and ("year" in lowered or "yr" in lowered)
            ):
                return DATE, 0.8, "", ["Four-digit values interpreted as years."]
            if unique <= 12 and unique_ratio < 0.05 and not _name_suggests_measure(lowered):
                return CATEGORICAL, 0.7, "", ["Small set of repeated integer codes."]
            return INTEGER, 0.95, "", notes
        return DECIMAL, 0.95, "", notes

    # --- textual columns ----------------------------------------------------
    numeric_ratio = _ratio(sum(1 for v in string_values if _NUMBER_RE.match(v)), sample_size)
    if numeric_ratio > 0.85:
        parsed = pd.to_numeric([_clean_number(v) for v in string_values], errors="coerce")
        parsed = pd.Series(parsed).dropna()
        if len(parsed):
            if unique_ratio > 0.95 and _name_suggests_id(lowered):
                return IDENTIFIER, 0.8, "", ["Numeric text that is unique per row."]
            integral = bool(np.all(np.equal(np.mod(parsed.to_numpy(dtype=float), 1), 0)))
            notes.append("Stored as text; converted to numbers for analysis.")
            return (INTEGER if integral else DECIMAL), 0.75, "", notes

    if _ratio(sum(1 for v in string_values if _TIME_RE.match(v)), sample_size) > 0.8:
        return TIME, 0.9, "", notes

    date_like = to_datetime_series(sample)
    date_ratio = _ratio(int(date_like.notna().sum()), sample_size)
    if date_ratio > 0.85:
        has_time = bool(
            (date_like.dt.hour.ne(0) | date_like.dt.minute.ne(0) | date_like.dt.second.ne(0)).any()
        )
        notes.append("Stored as text; parsed as dates for analysis.")
        return (DATETIME if has_time else DATE), 0.8, "", notes

    id_like_ratio = _ratio(sum(1 for v in string_values if _ID_LIKE_RE.match(v)), sample_size)
    if id_like_ratio > 0.8 and unique_ratio > 0.7:
        return IDENTIFIER, 0.9, "", notes
    if unique_ratio > 0.95 and total > 20 and _name_suggests_id(lowered):
        return IDENTIFIER, 0.8, "", ["Unique per row with an identifier-style name."]

    avg_len = float(np.mean([len(v) for v in string_values])) if string_values else 0.0
    word_count = float(np.mean([v.count(" ") + 1 for v in string_values])) if string_values else 0.0

    if _name_suggests_geo(lowered) or (lowered_values & _GEO_VALUE_HINTS and unique <= 60):
        return GEOGRAPHIC, 0.8, "", notes

    if unique <= max(50, int(total * 0.05)) and avg_len <= 60 and word_count <= 6:
        return CATEGORICAL, 0.85, "", notes
    if unique_ratio > 0.9 and avg_len > 25:
        return TEXT, 0.85, "", ["High-cardinality free text."]
    if unique <= 200 and avg_len <= 80:
        return CATEGORICAL, 0.6, "", ["High-cardinality categorical."]

    # A repeating id is a *foreign key*: it identifies an entity that lives in
    # another table. Without this branch it falls past every category test into
    # free text and drops out of the analysis entirely, taking every cross-sheet
    # relationship built on it with it.
    if (id_like_ratio > 0.8 or _name_suggests_id(lowered)) and unique > 1 and word_count <= 2:
        return IDENTIFIER, 0.75, "", [
            "Identifier values that repeat - a key referring to another table."
        ]
    return TEXT, 0.6, "", notes


def _name_suggests_id(lowered: str) -> bool:
    tokens = re.split(r"[^a-z0-9]+", lowered)
    return any(token in _ID_NAME_HINTS for token in tokens if token) or lowered.endswith("id")


def _name_suggests_measure(lowered: str) -> bool:
    tokens = set(re.split(r"[^a-z0-9]+", lowered))
    return any(hint in lowered for hint in _MEASURE_NAME_HINTS) or bool(tokens & set(_MEASURE_NAME_HINTS))


def _name_suggests_geo(lowered: str) -> bool:
    return any(hint in lowered for hint in _GEO_NAME_HINTS)


def _name_suggests_percentage(lowered: str) -> bool:
    return (
        "%" in lowered
        or "percent" in lowered
        or lowered.endswith(" pct")
        or "_pct" in lowered
        or lowered.startswith("pct ")
    )


def _name_suggests_date(lowered: str) -> bool:
    return any(hint in lowered for hint in _DATE_NAME_HINTS)


def _looks_like_year(numeric: pd.Series) -> bool:
    if numeric.empty:
        return False
    return bool(numeric.between(1900, 2100).mean() > 0.95)


_NON_ADDITIVE_HINTS = (
    "rate", "ratio", "score", "rating", "index", "average", "avg", "per ", "percent",
    "price", "age", "tenure", "duration", "temperature", "weight", "height", "level",
    "margin", "utilisation", "utilization", "attendance", "gpa", "cgpa", "share",
    "density", "probability", "median", "mean", "efficiency",
)


def default_aggregation(name: str, semantic_type: str) -> str:
    """Additive measures are summed; rates, scores and prices are averaged.

    Summing a rating or a percentage produces a number with no meaning, so the
    whole analytics stack asks this function before aggregating anything.
    """
    if semantic_type == PERCENTAGE:
        return "mean"
    lowered = str(name).lower()
    if "%" in lowered:
        return "mean"
    if any(hint in lowered for hint in _NON_ADDITIVE_HINTS):
        return "mean"
    return "sum"


def assign_role(profile: ColumnProfile, row_count: int) -> str:
    """Map a semantic type + distribution onto an analytical role."""
    stype = profile.semantic_type
    lowered = profile.name.lower()

    if stype in TEMPORAL_TYPES:
        return TIME_DIMENSION
    if stype == IDENTIFIER:
        return IDENTIFIER_ROLE
    if stype in {EMAIL, URL}:
        return IDENTIFIER_ROLE
    if stype == TEXT:
        return DESCRIPTIVE
    if stype in {CATEGORICAL, BOOLEAN, GEOGRAPHIC}:
        # A categorical with as many values as rows is really an identifier.
        if profile.unique_pct > 95 and row_count > 20:
            return IDENTIFIER_ROLE
        return DIMENSION
    if stype in NUMERIC_TYPES:
        if profile.is_constant:
            return DESCRIPTIVE
        # Unique integers that look like keys are identifiers, not measures.
        if stype == INTEGER and profile.unique_pct > 98 and row_count > 20 and _name_suggests_id(lowered):
            return IDENTIFIER_ROLE
        if stype == INTEGER and profile.unique <= 8 and not _name_suggests_measure(lowered) and row_count > 40:
            return DIMENSION
        return MEASURE
    return DESCRIPTIVE


def profile_dataframe(df: pd.DataFrame, sample_rows: int = 50_000) -> dict[str, Any]:
    """Profile every column of a dataframe."""
    row_count = int(len(df))
    working = df.sample(sample_rows, random_state=13) if row_count > sample_rows else df
    sampled = row_count > sample_rows

    profiles: list[ColumnProfile] = []
    for position, column in enumerate(df.columns):
        series = working[column]
        non_null = series.dropna()
        count = int(len(series))
        missing = int(series.isna().sum())
        unique = int(non_null.nunique())
        stype, confidence, symbol, notes = infer_semantic_type(series, column)

        profile = ColumnProfile(
            name=str(column),
            position=position,
            dtype=str(series.dtype),
            semantic_type=stype,
            role=DESCRIPTIVE,
            count=count,
            missing=missing,
            missing_pct=(missing / count * 100) if count else 0.0,
            unique=unique,
            unique_pct=(unique / max(count - missing, 1) * 100),
            is_constant=unique <= 1 and count > 0,
            currency_symbol=symbol,
            confidence=confidence,
            notes=list(notes),
        )
        profile.sample_values = [
            neutralize_text(v, 60) for v in non_null.head(5).tolist()
        ]

        if stype in NUMERIC_TYPES:
            numeric = to_numeric_series(series).dropna()
            if len(numeric):
                profile.numeric_stats = {
                    "min": float(numeric.min()),
                    "max": float(numeric.max()),
                    "mean": float(numeric.mean()),
                    "sum": float(numeric.sum()),
                }
                negatives = int((numeric < 0).sum())
                profile.non_negative = negatives / max(len(numeric), 1) < 0.01
                failed = int(series.notna().sum() - len(numeric))
                if failed > 0:
                    profile.notes.append(f"{failed} value(s) could not be converted to a number.")
        elif stype in TEMPORAL_TYPES and stype != TIME:
            parsed = to_datetime_series(series).dropna()
            if len(parsed):
                profile.temporal_stats = {
                    "min": parsed.min().isoformat(),
                    "max": parsed.max().isoformat(),
                    "span_days": int((parsed.max() - parsed.min()).days),
                }
                failed = int(series.notna().sum() - len(parsed))
                if failed > 0:
                    profile.notes.append(f"{failed} value(s) are not valid dates.")

        if stype in {CATEGORICAL, BOOLEAN, GEOGRAPHIC} and unique <= 500:
            counts = non_null.astype(str).value_counts().head(10)
            denominator = int(non_null.shape[0]) or 1
            profile.top_values = [
                {
                    "value": neutralize_text(index, 60),
                    "count": int(value),
                    "pct": round(int(value) / denominator * 100, 2),
                }
                for index, value in counts.items()
            ]

        profile.role = assign_role(profile, row_count)
        if profile.role == MEASURE:
            profile.aggregation = default_aggregation(profile.name, stype)
            profile.additive = profile.aggregation == "sum"
            if not profile.additive:
                profile.notes.append(
                    "Averaged rather than summed: totalling this column would not be meaningful."
                )
        profiles.append(profile)

    roles: dict[str, list[str]] = {
        MEASURE: [], DIMENSION: [], TIME_DIMENSION: [], IDENTIFIER_ROLE: [], DESCRIPTIVE: [],
    }
    for profile in profiles:
        roles[profile.role].append(profile.name)

    currency = next((p.currency_symbol for p in profiles if p.currency_symbol), "")

    return {
        "row_count": row_count,
        "column_count": int(df.shape[1]),
        "sampled": sampled,
        "sample_rows": int(len(working)),
        "columns": [p.to_dict() for p in profiles],
        "roles": roles,
        "currency_symbol": currency,
        "profiles": profiles,  # in-process only; stripped before serialisation
    }


def primary_time_column(profile: dict[str, Any]) -> str | None:
    """Pick the most useful time column: best coverage, widest span."""
    candidates = []
    for column in profile["columns"]:
        if column["role"] != TIME_DIMENSION or column["semantic_type"] == TIME:
            continue
        span = column.get("temporal_stats", {}).get("span_days", 0)
        coverage = 100 - column["missing_pct"]
        name_bonus = 15 if _name_suggests_date(column["name"].lower()) else 0
        candidates.append((coverage + name_bonus + min(span / 30, 40), column["name"]))
    if not candidates:
        return None
    return max(candidates)[1]


# --- user corrections -------------------------------------------------------

OVERRIDABLE_ROLES = {MEASURE, DIMENSION, TIME_DIMENSION, IDENTIFIER_ROLE, DESCRIPTIVE}
OVERRIDABLE_TYPES = {
    INTEGER, DECIMAL, CURRENCY, PERCENTAGE, DATE, DATETIME, CATEGORICAL, TEXT, BOOLEAN,
    IDENTIFIER, GEOGRAPHIC,
}
AGGREGATIONS = {"sum", "mean"}


def override_options(column: dict[str, Any], series: pd.Series | None = None) -> dict[str, Any]:
    """Which corrections are legitimate for one column, and which are not.

    Profiling is inference, and inference is sometimes wrong - but a text column
    cannot become a measure by being relabelled. The options offered here are
    the ones the *data* can actually support, so an override can never put the
    analytics engine in a state it cannot compute.
    """
    numeric_capable = bool(column.get("numeric_stats")) or (
        series is not None and to_numeric_series(series).notna().any()
    )
    temporal_capable = bool(column.get("temporal_stats")) or (
        series is not None and column["semantic_type"] not in NUMERIC_TYPES
        and to_datetime_series(series).notna().any()
    )

    roles = [DIMENSION, IDENTIFIER_ROLE, DESCRIPTIVE]
    if numeric_capable:
        roles.append(MEASURE)
    if temporal_capable:
        roles.append(TIME_DIMENSION)

    types = [CATEGORICAL, TEXT, IDENTIFIER, GEOGRAPHIC, BOOLEAN]
    if numeric_capable:
        types.extend([INTEGER, DECIMAL, CURRENCY, PERCENTAGE])
    if temporal_capable:
        types.extend([DATE, DATETIME])

    blocked = []
    if not numeric_capable:
        blocked.append(
            f"{column['name']} holds no values that can be read as numbers, so it cannot be "
            f"analysed as a measure."
        )
    if not temporal_capable:
        blocked.append(
            f"{column['name']} holds no values that can be read as dates, so it cannot be used "
            f"as the time axis."
        )
    return {
        "column": column["name"],
        "current": {
            "role": column["role"], "semantic_type": column["semantic_type"],
            "aggregation": column.get("aggregation"),
        },
        "roles": sorted(set(roles)),
        "semantic_types": sorted(set(types)),
        "aggregations": sorted(AGGREGATIONS) if MEASURE in roles else [],
        "blocked": blocked,
        "reason": (
            f"Detected as {column['semantic_type']} with "
            f"{column.get('confidence', 0) * 100:.0f}% confidence"
            if isinstance(column.get("confidence"), float) else ""
        ),
    }


def validate_overrides(
    overrides: dict[str, dict[str, Any]], profile: dict[str, Any],
    df: pd.DataFrame | None = None,
) -> list[str]:
    """Reject corrections the data cannot support, with a reason for each."""
    errors: list[str] = []
    columns = {c["name"]: c for c in profile["columns"]}
    for name, override in overrides.items():
        column = columns.get(name)
        if column is None:
            errors.append(f"'{name}' is not a column in this dataset.")
            continue
        if not isinstance(override, dict):
            errors.append(f"{name}: the correction must be an object.")
            continue
        options = override_options(column, df[name] if df is not None and name in df else None)
        role = override.get("role")
        if role is not None:
            if role not in OVERRIDABLE_ROLES:
                errors.append(f"{name}: '{role}' is not a role.")
            elif role not in options["roles"]:
                errors.append(
                    f"{name}: cannot be used as a {role} - "
                    + (options["blocked"][0] if options["blocked"] else "the values do not support it.")
                )
        semantic_type = override.get("semantic_type")
        if semantic_type is not None and semantic_type not in options["semantic_types"]:
            errors.append(f"{name}: '{semantic_type}' is not a valid type for these values.")
        aggregation = override.get("aggregation")
        if aggregation is not None and aggregation not in AGGREGATIONS:
            errors.append(f"{name}: aggregation must be one of {', '.join(sorted(AGGREGATIONS))}.")
    return errors


def apply_overrides(
    profile: dict[str, Any], overrides: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Fold user corrections into a profile, in place, and rebuild the role index.

    Applied immediately after profiling and before any engine reads the profile,
    so a correction propagates through KPI selection, aggregation, charting and
    narration without any of them needing to know overrides exist.
    """
    if not overrides:
        return profile
    changed = False
    for column in profile["columns"]:
        override = overrides.get(column["name"])
        if not isinstance(override, dict):
            continue
        applied: list[str] = []
        if override.get("semantic_type") and override["semantic_type"] != column["semantic_type"]:
            column["semantic_type"] = override["semantic_type"]
            applied.append("type")
        if override.get("role") and override["role"] != column["role"]:
            column["role"] = override["role"]
            applied.append("role")
        if column["role"] == MEASURE:
            aggregation = override.get("aggregation") or column.get("aggregation") or \
                default_aggregation(column["name"], column["semantic_type"])
            if aggregation != column.get("aggregation"):
                applied.append("aggregation")
            column["aggregation"] = aggregation
            column["additive"] = aggregation == "sum"
        else:
            # Matches how the profiler serialises a non-measure: an empty
            # string, never None, so consumers see one shape.
            column["aggregation"] = ""
            column["additive"] = False
        if applied:
            changed = True
            column["overridden"] = applied
            column["confidence"] = 1.0
            column["notes"] = [
                n for n in column.get("notes", [])
                if "Averaged rather than summed" not in n
            ] + [f"Classification corrected by a user ({', '.join(applied)})."]
            if column["role"] == MEASURE and not column["additive"]:
                column["notes"].append(
                    "Averaged rather than summed: totalling this column would not be meaningful."
                )

    if changed:
        roles: dict[str, list[str]] = {
            MEASURE: [], DIMENSION: [], TIME_DIMENSION: [], IDENTIFIER_ROLE: [], DESCRIPTIVE: [],
        }
        for column in profile["columns"]:
            roles.setdefault(column["role"], []).append(column["name"])
        profile["roles"] = roles
        profile["overrides_applied"] = sorted(
            c["name"] for c in profile["columns"] if c.get("overridden")
        )
    return profile


def mark_attribute_columns(
    profile: dict[str, Any], names: list[str] | None,
) -> set[str]:
    """Flag columns whose values are repeated across rows by a join.

    Totalling a customer's credit limit over their orders measures how many
    orders they placed. Such columns stay measures - an *average* credit limit
    by country is a real statistic - but they are never summed, and the caller
    keeps them out of anything time-based.
    """
    if not names:
        return set()
    flagged = set(names)
    present: set[str] = set()
    for column in profile["columns"]:
        if column["name"] not in flagged:
            continue
        present.add(column["name"])
        column["repeated_attribute"] = True
        if column["role"] == MEASURE and not column.get("overridden"):
            column["aggregation"] = "mean"
            column["additive"] = False
            column["notes"] = list(column.get("notes", [])) + [
                "Joined from a lookup table, so this value repeats on every matching row. "
                "It is averaged rather than summed and excluded from trends: a total would "
                "measure how often the record appears, not the value itself."
            ]
    profile["attribute_columns"] = sorted(present)
    return present
