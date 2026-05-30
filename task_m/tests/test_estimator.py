import numpy as np
import pandas as pd
import pytest

from treatment_effect import (
    AdjustmentMethod,
    EffectEstimate,
    PositivityViolation,
    TruthConfig,
    estimate_effect,
    recover_known_truth,
    generate_cohort,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

CONFOUNDED_CONFIG = TruthConfig(
    true_ate=2.0,
    confounder_effect_on_treatment=2.0,   # strong confounding
    confounder_effect_on_outcome=3.0,
    base_outcome=5.0,
    noise_std=1.0,
    seed=42,
)

MILD_CONFIG = TruthConfig(
    true_ate=1.0,
    confounder_effect_on_treatment=0.5,
    confounder_effect_on_outcome=0.5,
    base_outcome=0.0,
    noise_std=0.5,
    seed=0,
)


@pytest.fixture(scope="module")
def confounded_cohort():
    return generate_cohort(CONFOUNDED_CONFIG, n=2000, seed=42)


@pytest.fixture(scope="module")
def mild_cohort():
    return generate_cohort(MILD_CONFIG, n=2000, seed=0)


# ── basic interface ───────────────────────────────────────────────────────────

def test_naive_returns_effect_estimate(confounded_cohort):
    treated, control = confounded_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.NAIVE, seed=0)
    assert isinstance(result, EffectEstimate)


def test_iptw_returns_effect_estimate(mild_cohort):
    treated, control = mild_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=0)
    assert isinstance(result, EffectEstimate)


def test_gcomp_returns_effect_estimate(mild_cohort):
    treated, control = mild_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.GCOMPUTATION, seed=0)
    assert isinstance(result, EffectEstimate)


def test_estimate_has_valid_ci(mild_cohort):
    treated, control = mild_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=0)
    assert isinstance(result, EffectEstimate)
    assert result.ci_lower <= result.ate <= result.ci_upper


def test_sample_counts_correct(confounded_cohort):
    treated, control = confounded_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.NAIVE, seed=0)
    assert isinstance(result, EffectEstimate)
    assert result.n_treated == len(treated)
    assert result.n_control == len(control)


# ── known-truth recovery ──────────────────────────────────────────────────────

def test_iptw_recovers_true_ate(mild_cohort):
    treated, control = mild_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=0, n_bootstrap=200)
    assert isinstance(result, EffectEstimate)
    assert abs(result.ate - MILD_CONFIG.true_ate) < 0.3


def test_gcomp_recovers_true_ate(mild_cohort):
    treated, control = mild_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.GCOMPUTATION, seed=0, n_bootstrap=200)
    assert isinstance(result, EffectEstimate)
    assert abs(result.ate - MILD_CONFIG.true_ate) < 0.3


def test_recovery_report_iptw(mild_cohort):
    report = recover_known_truth(MILD_CONFIG, n=2000, seed=0)
    assert report.iptw_bias < report.naive_bias or report.iptw_bias < 0.5


def test_recovery_report_gcomp(mild_cohort):
    report = recover_known_truth(MILD_CONFIG, n=2000, seed=0)
    assert report.gcomp_bias < report.naive_bias or report.gcomp_bias < 0.5


# ── confounding bias demonstration ───────────────────────────────────────────

def test_naive_is_biased_under_strong_confounding(confounded_cohort):
    treated, control = confounded_cohort
    naive = estimate_effect(treated, control, AdjustmentMethod.NAIVE, seed=0)
    assert isinstance(naive, EffectEstimate)
    # naive should be significantly off from true ATE of 2.0
    assert abs(naive.ate - CONFOUNDED_CONFIG.true_ate) > 0.5


def test_adjusted_less_biased_than_naive(confounded_cohort):
    treated, control = confounded_cohort
    naive = estimate_effect(treated, control, AdjustmentMethod.NAIVE, seed=0)
    gcomp = estimate_effect(treated, control, AdjustmentMethod.GCOMPUTATION, seed=0, n_bootstrap=200)
    assert isinstance(naive, EffectEstimate)
    assert isinstance(gcomp, EffectEstimate)
    naive_bias = abs(naive.ate - CONFOUNDED_CONFIG.true_ate)
    gcomp_bias = abs(gcomp.ate - CONFOUNDED_CONFIG.true_ate)
    assert gcomp_bias < naive_bias


# ── positivity violation ──────────────────────────────────────────────────────

def test_positivity_violation_returned_not_raised():
    # Create cohorts where all treated have very high propensity → no overlap
    n = 200
    rng = np.random.default_rng(99)
    # treated: all have confounder = +10 (near certain treatment)
    treated = pd.DataFrame({"X0": rng.normal(10, 0.1, n)})
    # control: all have confounder = -10 (near certain control)
    control = pd.DataFrame({"X0": rng.normal(-10, 0.1, n)})

    result = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=0, positivity_threshold=0.1)
    assert isinstance(result, PositivityViolation)


def test_positivity_violation_has_correct_method():
    n = 100
    rng = np.random.default_rng(7)
    treated = pd.DataFrame({"X0": rng.normal(8, 0.1, n)})
    control = pd.DataFrame({"X0": rng.normal(-8, 0.1, n)})
    result = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=0, positivity_threshold=0.1)
    assert isinstance(result, PositivityViolation)
    assert result.method == AdjustmentMethod.IPTW


def test_positivity_not_triggered_with_good_overlap(mild_cohort):
    treated, control = mild_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.IPTW, seed=0)
    assert isinstance(result, EffectEstimate)


# ── reproducibility ───────────────────────────────────────────────────────────

def test_same_seed_same_report():
    r1 = recover_known_truth(MILD_CONFIG, n=500, seed=7)
    r2 = recover_known_truth(MILD_CONFIG, n=500, seed=7)
    assert r1.naive_ate == r2.naive_ate
    assert r1.iptw_ate == r2.iptw_ate
    assert r1.gcomp_ate == r2.gcomp_ate


def test_different_seed_different_report():
    r1 = recover_known_truth(MILD_CONFIG, n=500, seed=1)
    r2 = recover_known_truth(MILD_CONFIG, n=500, seed=2)
    assert r1.naive_ate != r2.naive_ate


# ── bootstrap coverage check ─────────────────────────────────────────────────

def test_bootstrap_coverage_iptw():
    """IPTW CI should cover the true ATE in most repeated simulations."""
    config = MILD_CONFIG
    covered = 0
    runs = 30
    for seed in range(runs):
        report = recover_known_truth(config, n=2000, seed=seed)
        if report.iptw_covers_truth:
            covered += 1
    coverage = covered / runs
    assert coverage >= 0.80, f"IPTW coverage too low: {coverage:.2f}"


def test_bootstrap_coverage_gcomp():
    config = MILD_CONFIG
    covered = 0
    runs = 30
    for seed in range(runs):
        report = recover_known_truth(config, n=2000, seed=seed)
        if report.gcomp_covers_truth:
            covered += 1
    coverage = covered / runs
    assert coverage >= 0.80, f"G-comp coverage too low: {coverage:.2f}"


def test_naive_bias_larger_with_stronger_confounding():
    weak = TruthConfig(true_ate=1.0, confounder_effect_on_treatment=0.1, confounder_effect_on_outcome=0.1, base_outcome=0.0, noise_std=0.5, seed=1)
    strong = TruthConfig(true_ate=1.0, confounder_effect_on_treatment=3.0, confounder_effect_on_outcome=3.0, base_outcome=0.0, noise_std=0.5, seed=1)
    r_weak = recover_known_truth(weak, n=2000, seed=1)
    r_strong = recover_known_truth(strong, n=2000, seed=1)
    assert r_strong.naive_bias > r_weak.naive_bias


def test_gcomp_ci_brackets_ate(mild_cohort):
    treated, control = mild_cohort
    result = estimate_effect(treated, control, AdjustmentMethod.GCOMPUTATION, seed=0, n_bootstrap=200)
    assert isinstance(result, EffectEstimate)
    assert result.ci_lower <= result.ate <= result.ci_upper
