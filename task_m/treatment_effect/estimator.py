import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, LinearRegression
from typing import Union

from .models import (
    AdjustmentMethod,
    EffectEstimate,
    PositivityViolation,
    OverlapDiagnostic,
)

_POSITIVITY_THRESHOLD = 0.05  # default min overlap


def _fit_propensity(X: np.ndarray, T: np.ndarray) -> np.ndarray:
    model = LogisticRegression(max_iter=1000, random_state=0)
    model.fit(X, T)
    return model.predict_proba(X)[:, 1]


def _overlap_diagnostic(
    ps_treated: np.ndarray,
    ps_control: np.ndarray,
    threshold: float = _POSITIVITY_THRESHOLD,
) -> OverlapDiagnostic:
    # Positivity: every unit must have PS in [threshold, 1-threshold].
    # Near-zero PS for a treated unit or near-one PS for a control unit both violate this.
    all_ps = np.concatenate([ps_treated, ps_control])
    ok = float(all_ps.min()) >= threshold and float(all_ps.max()) <= (1 - threshold)
    return OverlapDiagnostic(
        min_propensity_treated=float(ps_treated.min()),
        max_propensity_control=float(ps_control.max()),
        overlap_ok=ok,
    )


def _bootstrap_ci(
    func,
    data: pd.DataFrame,
    n_resamples: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(n_resamples):
        idx = rng.integers(0, len(data), size=len(data))
        sample = data.iloc[idx].reset_index(drop=True)
        try:
            est = func(sample)
            estimates.append(est)
        except Exception:
            pass
    estimates = np.array(estimates)
    return float(np.percentile(estimates, 2.5)), float(np.percentile(estimates, 97.5))


def _naive_ate(df: pd.DataFrame) -> float:
    return float(df.loc[df["treatment"] == 1, "outcome"].mean() - df.loc[df["treatment"] == 0, "outcome"].mean())


def _iptw_ate(df: pd.DataFrame) -> float:
    X = df[[c for c in df.columns if c.startswith("X")]].values
    T = df["treatment"].values
    Y = df["outcome"].values
    ps = _fit_propensity(X, T)
    ps = np.clip(ps, 0.01, 0.99)
    weights = np.where(T == 1, 1.0 / ps, 1.0 / (1.0 - ps))
    treated_weighted = np.sum(weights * T * Y) / np.sum(weights * T)
    control_weighted = np.sum(weights * (1 - T) * Y) / np.sum(weights * (1 - T))
    return float(treated_weighted - control_weighted)


def _gcomp_ate(df: pd.DataFrame) -> float:
    feature_cols = [c for c in df.columns if c.startswith("X")]
    X_cols = feature_cols + ["treatment"]
    X = df[X_cols].values
    Y = df["outcome"].values
    model = LinearRegression()
    model.fit(X, Y)

    df_t1 = df[feature_cols].copy()
    df_t1["treatment"] = 1
    df_t0 = df[feature_cols].copy()
    df_t0["treatment"] = 0

    y1 = model.predict(df_t1[X_cols].values)
    y0 = model.predict(df_t0[X_cols].values)
    return float((y1 - y0).mean())


def estimate_effect(
    treated: pd.DataFrame,
    control: pd.DataFrame,
    adjustment: AdjustmentMethod,
    seed: int = 0,
    n_bootstrap: int = 1000,
    positivity_threshold: float = _POSITIVITY_THRESHOLD,
) -> Union[EffectEstimate, PositivityViolation]:
    treated = treated.copy()
    control = control.copy()
    treated["treatment"] = 1
    control["treatment"] = 0
    df = pd.concat([treated, control], ignore_index=True)

    feature_cols = [c for c in df.columns if c.startswith("X")]

    if adjustment == AdjustmentMethod.NAIVE:
        ate = _naive_ate(df)
        ci_lo, ci_hi = _bootstrap_ci(_naive_ate, df, n_bootstrap, seed)
        return EffectEstimate(
            method=adjustment, ate=ate, ci_lower=ci_lo, ci_upper=ci_hi,
            n_treated=len(treated), n_control=len(control),
        )

    if adjustment == AdjustmentMethod.GCOMPUTATION:
        ate = _gcomp_ate(df)
        ci_lo, ci_hi = _bootstrap_ci(_gcomp_ate, df, n_bootstrap, seed)
        return EffectEstimate(
            method=adjustment, ate=ate, ci_lower=ci_lo, ci_upper=ci_hi,
            n_treated=len(treated), n_control=len(control),
        )

    # IPTW: check propensity overlap first; refuse if positivity is violated
    X = df[feature_cols].values
    T = df["treatment"].values
    ps = _fit_propensity(X, T)
    overlap = _overlap_diagnostic(ps[T == 1], ps[T == 0], positivity_threshold)

    if not overlap.overlap_ok:
        return PositivityViolation(
            method=adjustment,
            min_overlap=float(np.concatenate([ps[T == 1], ps[T == 0]]).min()),
            threshold=positivity_threshold,
            message=f"Propensity overlap too low for {adjustment.value}; refusing to estimate.",
        )

    ate = _iptw_ate(df)
    ci_lo, ci_hi = _bootstrap_ci(_iptw_ate, df, n_bootstrap, seed)

    return EffectEstimate(
        method=adjustment, ate=ate, ci_lower=ci_lo, ci_upper=ci_hi,
        n_treated=len(treated), n_control=len(control),
    )
