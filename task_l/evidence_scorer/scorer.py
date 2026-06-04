import math
from .models import (
    EvidenceItem,
    EvidenceGrade,
    GradeExplanation,
    GradeTier,
    BiasRisk,
    DimensionContribution,
)
from .rubric import Rubric

_TIER_ORDER = [
    GradeTier.SPECULATIVE,
    GradeTier.EMERGING,
    GradeTier.SUPPORTED,
    GradeTier.WELL_REPLICATED,
    GradeTier.CONSENSUS,
]


def _sigmoid(x: float, midpoint: float) -> float:
    return 1.0 / (1.0 + math.exp(-(x - midpoint) / (midpoint * 0.5 + 1)))


def _score_item(item: EvidenceItem, rubric: Rubric) -> dict[str, float]:
    design_score = rubric.design_base_scores.get(item.study_design.value, 0.0)

    rep_bonus = min(
        item.replication_count * rubric.replication_bonus["per_replication"],
        rubric.replication_bonus["cap"],
    )

    sample_score = _sigmoid(item.sample_size, rubric.sample_size_scale)

    effect_score = min(abs(item.effect_size), 1.0)

    ci_penalty = min(item.ci_width * rubric.ci_width_penalty_weight, 1.0)

    preregistered_bonus = rubric.preregistered_bonus if item.preregistered else 0.0

    bias_penalty = rubric.bias_penalties.get(item.risk_of_bias_tier.value, 0.0)

    return {
        "design": design_score + rep_bonus,
        "sample_size": sample_score * rubric.sample_size_weight,
        "effect": effect_score * rubric.effect_size_weight,
        "ci_penalty": -(ci_penalty),
        "preregistered": preregistered_bonus,
        "bias_penalty": -(bias_penalty),
    }


def _aggregate(items: list[EvidenceItem], rubric: Rubric) -> tuple[float, list[dict], dict[str, float]]:
    if not items:
        return 0.0, [], {k: 0.0 for k in rubric.weights}

    per_item = [_score_item(item, rubric) for item in items]

    # average raw contributions across items
    dim_totals: dict[str, float] = {}
    for breakdown in per_item:
        for dim, val in breakdown.items():
            dim_totals[dim] = dim_totals.get(dim, 0.0) + val
    avg = {dim: total / len(items) for dim, total in dim_totals.items()}

    # map raw dimensions to weighted dimensions
    weighted: dict[str, float] = {
        "design": avg["design"] * rubric.weights.get("design", 0.0),
        "sample_size": avg["sample_size"] * rubric.weights.get("sample_size", 0.0),
        "effect": avg["effect"] * rubric.weights.get("effect", 0.0),
        "ci_penalty": avg["ci_penalty"] * rubric.weights.get("ci_penalty", 0.0),
        "preregistered": avg["preregistered"] * rubric.weights.get("preregistered", 0.0),
        "bias_penalty": avg["bias_penalty"] * rubric.weights.get("bias_penalty", 0.0),
    }

    raw_score = sum(weighted.values())
    final_score = max(0.0, min(1.0, raw_score))

    # ensure contributions sum to the clamped score, not the raw total
    clamp_delta = final_score - raw_score
    if abs(clamp_delta) > 1e-9:
        weighted["clamp_adjustment"] = clamp_delta

    return final_score, per_item, weighted


def _tier_for_score(score: float, rubric: Rubric) -> tuple[GradeTier, float]:
    thresholds = rubric.tier_thresholds
    tier = GradeTier.SPECULATIVE
    threshold_used = 0.0
    for t in _TIER_ORDER:
        cutoff = thresholds.get(t.value, 0.0)
        if score >= cutoff:
            tier = t
            threshold_used = cutoff
    return tier, threshold_used


def score(evidence: list[EvidenceItem], rubric: Rubric) -> EvidenceGrade:
    final_score, _, _ = _aggregate(evidence, rubric)
    tier, threshold = _tier_for_score(final_score, rubric)
    return EvidenceGrade(tier=tier, score=final_score, threshold_used=threshold)


def explain(evidence: list[EvidenceItem], rubric: Rubric) -> GradeExplanation:
    final_score, per_item, weighted = _aggregate(evidence, rubric)
    tier, _ = _tier_for_score(final_score, rubric)

    contributions = [
        DimensionContribution(dimension=dim, contribution=val)
        for dim, val in weighted.items()
    ]

    return GradeExplanation(
        tier=tier,
        score=final_score,
        contributions=contributions,
        item_breakdowns=per_item,
    )
