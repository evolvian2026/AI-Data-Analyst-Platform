"""Forward projection of a measured series.

A projection is not a measurement, and this module is written so the rest of
the platform can never confuse the two:

* every projected point carries ``projected: True`` and a prediction interval;
* projections live in their own structure, never inside ``trends[*].points``,
  so nothing that sums or averages the measured series can pick them up;
* a projection is produced **only** when the fitted model earns it. A noisy,
  short or structurally unsuitable series returns ``None`` with a stated
  reason rather than a confident-looking line.

Two methods are used, both fitted to the aggregated series the trend engine
already built:

``linear_trend``     ordinary least squares extrapolation.
``level``            when there is no significant trend: the recent mean is
                     carried forward flat. Saying "about the same" is an honest
                     forecast; extrapolating noise is not.
``seasonal_trend``   /
``seasonal_level``   either of the above plus additive month-of-year (or
                     quarter) offsets, estimated only when two full cycles are
                     available *and* they measurably reduce residual variance.

Trend and seasonality are estimated independently, because a series can be
strongly seasonal with no trend at all - which is what a year of retail data
usually looks like.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from app.engines.formatting import format_value, safe_float
from app.engines.trend import FREQ_LABELS, _label

# A projection needs enough history to estimate both a slope and its error.
MIN_PERIODS = 8
# Never project further than a quarter of the observed history, capped hard.
MAX_HORIZON = 6
HORIZON_FRACTION = 0.25
# Beyond this coefficient of variation the series is noise, not a signal.
MAX_VOLATILITY_PCT = 75.0
INTERVAL_PCT = 90

_STEP = {"D": pd.DateOffset(days=1), "W": pd.DateOffset(weeks=1),
         "MS": pd.DateOffset(months=1), "QS": pd.DateOffset(months=3),
         "YS": pd.DateOffset(years=1)}

_CYCLE_LENGTH = {"MS": 12, "QS": 4}


def _reason(text: str) -> dict[str, Any]:
    return {"available": False, "reason": text}


def build_forecast(
    points: list[dict[str, Any]],
    freq: str,
    *,
    measure: str = "",
    aggregation: str = "sum",
    semantic_type: str = "",
    currency: str = "",
    non_negative: bool = True,
    horizon: int | None = None,
) -> dict[str, Any]:
    """Project a measured series forward, or explain why it cannot be projected.

    ``points`` is the trend engine's own list of measured periods, so a forecast
    is always anchored to exactly the values the rest of the analysis reports.
    """
    unit = FREQ_LABELS.get(freq, "period")
    if len(points) < MIN_PERIODS:
        return _reason(
            f"A projection needs at least {MIN_PERIODS} complete {unit}s of history; "
            f"this series has {len(points)}."
        )

    values = np.array([float(p["value"]) for p in points], dtype=float)
    if not np.isfinite(values).all():
        return _reason("The series contains values that cannot be modelled.")

    mean_value = float(np.mean(values))
    if mean_value == 0:
        return _reason("The series averages zero, so a proportional projection is undefined.")
    volatility = float(np.std(values, ddof=1) / abs(mean_value) * 100)
    if volatility > MAX_VOLATILITY_PCT:
        return _reason(
            f"{measure or 'This series'} varies by {volatility:.0f}% around its own average. "
            f"A projection from a series this volatile would be a guess presented as a number."
        )

    n = len(values)
    x = np.arange(n, dtype=float)
    fit = scipy_stats.linregress(x, values)
    r_squared = float(fit.rvalue ** 2)
    p_value = float(fit.pvalue)
    significant = p_value < 0.05 and r_squared >= 0.25

    cycle = _CYCLE_LENGTH.get(freq, 0)
    offsets: dict[int, float] = {}

    # The trend and the seasonal pattern are estimated independently, because a
    # series can be strongly seasonal with no trend at all - which is exactly
    # what a year of retail data looks like.
    if significant:
        trend_component = fit.intercept + fit.slope * x
    else:
        window = min(n, max(4, cycle or 4))
        trend_component = np.full(n, float(np.mean(values[-window:])))

    # A seasonal term costs ``cycle - 1`` parameters, and with only two cycles of
    # history it can absorb half the residual variance purely by fitting noise -
    # so it is kept only when an F-test says it explains more than that costs.
    trend_params = 2 if significant else 1
    if cycle and n >= cycle * 2 + trend_params + 2:
        detrended = values - trend_component
        candidate = {
            position: float(np.mean(detrended[position::cycle]))
            for position in range(cycle)
            if len(detrended[position::cycle]) >= 2
        }
        if len(candidate) == cycle:
            seasonal_fit = np.array([candidate[i % cycle] for i in range(n)])
            rss_reduced = float(np.sum(detrended ** 2))
            rss_full = float(np.sum((detrended - seasonal_fit) ** 2))
            extra_params = cycle - 1
            residual_df = n - trend_params - extra_params
            if rss_full > 0 and residual_df > 0 and rss_reduced > rss_full:
                f_statistic = ((rss_reduced - rss_full) / extra_params) / (rss_full / residual_df)
                if scipy_stats.f.sf(f_statistic, extra_params, residual_df) < 0.05:
                    offsets = candidate

    seasonal = (
        np.array([offsets.get(i % cycle, 0.0) for i in range(n)]) if offsets else np.zeros(n)
    )
    baseline = trend_component + seasonal
    method = (
        ("seasonal_trend" if offsets else "linear_trend") if significant
        else ("seasonal_level" if offsets else "level")
    )

    residuals = values - baseline
    degrees = max(n - (2 if significant else 1) - (len(offsets) if offsets else 0), 1)
    residual_std = float(np.sqrt(np.sum(residuals ** 2) / degrees))
    t_value = float(scipy_stats.t.ppf(0.5 + INTERVAL_PCT / 200, degrees))

    steps = horizon or max(1, min(MAX_HORIZON, int(n * HORIZON_FRACTION)))
    step = _STEP.get(freq, pd.DateOffset(months=1))
    last_period = pd.Timestamp(points[-1]["iso"])
    x_mean = float(np.mean(x))
    sxx = float(np.sum((x - x_mean) ** 2)) or 1.0

    projected: list[dict[str, Any]] = []
    for offset in range(1, steps + 1):
        index = n - 1 + offset
        if significant:
            centre = float(fit.intercept + fit.slope * index)
            spread = residual_std * np.sqrt(1 + 1 / n + (index - x_mean) ** 2 / sxx)
        else:
            centre = float(trend_component[-1])
            spread = residual_std * np.sqrt(1 + 1 / n)
        if offsets:
            centre += offsets.get(index % cycle, 0.0)
        margin = t_value * float(spread)
        lower = centre - margin
        if non_negative:
            centre = max(centre, 0.0)
            lower = max(lower, 0.0)
        period = last_period
        for _ in range(offset):
            period = period + step
        projected.append({
            "label": _label(period, freq),
            "iso": period.isoformat(),
            "value": safe_float(centre),
            "lower": safe_float(lower),
            "upper": safe_float(centre + margin),
            "formatted": format_value(safe_float(centre), semantic_type, currency),
            "formatted_range": (
                f"{format_value(safe_float(lower), semantic_type, currency)} to "
                f"{format_value(safe_float(centre + margin), semantic_type, currency)}"
            ),
            "projected": True,
            "step": offset,
        })

    width = float(np.mean([p["upper"] - p["lower"] for p in projected]))
    relative_width = width / abs(mean_value) * 100 if mean_value else 999.0
    if relative_width > 150:
        return _reason(
            f"The {INTERVAL_PCT}% prediction interval for {measure or 'this series'} spans more "
            f"than 1.5x its own average, so the projection would carry no usable information."
        )

    confidence = (
        "high" if significant and r_squared >= 0.6 and relative_width <= 40
        else "medium" if relative_width <= 80
        else "low"
    )

    caveats = [
        "Projected values are model output, not measurements. They assume the pattern in the "
        "measured history continues unchanged.",
    ]
    if not significant:
        caveats.append(
            f"No statistically significant trend was found (p = {p_value:.2f}), so the recent "
            f"level is carried forward rather than a slope extrapolated."
        )
    if offsets:
        caveats.append(
            f"A repeating {unit}-of-{'year' if cycle == 12 else 'cycle'} pattern was estimated "
            f"from {n // cycle} complete cycle(s) and added to the projection."
        )
    elif cycle and cycle <= n < cycle * 2:
        caveats.append(
            f"This series may repeat annually, but {n} {unit}s is less than the two full cycles "
            f"needed to estimate a seasonal pattern. The projection ignores seasonality, which is "
            f"part of why its interval is wide."
        )
    if volatility > 30:
        caveats.append(
            f"The measured series varies by {volatility:.0f}% around its average, which is why the "
            f"interval is wide."
        )
    if steps == MAX_HORIZON:
        caveats.append(
            f"The horizon is capped at {MAX_HORIZON} {unit}s; accuracy degrades with distance."
        )

    label = {"linear_trend": "Linear trend extrapolation",
             "seasonal_trend": "Seasonal trend extrapolation",
             "level": "Recent level carried forward",
             "seasonal_level": "Recent level with a seasonal pattern"}[method]

    return {
        "available": True,
        "measure": measure,
        "aggregation": aggregation,
        "aggregation_label": "Total" if aggregation == "sum" else "Average",
        "method": method,
        "method_label": label,
        "unit": unit,
        "frequency": freq,
        "horizon": steps,
        "interval_pct": INTERVAL_PCT,
        "confidence": confidence,
        "measured_periods": n,
        "last_measured_period": points[-1]["label"],
        "last_measured_value": safe_float(values[-1]),
        "r_squared": safe_float(r_squared),
        "p_value": safe_float(p_value),
        "slope_per_period": safe_float(fit.slope) if significant else 0.0,
        "seasonal": bool(offsets),
        "residual_std": safe_float(residual_std),
        "volatility_pct": safe_float(volatility),
        "interval_width_pct_of_mean": safe_float(relative_width),
        "points": projected,
        "basis": (
            f"{label} fitted to {n} measured {unit}s of "
            f"{'total' if aggregation == 'sum' else 'average'} {measure}"
            f"{f' (R2 = {r_squared:.2f})' if significant else ''}."
        ),
        "caveats": caveats,
        "disclaimer": (
            "Projection - not a measured value. Shown with a "
            f"{INTERVAL_PCT}% prediction interval."
        ),
    }


def forecast_trends(
    trends: list[dict[str, Any]], profile: dict[str, Any], max_measures: int = 3,
) -> list[dict[str, Any]]:
    """Project the leading measures, keeping the unavailable ones and their reasons."""
    currency = profile.get("currency_symbol", "")
    columns = {c["name"]: c for c in profile["columns"]}
    results: list[dict[str, Any]] = []
    for trend in trends[:max_measures]:
        column = columns.get(trend["measure"], {})
        forecast = build_forecast(
            trend["points"], trend["frequency"],
            measure=trend["measure"],
            aggregation=trend.get("aggregation", "sum"),
            semantic_type=column.get("semantic_type", ""),
            currency=currency,
            non_negative=bool(column.get("non_negative", True)),
        )
        forecast["measure"] = trend["measure"]
        forecast["time_column"] = trend["time_column"]
        results.append(forecast)
    return results
