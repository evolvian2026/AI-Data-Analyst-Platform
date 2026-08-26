"""Compare two analyses of the same dataset: what changed since last time.

Re-uploading last month's workbook with this month's rows is the single most
common thing a real analyst does, and "what moved?" is the question they ask
first. This engine answers it by diffing two stored analysis results.

It only ever compares like with like. Every comparison is keyed on something
structural - a KPI key, a (dimension, measure) pair, a group name, an insight
signature - so a metric that exists in one dataset and not the other is
reported as *added* or *removed*, never silently matched to something else.

Percentage change is delegated to :func:`app.engines.trend.pct_change`, which
returns ``None`` for a non-positive baseline, so nothing here can report the
"declined 860%" class of nonsense.
"""
from __future__ import annotations

from typing import Any

from app.engines.formatting import format_value, safe_float
from app.engines.trend import pct_change

# Below this, a movement is noise rather than news.
MATERIAL_PCT = 2.0
MAX_ITEMS = 12


def dataset_signature(result: dict[str, Any]) -> str:
    """A stable fingerprint of a dataset's shape, used to find comparable runs.

    Two analyses are comparable when they describe the same columns playing the
    same analytical roles - not when they happen to have the same row count.
    """
    columns = sorted(
        f"{c['name']}:{c['role']}" for c in result.get("profile", {}).get("columns", [])
    )
    return "|".join(columns)


def signature_overlap(left: str, right: str) -> float:
    """How much two dataset signatures share, 0-100."""
    a, b = set(left.split("|")), set(right.split("|"))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b) * 100


def _fmt(value: float | None, semantic: str, currency: str) -> str:
    return format_value(value, semantic, currency) if value is not None else "n/a"


def _direction(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "unchanged"
    return "up" if delta > 0 else "down"


# --- individual diffs -------------------------------------------------------

def _compare_schema(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = {c["name"]: c for c in previous.get("profile", {}).get("columns", [])}
    after = {c["name"]: c for c in current.get("profile", {}).get("columns", [])}
    reclassified = []
    for name in set(before) & set(after):
        changes = []
        for field, label in (("role", "role"), ("semantic_type", "type"),
                             ("aggregation", "aggregation")):
            if before[name].get(field) != after[name].get(field):
                changes.append(
                    f"{label} {before[name].get(field) or 'none'} -> {after[name].get(field) or 'none'}"
                )
        if changes:
            reclassified.append({"column": name, "changes": changes})
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "reclassified": reclassified[:MAX_ITEMS],
        "identical": not (set(after) ^ set(before)) and not reclassified,
    }


def _compare_coverage(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before_rows = int(previous.get("profile", {}).get("row_count", 0))
    after_rows = int(current.get("profile", {}).get("row_count", 0))

    def _range(result: dict[str, Any]) -> tuple[str, str]:
        time_column = result.get("time_column")
        for column in result.get("profile", {}).get("columns", []):
            if column["name"] == time_column:
                stats = column.get("temporal_stats") or {}
                return stats.get("min", ""), stats.get("max", "")
        return "", ""

    before_min, before_max = _range(previous)
    after_min, after_max = _range(current)
    return {
        "rows_before": before_rows,
        "rows_after": after_rows,
        "rows_delta": after_rows - before_rows,
        "rows_change_pct": pct_change(float(after_rows), float(before_rows)),
        "period_before": {"from": before_min, "to": before_max},
        "period_after": {"from": after_min, "to": after_max},
        "extends_period": bool(after_max and before_max and after_max > before_max),
        "time_column": current.get("time_column"),
    }


def _compare_quality(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = previous.get("quality", {})
    after = current.get("quality", {})
    before_score = safe_float(before.get("score"))
    after_score = safe_float(after.get("score"))
    before_issues = {i["id"]: i for i in before.get("issues", [])}
    after_issues = {i["id"]: i for i in after.get("issues", [])}
    delta = (
        round(after_score - before_score, 1)
        if before_score is not None and after_score is not None else None
    )
    return {
        "score_before": before_score,
        "score_after": after_score,
        "score_delta": delta,
        "grade_before": before.get("grade", ""),
        "grade_after": after.get("grade", ""),
        "direction": _direction(delta),
        "resolved": [
            {"id": i["id"], "title": i["title"], "severity": i["severity"]}
            for key, i in before_issues.items() if key not in after_issues
        ][:MAX_ITEMS],
        "introduced": [
            {"id": i["id"], "title": i["title"], "severity": i["severity"]}
            for key, i in after_issues.items() if key not in before_issues
        ][:MAX_ITEMS],
        "persisting": len(set(before_issues) & set(after_issues)),
    }


def _compare_kpis(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    before = {k["key"]: k for k in previous.get("kpis", {}).get("all", [])}
    after = {k["key"]: k for k in current.get("kpis", {}).get("all", [])}
    primary = {k["key"] for k in current.get("kpis", {}).get("primary", [])}
    currency = current.get("profile", {}).get("currency_symbol", "")

    rows: list[dict[str, Any]] = []
    for key, kpi in after.items():
        semantic = kpi.get("semantic_type", "")
        old = before.get(key)
        if old is None:
            rows.append({
                "key": key, "label": kpi["label"], "status": "new",
                "value_before": None, "value_after": safe_float(kpi.get("value")),
                "formatted_before": "n/a", "formatted_after": kpi.get("formatted", ""),
                "delta": None, "change_pct": None, "direction": "new",
                "aggregation": kpi.get("aggregation", ""),
                "is_primary": key in primary, "material": True,
                "note": "Not present in the earlier analysis.",
            })
            continue
        # Comparing a total against a total only makes sense when both runs
        # aggregated the same way.
        if old.get("aggregation") != kpi.get("aggregation"):
            rows.append({
                "key": key, "label": kpi["label"], "status": "incomparable",
                "value_before": safe_float(old.get("value")),
                "value_after": safe_float(kpi.get("value")),
                "formatted_before": old.get("formatted", ""),
                "formatted_after": kpi.get("formatted", ""),
                "delta": None, "change_pct": None, "direction": "unchanged",
                "aggregation": kpi.get("aggregation", ""),
                "is_primary": key in primary, "material": False,
                "note": (
                    f"Aggregation changed from {old.get('aggregation')} to "
                    f"{kpi.get('aggregation')}, so the two values are not comparable."
                ),
            })
            continue
        old_value, new_value = safe_float(old.get("value")), safe_float(kpi.get("value"))
        delta = (
            round(new_value - old_value, 4)
            if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float))
            else None
        )
        change_pct = pct_change(new_value, old_value)
        rows.append({
            "key": key, "label": kpi["label"], "status": "changed",
            "value_before": old_value, "value_after": new_value,
            "formatted_before": old.get("formatted", ""),
            "formatted_after": kpi.get("formatted", ""),
            "delta": delta,
            "formatted_delta": _fmt(delta, semantic, currency) if delta is not None else "",
            "change_pct": round(change_pct, 1) if change_pct is not None else None,
            "direction": _direction(delta),
            "aggregation": kpi.get("aggregation", ""),
            "is_primary": key in primary,
            "material": bool(change_pct is not None and abs(change_pct) >= MATERIAL_PCT),
            "note": (
                "" if change_pct is not None
                else "The earlier value is zero or negative, so a percentage change is undefined; "
                     "the absolute movement is shown instead."
            ),
        })

    removed = [
        {"key": key, "label": kpi["label"], "status": "removed",
         "value_before": safe_float(kpi.get("value")), "value_after": None,
         "formatted_before": kpi.get("formatted", ""), "formatted_after": "n/a",
         "delta": None, "change_pct": None, "direction": "removed",
         "aggregation": kpi.get("aggregation", ""), "is_primary": False, "material": True,
         "note": "This metric could not be calculated from the newer dataset."}
        for key, kpi in before.items() if key not in after
    ]

    rows.sort(key=lambda r: (
        not r["is_primary"],
        -abs(r["change_pct"] or 0),
    ))
    return (rows + removed)[:20]


def _compare_segments(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    before = {(s["dimension"], s["measure"]): s for s in previous.get("segments", [])}
    after = {(s["dimension"], s["measure"]): s for s in current.get("segments", [])}
    currency = current.get("profile", {}).get("currency_symbol", "")

    results: list[dict[str, Any]] = []
    for key, segment in after.items():
        old = before.get(key)
        if old is None or old.get("aggregation") != segment.get("aggregation"):
            continue
        semantic = segment.get("semantic_type", "")
        old_groups = {g["group"]: g for g in old.get("groups", [])}
        old_rank = {g["group"]: i + 1 for i, g in enumerate(old.get("groups", []))}
        moves: list[dict[str, Any]] = []
        for index, group in enumerate(segment.get("groups", [])):
            name = group["group"]
            previous_group = old_groups.get(name)
            if previous_group is None:
                moves.append({
                    "group": name, "status": "new", "rank_before": None, "rank_after": index + 1,
                    "value_before": None, "value_after": safe_float(group["value"]),
                    "formatted_before": "n/a", "formatted_after": group.get("formatted_value", ""),
                    "share_before": None, "share_after": group.get("share_pct"),
                    "share_delta": None, "change_pct": None,
                })
                continue
            share_delta = (
                round((group.get("share_pct") or 0) - (previous_group.get("share_pct") or 0), 1)
                if segment.get("shares_valid", True) else None
            )
            change = pct_change(safe_float(group["value"]), safe_float(previous_group["value"]))
            moves.append({
                "group": name, "status": "changed",
                "rank_before": old_rank.get(name), "rank_after": index + 1,
                "rank_delta": (old_rank[name] - (index + 1)) if name in old_rank else None,
                "value_before": safe_float(previous_group["value"]),
                "value_after": safe_float(group["value"]),
                "formatted_before": previous_group.get("formatted_value", ""),
                "formatted_after": group.get("formatted_value", ""),
                "share_before": previous_group.get("share_pct"),
                "share_after": group.get("share_pct"),
                "share_delta": share_delta,
                "change_pct": round(change, 1) if change is not None else None,
            })
        gone = [
            {"group": name, "status": "removed", "rank_before": old_rank.get(name),
             "rank_after": None, "value_before": safe_float(g["value"]), "value_after": None,
             "formatted_before": g.get("formatted_value", ""), "formatted_after": "n/a",
             "share_before": g.get("share_pct"), "share_after": None,
             "share_delta": None, "change_pct": None}
            for name, g in old_groups.items()
            if name not in {g["group"] for g in segment.get("groups", [])}
        ]
        moves.sort(key=lambda m: -abs(m.get("share_delta") or m.get("change_pct") or 0))
        leader_changed = (
            old.get("best", {}).get("group") != segment.get("best", {}).get("group")
            if old.get("best") and segment.get("best") else False
        )
        results.append({
            "dimension": segment["dimension"],
            "measure": segment["measure"],
            "aggregation_label": segment.get("aggregation_label", "Total"),
            "shares_valid": segment.get("shares_valid", True),
            "leader_before": (old.get("best") or {}).get("group"),
            "leader_after": (segment.get("best") or {}).get("group"),
            "leader_changed": leader_changed,
            "groups": (moves + gone)[:MAX_ITEMS],
            "narrative": (
                f"{segment['dimension']} leadership on {segment['measure']} passed from "
                f"{(old.get('best') or {}).get('group')} to "
                f"{(segment.get('best') or {}).get('group')}."
                if leader_changed else
                f"{(segment.get('best') or {}).get('group')} remains the largest "
                f"{segment['dimension']} by {segment['measure']}."
            ),
            "currency_symbol": currency,
            "semantic_type": semantic,
        })
    results.sort(key=lambda r: (not r["leader_changed"],))
    return results[:6]


def _compare_concentration(previous: dict[str, Any],
                           current: dict[str, Any]) -> list[dict[str, Any]]:
    before = {(c["dimension"], c["measure"]): c for c in previous.get("concentration", [])}
    rows = []
    for concentration in current.get("concentration", []):
        old = before.get((concentration["dimension"], concentration["measure"]))
        if old is None:
            continue
        delta = round(concentration["top1_pct"] - old["top1_pct"], 1)
        rows.append({
            "dimension": concentration["dimension"],
            "measure": concentration["measure"],
            "top1_before": old["top1_pct"], "top1_after": concentration["top1_pct"],
            "top1_delta": delta,
            "top_group_before": old.get("top_group"),
            "top_group_after": concentration.get("top_group"),
            "risk_before": bool(old.get("is_risk")),
            "risk_after": bool(concentration.get("is_risk")),
            "became_risk": bool(concentration.get("is_risk")) and not bool(old.get("is_risk")),
            "cleared_risk": bool(old.get("is_risk")) and not bool(concentration.get("is_risk")),
            "direction": _direction(delta),
        })
    rows.sort(key=lambda r: -abs(r["top1_delta"]))
    return rows[:6]


def _compare_trends(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    before = {t["measure"]: t for t in previous.get("trends", [])}
    rows = []
    for trend in current.get("trends", []):
        old = before.get(trend["measure"])
        if old is None:
            continue
        old_direction = old.get("classification", {}).get("direction", "")
        new_direction = trend.get("classification", {}).get("direction", "")
        rows.append({
            "measure": trend["measure"],
            "direction_before": old_direction,
            "direction_after": new_direction,
            "reversed": bool(
                {old_direction, new_direction} == {"increasing", "decreasing"}
            ),
            "changed": old_direction != new_direction,
            "confidence_after": trend.get("classification", {}).get("confidence", ""),
            "slope_pct_before": old.get("classification", {}).get("slope_pct_per_period"),
            "slope_pct_after": trend.get("classification", {}).get("slope_pct_per_period"),
            "narrative": (
                f"{trend['measure']} was {old_direction} and is now {new_direction}."
                if old_direction != new_direction
                else f"{trend['measure']} remains {new_direction}."
            ),
        })
    rows.sort(key=lambda r: (not r["reversed"], not r["changed"]))
    return rows[:6]


def _insight_signature(insight: dict[str, Any]) -> str:
    """Identify a *finding*, not a wording, so rephrasing is not "a new insight"."""
    evidence = insight.get("evidence") or {}
    columns = "+".join(sorted(str(c) for c in evidence.get("source_columns", [])))
    return f"{insight.get('type')}:{insight.get('subject', '')}:{columns}"


def _compare_insights(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = {_insight_signature(i): i for i in previous.get("insights", [])}
    after = {_insight_signature(i): i for i in current.get("insights", [])}

    def _slim(insight: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": insight.get("id"), "type": insight.get("type"),
            "type_label": insight.get("type_label"), "headline": insight.get("headline"),
            "confidence": insight.get("confidence"),
            "priority": (insight.get("priority") or {}).get("score"),
        }

    persisting = []
    for key in set(before) & set(after):
        new, old = after[key], before[key]
        persisting.append({
            **_slim(new),
            "priority_before": (old.get("priority") or {}).get("score"),
            "headline_before": old.get("headline"),
        })
    persisting.sort(key=lambda i: -(i.get("priority") or 0))

    new_items = sorted(
        (_slim(after[k]) for k in set(after) - set(before)),
        key=lambda i: -(i.get("priority") or 0),
    )
    resolved = sorted(
        (_slim(before[k]) for k in set(before) - set(after)),
        key=lambda i: -(i.get("priority") or 0),
    )
    return {
        "new": new_items[:MAX_ITEMS],
        "resolved": resolved[:MAX_ITEMS],
        "persisting": persisting[:MAX_ITEMS],
        "counts": {"new": len(new_items), "resolved": len(resolved),
                   "persisting": len(persisting)},
    }


# --- headline ---------------------------------------------------------------

def _headline(coverage: dict[str, Any], kpis: list[dict[str, Any]], quality: dict[str, Any],
              segments: list[dict[str, Any]], insights: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if coverage["rows_delta"]:
        change = coverage["rows_change_pct"]
        lines.append(
            f"The newer dataset holds {coverage['rows_after']:,} records, "
            f"{abs(coverage['rows_delta']):,} "
            f"{'more' if coverage['rows_delta'] > 0 else 'fewer'} than before"
            + (f" ({change:+.1f}%)." if change is not None else ".")
        )
    else:
        lines.append(f"Both datasets hold {coverage['rows_after']:,} records.")

    movers = [k for k in kpis if k["material"] and k["status"] == "changed"][:3]
    for kpi in movers:
        lines.append(
            f"{kpi['label']} moved from {kpi['formatted_before']} to {kpi['formatted_after']}"
            + (f" ({kpi['change_pct']:+.1f}%)." if kpi["change_pct"] is not None else ".")
        )
    if not movers and kpis:
        lines.append(
            f"No headline metric moved by more than {MATERIAL_PCT:.0f}%."
        )

    if quality["score_delta"]:
        lines.append(
            f"Data quality {'improved' if quality['score_delta'] > 0 else 'fell'} "
            f"{abs(quality['score_delta']):.1f} points to {quality['score_after']:.0f}/100 "
            f"({quality['grade_after']})."
        )
    for segment in segments:
        if segment["leader_changed"]:
            lines.append(segment["narrative"])
            break
    counts = insights["counts"]
    if counts["new"] or counts["resolved"]:
        lines.append(
            f"{counts['new']} finding(s) appeared and {counts['resolved']} no longer hold; "
            f"{counts['persisting']} carried over."
        )
    return lines


def compare_analyses(
    previous: dict[str, Any], current: dict[str, Any],
    previous_label: str = "Earlier analysis", current_label: str = "This analysis",
) -> dict[str, Any]:
    """Diff two completed analysis results."""
    schema = _compare_schema(previous, current)
    coverage = _compare_coverage(previous, current)
    quality = _compare_quality(previous, current)
    kpis = _compare_kpis(previous, current)
    segments = _compare_segments(previous, current)
    concentration = _compare_concentration(previous, current)
    trends = _compare_trends(previous, current)
    insights = _compare_insights(previous, current)

    overlap = signature_overlap(dataset_signature(previous), dataset_signature(current))
    caveats: list[str] = []
    if schema["added"]:
        caveats.append(
            f"{len(schema['added'])} column(s) exist only in the newer dataset "
            f"({', '.join(schema['added'][:4])}), so metrics built on them have no baseline."
        )
    if schema["removed"]:
        caveats.append(
            f"{len(schema['removed'])} column(s) were present before and are now missing "
            f"({', '.join(schema['removed'][:4])})."
        )
    if schema["reclassified"]:
        caveats.append(
            f"{len(schema['reclassified'])} column(s) are classified differently in the two runs, "
            f"which changes how they are aggregated."
        )
    if coverage["extends_period"]:
        caveats.append(
            "The newer dataset covers a longer period, so totals are expected to be larger; "
            "compare rates and shares rather than totals."
        )
    if overlap < 100:
        caveats.append(
            f"The two datasets share {overlap:.0f}% of their column definitions. "
            f"Only shared metrics are compared."
        )

    return {
        "comparable_pct": round(overlap, 1),
        "previous_label": previous_label,
        "current_label": current_label,
        "headline": _headline(coverage, kpis, quality, segments, insights),
        "schema": schema,
        "coverage": coverage,
        "quality": quality,
        "kpis": kpis,
        "segments": segments,
        "concentration": concentration,
        "trends": trends,
        "insights": insights,
        "caveats": caveats,
        "method": (
            "Metrics are matched by their calculation key, segments by (dimension, measure), "
            "and findings by what they are about rather than by their wording. Anything that "
            "exists in only one of the two analyses is reported as added or removed rather than "
            "compared."
        ),
    }
