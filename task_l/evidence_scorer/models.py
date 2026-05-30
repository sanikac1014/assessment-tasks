from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator


class StudyDesign(str, Enum):
    META_ANALYSIS = "META_ANALYSIS"
    RCT = "RCT"
    PROSPECTIVE_COHORT = "PROSPECTIVE_COHORT"
    CASE_CONTROL = "CASE_CONTROL"
    CROSS_SECTIONAL = "CROSS_SECTIONAL"
    CASE_SERIES = "CASE_SERIES"
    MECHANISTIC_ONLY = "MECHANISTIC_ONLY"
    EXPERT_OPINION = "EXPERT_OPINION"


class BiasRisk(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class GradeTier(str, Enum):
    SPECULATIVE = "SPECULATIVE"
    EMERGING = "EMERGING"
    SUPPORTED = "SUPPORTED"
    WELL_REPLICATED = "WELL_REPLICATED"
    CONSENSUS = "CONSENSUS"


class EvidenceItem(BaseModel):
    study_design: StudyDesign
    sample_size: int
    replication_count: int
    effect_size: float
    ci_width: float
    preregistered: bool
    risk_of_bias_tier: BiasRisk

    @field_validator("sample_size", "replication_count")
    @classmethod
    def must_be_positive(cls, v):
        if v < 0:
            raise ValueError("must be >= 0")
        return v


class EvidenceGrade(BaseModel):
    tier: GradeTier
    score: float
    threshold_used: float


class DimensionContribution(BaseModel):
    dimension: str
    contribution: float


class GradeExplanation(BaseModel):
    tier: GradeTier
    score: float
    contributions: list[DimensionContribution]
    item_breakdowns: list[dict]
