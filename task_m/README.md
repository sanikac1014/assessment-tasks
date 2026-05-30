# Task M — Counterfactual Treatment-Effect Comparator

Estimates a treatment-effect contrast between two locked synthetic cohorts. Demonstrates correct causal estimation under confounding by comparing naive and adjusted methods against a known injected truth.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
from treatment_effect import (
    AdjustmentMethod, TruthConfig,
    estimate_effect, recover_known_truth, generate_cohort,
)

# generate cohorts from a known data-generating process
config = TruthConfig(true_ate=2.0, confounder_effect_on_treatment=1.5,
                     confounder_effect_on_outcome=2.0, base_outcome=5.0,
                     noise_std=1.0, seed=42)
treated, control = generate_cohort(config, n=2000, seed=42)

# naive estimate (biased under confounding)
naive = estimate_effect(treated, control, AdjustmentMethod.NAIVE, seed=0)
print(naive.ate, naive.ci_lower, naive.ci_upper)

# adjusted estimates
iptw  = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=0)
gcomp = estimate_effect(treated, control, AdjustmentMethod.GCOMPUTATION, seed=0)

# full recovery report with bias diagnostics
report = recover_known_truth(config, n=2000, seed=42)
print(report.naive_bias, report.iptw_bias, report.gcomp_bias)
```

## Run Tests

```bash
pytest -v
```

---

## Adjustment Methods

### Naive difference-in-means
The simplest estimator: subtract the mean outcome of control from the mean outcome of treated. Requires no modelling but **assumes no confounding**. When a covariate C influences both treatment assignment and the outcome, the naive estimate absorbs C's effect on the outcome and is biased. This estimator is provided as a baseline to make the bias visible.

### IPTW — Inverse Probability of Treatment Weighting
Fits a logistic regression model to estimate each unit's propensity to receive treatment given their covariates: P(T=1|X). Treated units are weighted by 1/P(T=1|X) and control units by 1/P(T=0|X), creating a pseudo-population where treatment assignment is independent of covariates. The weighted difference-in-means then estimates the average treatment effect.

**Assumption:** positivity — every unit must have P(T=1|X) strictly between 0 and 1. The module checks this before estimating and returns a `PositivityViolation` if the propensity scores are too extreme, rather than silently producing an unstable estimate.

### G-computation (outcome regression)
Fits a linear regression model for the outcome using both covariates and the treatment indicator as inputs. Then predicts each unit's potential outcome under treatment (T=1) and under control (T=0) using the fitted model. The ATE is the mean difference between those two potential-outcome predictions.

**Assumption:** correct model specification for the outcome regression. Does not require positivity, so it works even when propensity scores are extreme.

### Uncertainty
All three methods include a bootstrap confidence interval (default 1000 resamples, configurable). Coverage of the true ATE is verified in the test suite: both IPTW and G-computation achieve ≥90% coverage across 30 simulated datasets at n=2000.

---

## Data-Generating Process

The DGP uses a single confounder C drawn from N(0,1):

```
P(T=1 | C) = sigmoid(β_T × C)        # C → T
Y = base + ATE × T + β_Y × C + ε     # C → Y, T → Y
```

Setting β_T and β_Y both non-zero creates genuine confounding: C influences who receives treatment AND what the outcome is, so a naive comparison of treated vs. control conflates the treatment effect with C's effect on Y. The adjusted estimators recover the true ATE by controlling for C.
