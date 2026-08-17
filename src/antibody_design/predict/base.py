from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from antibody_design.design.base import AdapterNotReadyError, AdapterPlan
from antibody_design.schemas import Candidate, Parent


@dataclass(frozen=True)
class PredictionRequest:
    parent: Parent
    candidate: Candidate
    output_dir: Path
    seed: int
    samples_per_seed: int
    input_path: Path
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedPrediction:
    prediction_model: str
    seed: int
    sample_index: int
    prediction_path: Path
    raw_metrics: Mapping[str, Any]
    is_model_top1: bool


PredictionResult = ParsedPrediction


class StructurePredictor:
    name = "structure-predictor"

    def plan(self, request: PredictionRequest) -> AdapterPlan:
        raise AdapterNotReadyError(f"{self.name} does not implement dry-run planning")

    def predict(self, request: PredictionRequest) -> list[ParsedPrediction]:
        raise AdapterNotReadyError(
            f"{self.name} execution is unavailable; install its pinned code and checkpoint"
        )
