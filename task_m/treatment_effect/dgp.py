"""Data-generating process for known-truth validation."""
import numpy as np
import pandas as pd
from scipy.special import expit

from .models import TruthConfig, RecoveryReport, AdjustmentMethod, PositivityViolation
from .estimator import estimate_effect


def generate_cohort(config: TruthConfig, n: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    DGP: a single confounder C affects both treatment assignment and outcome.

    Treatment assignment: P(T=1 | C) = sigmoid(config.confounder_effect_on_treatment * C)
    Outcome: Y = config.base_outcome + config.true_ate * T + config.confounder_effect_on_outcome * C + noise

    Confounding is present because C -> T and C -> Y simultaneously.
    """
    rng = np.random.default_rng(seed)
    C = rng.standard_normal(n)

    treatment_prob = expit(config.confounder_effect_on_treatment * C)
    T = rng.binomial(1, treatment_prob).astype(float)

    noise = rng.normal(0, config.noise_std, n)
    Y = config.base_outcome + config.true_ate * T + config.confounder_effect_on_outcome * C + noise

    df = pd.DataFrame({"X0": C, "treatment": T, "outcome": Y})
    treated = df[df["treatment"] == 1].drop(columns=["treatment", "outcome"]).reset_index(drop=True)
    treated["outcome"] = Y[df["treatment"] == 1]
    control = df[df["treatment"] == 0].drop(columns=["treatment", "outcome"]).reset_index(drop=True)
    control["outcome"] = Y[df["treatment"] == 0]

    return treated, control


def recover_known_truth(config: TruthConfig, n: int, seed: int, n_bootstrap: int = 500) -> RecoveryReport:
    treated, control = generate_cohort(config, n, seed)

    naive_result = estimate_effect(treated, control, AdjustmentMethod.NAIVE, seed=seed, n_bootstrap=n_bootstrap)
    iptw_result = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=seed, n_bootstrap=n_bootstrap)
    gcomp_result = estimate_effect(treated, control, AdjustmentMethod.GCOMPUTATION, seed=seed, n_bootstrap=n_bootstrap)

    true_ate = config.true_ate
    naive = naive_result.ate
    gcomp = gcomp_result.ate
    gcomp_ci = (gcomp_result.ci_lower, gcomp_result.ci_upper)

    if isinstance(iptw_result, PositivityViolation):
        return RecoveryReport(
            config=config, n=n, seed=seed,
            naive_ate=naive,
            iptw_ate=None,
            gcomp_ate=gcomp,
            true_ate=true_ate,
            naive_bias=abs(naive - true_ate),
            iptw_bias=None,
            gcomp_bias=abs(gcomp - true_ate),
            iptw_ci=None,
            gcomp_ci=gcomp_ci,
            iptw_covers_truth=None,
            gcomp_covers_truth=gcomp_ci[0] <= true_ate <= gcomp_ci[1],
            iptw_positivity_ok=False,
        )

    iptw = iptw_result.ate
    iptw_ci = (iptw_result.ci_lower, iptw_result.ci_upper)

    return RecoveryReport(
        config=config, n=n, seed=seed,
        naive_ate=naive,
        iptw_ate=iptw,
        gcomp_ate=gcomp,
        true_ate=true_ate,
        naive_bias=abs(naive - true_ate),
        iptw_bias=abs(iptw - true_ate),
        gcomp_bias=abs(gcomp - true_ate),
        iptw_ci=iptw_ci,
        gcomp_ci=gcomp_ci,
        iptw_covers_truth=iptw_ci[0] <= true_ate <= iptw_ci[1],
        gcomp_covers_truth=gcomp_ci[0] <= true_ate <= gcomp_ci[1],
        iptw_positivity_ok=True,
    )
