"""Data-generating process for known-truth validation."""
import numpy as np
import pandas as pd
from scipy.special import expit

from .models import TruthConfig, RecoveryReport, AdjustmentMethod
from .estimator import estimate_effect, _iptw_ate, _gcomp_ate, _naive_ate


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


def recover_known_truth(config: TruthConfig, n: int, seed: int) -> RecoveryReport:
    treated, control = generate_cohort(config, n, seed)

    treated_c = treated.copy()
    control_c = control.copy()
    treated_c["treatment"] = 1
    control_c["treatment"] = 0
    df = pd.concat([treated_c, control_c], ignore_index=True)

    naive = _naive_ate(df)
    iptw = _iptw_ate(df)
    gcomp = _gcomp_ate(df)

    from .estimator import _bootstrap_ci
    iptw_ci = _bootstrap_ci(_iptw_ate, df, n_resamples=500, seed=seed)
    gcomp_ci = _bootstrap_ci(_gcomp_ate, df, n_resamples=500, seed=seed)

    true_ate = config.true_ate

    return RecoveryReport(
        config=config,
        n=n,
        seed=seed,
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
    )
