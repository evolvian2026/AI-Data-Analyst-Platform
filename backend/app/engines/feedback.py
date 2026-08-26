"""Learning which findings a user actually values.

Insight ranking is calculated from six statistical components. That ordering is
right in general and wrong for individuals: an operations manager does not care
about the data-quality findings a data steward lives for.

This module lets a "useful" / "not useful" vote nudge the *order*, under three
hard constraints:

* **It moves ranking only.** No number, headline, evidence value or confidence
  level is ever touched by feedback. A downvoted finding is still true.
* **It is bounded.** The adjustment is capped well below the range of the
  statistical score, so a large, unusual, high-confidence finding cannot be
  voted off the front page.
* **It is explainable.** Every adjusted insight carries the adjustment and the
  reason for it, and the API reports the votes it was derived from.

Feedback is keyed on what a finding is *about*, not on its id, so a vote
survives re-analysis and carries across datasets with the same shape.
"""
from __future__ import annotations

import math
from typing import Any

# Cap on the adjustment, against a statistical score whose components total 100.
MAX_ADJUSTMENT = 8.0
# A vote on the whole category of finding is weaker evidence than a vote on a
# specific subject, so it moves the score less.
MAX_TYPE_ADJUSTMENT = 4.0
# Votes needed before the adjustment reaches roughly 75% of its cap.
SATURATION = 3.0

UP, DOWN = "useful", "not_useful"
VOTES = {UP: 1, DOWN: -1}


def signature(insight: dict[str, Any]) -> str:
    """What this finding is about: its type and its subject."""
    subject = insight.get("subject") or ""
    if not subject:
        evidence = insight.get("evidence") or {}
        subject = "+".join(sorted(str(c) for c in evidence.get("source_columns", [])))
    return f"{insight.get('type', '')}::{subject}"


def _curve(net: int, cap: float) -> float:
    """Diminishing returns: the tenth vote must not outweigh the statistics."""
    return round(cap * math.tanh(net / SATURATION), 2)


def build_adjustments(votes: list[tuple[str, str, str]]) -> dict[str, Any]:
    """Turn raw votes into bounded adjustments.

    ``votes`` is a list of ``(signature, insight_type, vote)``.
    """
    by_signature: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for sig, insight_type, vote in votes:
        weight = VOTES.get(vote, 0)
        if not weight:
            continue
        by_signature[sig] = by_signature.get(sig, 0) + weight
        by_type[insight_type] = by_type.get(insight_type, 0) + weight

    return {
        "signatures": {k: _curve(v, MAX_ADJUSTMENT) for k, v in by_signature.items() if v},
        "types": {k: _curve(v, MAX_TYPE_ADJUSTMENT) for k, v in by_type.items() if v},
        "vote_counts": {
            "total": len(votes),
            "useful": sum(1 for _, _, v in votes if v == UP),
            "not_useful": sum(1 for _, _, v in votes if v == DOWN),
        },
        "net_by_signature": by_signature,
        "net_by_type": by_type,
    }


def apply(
    insights: list[dict[str, Any]], adjustments: dict[str, Any] | None,
    voted: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Re-order insights by their adjusted score, leaving every value untouched.

    Returns new list items (shallow copies with a new ``priority``) so the
    stored analysis result is never mutated by serving it.
    """
    if not adjustments or not (adjustments.get("signatures") or adjustments.get("types")):
        return insights

    signatures = adjustments.get("signatures", {})
    types = adjustments.get("types", {})
    voted = voted or {}
    adjusted: list[dict[str, Any]] = []
    for insight in insights:
        sig = signature(insight)
        specific = float(signatures.get(sig, 0.0))
        general = float(types.get(insight.get("type", ""), 0.0))
        # A vote on this exact subject supersedes the broader category vote
        # rather than stacking with it.
        delta = specific if specific else general
        priority = dict(insight.get("priority") or {})
        base = float(priority.get("score", 0.0))
        priority["score_before_feedback"] = base
        priority["feedback_adjustment"] = round(delta, 2)
        priority["score"] = round(max(base + delta, 0.0), 1)
        priority["feedback_reason"] = (
            ""
            if not delta else
            f"Ranked {'higher' if delta > 0 else 'lower'} because you marked findings about "
            f"{insight.get('subject') or 'this'} as "
            f"{'useful' if delta > 0 else 'not useful'}."
            if specific else
            f"Ranked {'higher' if delta > 0 else 'lower'} because you have marked "
            f"{insight.get('type_label', insight.get('type', ''))} findings as "
            f"{'useful' if delta > 0 else 'not useful'}."
        )
        adjusted.append({**insight, "priority": priority, "your_vote": voted.get(insight.get("id", ""), "")})

    adjusted.sort(key=lambda i: -(i.get("priority") or {}).get("score", 0.0))
    return adjusted


def explain(adjustments: dict[str, Any] | None) -> dict[str, Any]:
    """A user-readable statement of how their feedback is being used."""
    counts = (adjustments or {}).get("vote_counts", {"total": 0, "useful": 0, "not_useful": 0})
    return {
        "votes": counts,
        "max_adjustment": MAX_ADJUSTMENT,
        "active": bool((adjustments or {}).get("signatures") or (adjustments or {}).get("types")),
        "statement": (
            f"Your {counts['total']} rating(s) move findings up or down the list by at most "
            f"{MAX_ADJUSTMENT:.0f} points on a 100-point priority score. Ratings change the order "
            f"only - never a calculated value, a confidence level or whether a finding is shown "
            f"in a report."
            if counts["total"] else
            "Rate a finding useful or not useful and the ordering adapts. Ratings change the "
            "order only - never a calculated value."
        ),
    }
