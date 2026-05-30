from enum import Enum
from typing import Optional
from pydantic import BaseModel


class AdjustmentMethod(str, Enum):
    NAIVE = "NAIVE"
    IPTW = "IPTW"
    GCOMPUTATION = "GCOMPUTATION"


class EffectEstimate(BaseModel):
    method: AdjustmentMethod
    ate: float                  # average treatment effect
    ci_lower: float
    ci_upper: float
    n_treated: int
    n_control: int


class PositivityViolation(BaseModel):
    method: AdjustmentMethod
    min_overlap: float
    threshold: float
    message: str


class TruthConfig(BaseModel):
    true_ate: float
    confounder_effect_on_treatment: float
    confounder_effect_on_outcome: float
    base_outcome: float
    noise_std: float
    n_confounders: int = 1
    seed: int = 0


class RecoveryReport(BaseModel):
    config: TruthConfig
    n: int
    seed: int
    naive_ate: float
    iptw_ate: float
    gcomp_ate: float
    true_ate: float
    naive_bias: float
    iptw_bias: float
    gcomp_bias: float
    iptw_ci: tuple[float, float]
    gcomp_ci: tuple[float, float]
    iptw_covers_truth: bool
    gcomp_covers_truth: bool


class OverlapDiagnostic(BaseModel):
    min_propensity_treated: float
    max_propensity_control: float
    overlap_ok: bool
