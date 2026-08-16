from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from antibody_design.schemas import PreparedComplex


class AdapterNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalCommand:
    argv: tuple[str, ...]
    cwd: Path | None = None
    ready: bool = False
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "cwd": str(self.cwd) if self.cwd else None,
            "ready": self.ready,
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class AdapterPlan:
    stage: str
    adapter: str
    commands: tuple[ExternalCommand, ...]
    expected_outputs: tuple[str, ...]
    notes: tuple[str, ...] = ()
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "adapter": self.adapter,
            "dry_run": self.dry_run,
            "commands": [command.to_dict() for command in self.commands],
            "expected_outputs": list(self.expected_outputs),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DesignRequest:
    prepared: PreparedComplex
    prepared_dir: Path
    output_dir: Path
    num_sequences: int
    seed: int
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedSequence:
    heavy_sequence: str
    light_sequence: str
    raw_metrics: Mapping[str, Any] = field(default_factory=dict)


class SequenceDesigner:
    name = "sequence-designer"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        raise AdapterNotReadyError(f"{self.name} does not implement dry-run planning")

    def generate(self, request: DesignRequest) -> list[GeneratedSequence]:
        raise AdapterNotReadyError(
            f"{self.name} execution is not implemented; use dry-run or a mock adapter"
        )
