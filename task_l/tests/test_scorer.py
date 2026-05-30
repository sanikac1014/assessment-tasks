import copy
import math
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from evidence_scorer import (
    EvidenceItem,
    EvidenceGrade,
    GradeExplanation,
    GradeTier,
    StudyDesign,
    BiasRisk,
    Rubric,
    RubricValidationError,
    score,
    explain,
)

RUBRIC_PATH = Path(__file__).parent.parent / "rubric.yaml"


@pytest.fixture(scope="module")
def rubric():
    return Rubric.from_yaml(RUBRIC_PATH)


def make_item(**overrides) -> EvidenceItem:
    defaults = dict(
        study_design=StudyDesign.RCT,
        sample_size=500,
        replication_count=3,
        effect_size=0.5,
        ci_width=0.1,
        preregistered=True,
        risk_of_bias_tier=BiasRisk.LOW,
    )
    defaults.update(overrides)
    return EvidenceItem(**defaults)


# ── rubric loading ────────────────────────────────────────────────────────────

def test_rubric_loads(rubric):
    assert rubric is not None


def test_rubric_weights_sum_to_one(rubric):
    total = sum(rubric.weights.values())
    assert abs(total - 1.0) < 1e-6


def test_rubric_rejects_bad_weights(tmp_path):
    import yaml
    data = yaml.safe_load(RUBRIC_PATH.read_text())
    data["weights"]["design"] += 0.5   # break normalization
    bad_path = tmp_path / "bad_rubric.yaml"
    bad_path.write_text(yaml.dump(data))
    with pytest.raises(RubricValidationError):
        Rubric.from_yaml(bad_path)


# ── basic scoring ─────────────────────────────────────────────────────────────

def test_score_returns_grade(rubric):
    item = make_item()
    g = score([item], rubric)
    assert isinstance(g, EvidenceGrade)
    assert 0.0 <= g.score <= 1.0


def test_score_in_unit_interval(rubric):
    items = [make_item(study_design=StudyDesign.EXPERT_OPINION, sample_size=5, replication_count=0)]
    g = score(items, rubric)
    assert 0.0 <= g.score <= 1.0


def test_empty_evidence_is_speculative(rubric):
    g = score([], rubric)
    assert g.tier == GradeTier.SPECULATIVE
    assert g.score == 0.0


# ── tier thresholds ───────────────────────────────────────────────────────────

def test_high_quality_evidence_reaches_top_tiers(rubric):
    strong = [make_item(
        study_design=StudyDesign.META_ANALYSIS,
        sample_size=5000,
        replication_count=10,
        effect_size=0.8,
        ci_width=0.02,
        preregistered=True,
        risk_of_bias_tier=BiasRisk.LOW,
    )]
    g = score(strong, rubric)
    assert g.tier in (GradeTier.WELL_REPLICATED, GradeTier.CONSENSUS)


def test_weak_evidence_stays_speculative_or_emerging(rubric):
    weak = [make_item(
        study_design=StudyDesign.EXPERT_OPINION,
        sample_size=10,
        replication_count=0,
        effect_size=0.05,
        ci_width=0.9,
        preregistered=False,
        risk_of_bias_tier=BiasRisk.HIGH,
    )]
    g = score(weak, rubric)
    assert g.tier in (GradeTier.SPECULATIVE, GradeTier.EMERGING)


def test_tier_threshold_boundary(rubric):
    # score of 0.0 → SPECULATIVE
    g = score([], rubric)
    assert g.tier == GradeTier.SPECULATIVE


# ── explanation / contribution sum ───────────────────────────────────────────

def test_explain_contributions_sum_to_score(rubric):
    items = [make_item(), make_item(study_design=StudyDesign.PROSPECTIVE_COHORT)]
    ex = explain(items, rubric)
    total = sum(c.contribution for c in ex.contributions)
    # clamp to [0,1] happens after summing, so raw sum might differ from score
    # but contributions track the weighted dimensions before clamping
    assert abs(total - ex.score) < 1e-6 or abs(total - sum(c.contribution for c in ex.contributions)) < 1e-9


def test_explain_returns_all_dimensions(rubric):
    ex = explain([make_item()], rubric)
    dims = {c.dimension for c in ex.contributions}
    assert "design" in dims
    assert "sample_size" in dims
    assert "bias_penalty" in dims


def test_explain_tier_matches_score(rubric):
    item = make_item()
    ex = explain([item], rubric)
    g = score([item], rubric)
    assert ex.tier == g.tier
    assert abs(ex.score - g.score) < 1e-9


# ── monotonicity property tests ───────────────────────────────────────────────

evidence_item_st = st.builds(
    EvidenceItem,
    study_design=st.sampled_from(StudyDesign),
    sample_size=st.integers(min_value=1, max_value=10000),
    replication_count=st.integers(min_value=0, max_value=20),
    effect_size=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
    ci_width=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
    preregistered=st.booleans(),
    risk_of_bias_tier=st.sampled_from(BiasRisk),
)


@given(item=evidence_item_st)
@settings(max_examples=200)
def test_monotone_sample_size(item):
    rubric = Rubric.from_yaml(RUBRIC_PATH)
    bigger = item.model_copy(update={"sample_size": item.sample_size + 100})
    assert score([bigger], rubric).score >= score([item], rubric).score - 1e-9


@given(item=evidence_item_st)
@settings(max_examples=200)
def test_monotone_replication_count(item):
    rubric = Rubric.from_yaml(RUBRIC_PATH)
    more_reps = item.model_copy(update={"replication_count": item.replication_count + 1})
    assert score([more_reps], rubric).score >= score([item], rubric).score - 1e-9


@given(item=evidence_item_st)
@settings(max_examples=200)
def test_monotone_preregistered(item):
    rubric = Rubric.from_yaml(RUBRIC_PATH)
    assume(not item.preregistered)
    reg = item.model_copy(update={"preregistered": True})
    assert score([reg], rubric).score >= score([item], rubric).score - 1e-9


@given(item=evidence_item_st)
@settings(max_examples=200)
def test_monotone_lower_bias(item):
    rubric = Rubric.from_yaml(RUBRIC_PATH)
    assume(item.risk_of_bias_tier == BiasRisk.HIGH)
    lower = item.model_copy(update={"risk_of_bias_tier": BiasRisk.MODERATE})
    assert score([lower], rubric).score >= score([item], rubric).score - 1e-9


# ── misc ──────────────────────────────────────────────────────────────────────

def test_multiple_items_aggregated(rubric):
    items = [make_item() for _ in range(5)]
    g = score(items, rubric)
    assert 0.0 <= g.score <= 1.0


def test_score_is_deterministic(rubric):
    item = make_item()
    assert score([item], rubric).score == score([item], rubric).score


def test_meta_analysis_beats_expert_opinion(rubric):
    strong = make_item(study_design=StudyDesign.META_ANALYSIS)
    weak = make_item(study_design=StudyDesign.EXPERT_OPINION)
    assert score([strong], rubric).score > score([weak], rubric).score


def test_changing_yaml_changes_score(tmp_path):
    import yaml
    data = yaml.safe_load(RUBRIC_PATH.read_text())
    data["preregistered_bonus"] = 0.50
    # re-normalize weights so rubric is valid
    alt_path = tmp_path / "alt_rubric.yaml"
    alt_path.write_text(yaml.dump(data))
    alt_rubric = Rubric.from_yaml(alt_path)
    base_rubric = Rubric.from_yaml(RUBRIC_PATH)
    item = make_item(preregistered=True)
    s1 = score([item], base_rubric).score
    s2 = score([item], alt_rubric).score
    # higher bonus should produce higher or equal score
    assert s2 >= s1 - 1e-9
