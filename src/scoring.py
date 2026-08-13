"""Stage D: business-viability scoring. These are *signals*, not hard
filters -- feed into a hot/warm/cold ranking rather than rejecting leads
(the one hard filter here, phone validity, is applied separately by the
pipeline since an unusable lead should be dropped regardless of score).
"""
from __future__ import annotations

HOT = "hot"
WARM = "warm"
COLD = "cold"


def score_lead(niche: str, niche_weights: dict, rating: float | None, review_count: int | None, max_niche_weight: int = 30) -> float:
    niche_weight = niche_weights.get(niche, niche_weights.get("other", 5))
    niche_signal = (niche_weight / max_niche_weight) * 100

    review_signal = (min(review_count, 50) / 50 * 100) if review_count else 0
    rating_signal = (rating / 5 * 100) if rating else 0

    score = niche_signal * 0.40 + review_signal * 0.35 + rating_signal * 0.25
    return round(score, 2)


def score_tier(score_value: float, hot_threshold: float, warm_threshold: float) -> str:
    if score_value >= hot_threshold:
        return HOT
    if score_value >= warm_threshold:
        return WARM
    return COLD
