from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from antibody_design.schemas import Parent


class AdapterNotReadyError(RuntimeError):
    pass


class CapabilityError(ValueError):
    pass


@dataclass(frozen=True)
class ExternalCommand:
    argv: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    ready: bool = False
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "cwd": str(self.cwd) if self.cwd else None,
            "env": dict(self.env),
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
    metadata: Mapping[str, Any] = field(default_factory=dict)
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "adapter": self.adapter,
            "dry_run": self.dry_run,
            "commands": [command.to_dict() for command in self.commands],
            "expected_outputs": list(self.expected_outputs),
            "notes": list(self.notes),
            "metadata": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in self.metadata.items()
            },
        }


@dataclass(frozen=True)
class DesignRequest:
    parent: Parent
    prepared_dir: Path
    output_dir: Path
    seeds: tuple[int, ...]
    unique_per_generator: int
    proposal_budget: int
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SequenceProposal:
    heavy_sequence: str
    light_sequence: str
    seed: int
    sample_index: int
    raw_metrics: Mapping[str, Any] = field(default_factory=dict)
    designed_positions: tuple[str, ...] = ()


GeneratedSequence = SequenceProposal


class SequenceDesigner:
    name = "sequence-designer"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        raise AdapterNotReadyError(f"{self.name} does not implement dry-run planning")

    def generate(self, request: DesignRequest) -> list[SequenceProposal]:
        raise AdapterNotReadyError(
            f"{self.name} execution is unavailable; install its pinned code and checkpoint"
        )
