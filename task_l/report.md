# Task L — Worked Examples

Three evidence bodies landing in three different tiers, with per-dimension contribution breakdowns.

---

## Example 1 — SPECULATIVE (score = 0.0000)

**Input:** single expert-opinion study, n=8, 0 replications, effect size=0.05, CI width=0.9, not preregistered, high bias

| Dimension | Contribution |
|---|---|
| design | +0.0175 |
| sample_size | +0.0260 |
| effect | +0.0075 |
| ci_penalty | **−0.0450** |
| preregistered | +0.0000 |
| bias_penalty | **−0.0300** |
| **Total (clamped to 0)** | **0.0000** |

The CI-width penalty and high-bias penalty together pull the raw score below zero, which is clamped to 0.0. Expert opinion has the lowest design base score (0.05), and the tiny sample and absence of preregistration add almost nothing. Verdict: **SPECULATIVE** (threshold 0.0).

---

## Example 2 — SUPPORTED (score = 0.4681)

**Input:** prospective cohort, n=350, 2 replications, effect size=0.4, CI width=0.15, not preregistered, moderate bias

| Dimension | Contribution |
|---|---|
| design | +0.2625 |
| sample_size | +0.1631 |
| effect | +0.0600 |
| ci_penalty | −0.0075 |
| preregistered | +0.0000 |
| bias_penalty | −0.0100 |
| **Total** | **0.4681** |

Prospective cohort gets a solid design base (0.65), the modest sample size is enough to clear the sigmoid midpoint, and the replications add a small bonus. The moderate-bias penalty is minor. Score clears the SUPPORTED threshold (0.35) comfortably. Verdict: **SUPPORTED**.

---

## Example 3 — CONSENSUS (score = 0.7567)

**Input:** two studies — a meta-analysis (n=8000, 15 reps, effect=0.9, CI=0.01, preregistered, low bias) and an RCT (n=3000, 5 reps, effect=0.8, CI=0.02, preregistered, low bias)

| Dimension | Contribution |
|---|---|
| design | +0.4200 |
| sample_size | +0.2000 |
| effect | +0.1275 |
| ci_penalty | −0.0008 |
| preregistered | +0.0100 |
| bias_penalty | +0.0000 |
| **Total** | **0.7567** |

Meta-analysis base score (1.0) plus replication bonus (capped at 0.30) drives the design dimension to its maximum. Both studies have large samples saturating the sigmoid. The narrow CI produces essentially no penalty. Preregistration adds the 0.10 bonus scaled by its weight. Score clears the CONSENSUS threshold (0.73). Verdict: **CONSENSUS**.

---

## Notes

- Contributions are weighted dimension averages: `raw_contribution × dimension_weight`
- Negative contributions (ci_penalty, bias_penalty) are scaled by their weights and subtracted
- Final score is clamped to [0, 1] after summing all contributions
- All thresholds and weights are defined in `rubric.yaml` — no code changes needed to retune
