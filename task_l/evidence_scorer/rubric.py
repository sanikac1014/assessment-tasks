from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel


class RubricValidationError(ValueError):
    pass


class Rubric(BaseModel):
    design_base_scores: dict[str, float]
    replication_bonus: dict[str, float]   # keys: "per_replication", "cap"
    sample_size_weight: float
    sample_size_scale: float              # sigmoid midpoint
    effect_size_weight: float
    ci_width_penalty_weight: float
    preregistered_bonus: float
    bias_penalties: dict[str, float]      # LOW/MODERATE/HIGH -> penalty
    weights: dict[str, float]             # dimension -> weight (must sum to 1)
    tier_thresholds: dict[str, float]     # tier name -> min score

    @classmethod
    def from_yaml(cls, path: Path) -> "Rubric":
        data = yaml.safe_load(path.read_text())
        rubric = cls.model_validate(data)
        rubric._validate_weights()
        return rubric

    def _validate_weights(self):
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise RubricValidationError(
                f"Rubric weights must sum to 1.0, got {total:.6f}"
            )
