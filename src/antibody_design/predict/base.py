from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from antibody_design.design.base import AdapterNotReadyError, AdapterPlan
from antibody_design.schemas import Candidate, PreparedComplex


@dataclass(frozen=True)
class PredictionRequest:
    prepared: PreparedComplex
    candidate: Candidate
    output_dir: Path
    seed: int
    input_path: Path | None = None
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionResult:
    prediction_model: str
    seed: int
    prediction_path: Path
    raw_metrics: Mapping[str, Any] = field(default_factory=dict)


class StructurePredictor:
    name = "structure-predictor"

    def plan(self, request: PredictionRequest) -> AdapterPlan:
        raise AdapterNotReadyError(f"{self.name} does not implement dry-run planning")

    def predict(self, request: PredictionRequest) -> PredictionResult:
        raise AdapterNotReadyError(
            f"{self.name} execution is not implemented; use dry-run or a mock adapter"
        )
