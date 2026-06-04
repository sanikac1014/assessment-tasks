# Task L — Evidence-Grade Scoring Engine

Assigns a calibrated evidence-grade tier to a body of scientific evidence. The scoring rubric lives entirely in `rubric.yaml` — no code changes needed to adjust weights or thresholds.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
from pathlib import Path
from evidence_scorer import EvidenceItem, StudyDesign, BiasRisk, Rubric, score, explain

rubric = Rubric.from_yaml(Path("rubric.yaml"))

items = [
    EvidenceItem(
        study_design=StudyDesign.RCT,
        sample_size=500,
        replication_count=3,
        effect_size=0.6,
        ci_width=0.08,
        preregistered=True,
        risk_of_bias_tier=BiasRisk.LOW,
    )
]

grade = score(items, rubric)
print(grade.tier, grade.score)

breakdown = explain(items, rubric)
for c in breakdown.contributions:
    print(c.dimension, c.contribution)
```

## Run Tests

```bash
pytest -v
```

---

## Contribution Breakdown

`explain()` returns a per-dimension breakdown showing why a body of evidence landed in its tier. Each `DimensionContribution.contribution` is the weighted score for that dimension. The contributions always sum to the final reported score within floating-point tolerance — including when the raw total is clamped to the [0, 1] range, in which case a `clamp_adjustment` term is included in the breakdown to account for the delta.

---

## Rubric Knobs (`rubric.yaml`)

| Key | What it does |
|---|---|
| `design_base_scores` | Base quality score (0–1) per study design |
| `replication_bonus.per_replication` | Score added per independent replication |
| `replication_bonus.cap` | Maximum cumulative replication bonus |
| `sample_size_scale` | Sigmoid midpoint — n at this value scores 0.5 |
| `sample_size_weight` | Scale factor for the sample-size sigmoid output |
| `effect_size_weight` | Scale factor for effect size contribution |
| `ci_width_penalty_weight` | How much a wide CI hurts the score |
| `preregistered_bonus` | Flat bonus added if the study was preregistered |
| `bias_penalties` | Score deducted per bias tier (LOW/MODERATE/HIGH) |
| `weights` | Per-dimension final weights (must sum to 1.0) |
| `tier_thresholds` | Minimum score required to reach each tier |

## Three Worked Examples

### Example 1 — SPECULATIVE
Expert opinion, n=10, no preregistration, high bias → score ≈ 0.04 → **SPECULATIVE**

### Example 2 — SUPPORTED
Prospective cohort, n=300, 2 replications, moderate bias → score ≈ 0.45 → **SUPPORTED**

### Example 3 — WELL_REPLICATED
Meta-analysis of 5 RCTs, n=2000, 8 replications, low bias, preregistered → score ≈ 0.82 → **CONSENSUS**
