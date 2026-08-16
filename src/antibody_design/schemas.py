from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, order=True)
class ResidueRef:
    """PDB residue reference in ``CHAIN:NUMBER[INSERTION_CODE]`` form."""

    chain_id: str
    residue_id: str

    @classmethod
    def parse(cls, value: str) -> "ResidueRef":
        if not isinstance(value, str) or ":" not in value:
            raise ValueError(f"Invalid residue reference: {value!r}")
        chain_id, residue_id = value.split(":", 1)
        if len(chain_id) != 1 or not residue_id:
            raise ValueError(f"Invalid residue reference: {value!r}")
        number = residue_id[:-1] if residue_id[-1].isalpha() else residue_id
        if not number.lstrip("-").isdigit():
            raise ValueError(f"Invalid residue reference: {value!r}")
        return cls(chain_id=chain_id, residue_id=residue_id)

    def __str__(self) -> str:
        return f"{self.chain_id}:{self.residue_id}"


@dataclass(frozen=True)
class RunConfig:
    parent_id: str
    input_structure: Path
    output_dir: Path
    seed: int


@dataclass(frozen=True)
class ChainConfig:
    heavy: str
    light: str
    antigen: tuple[str, ...]


@dataclass(frozen=True)
class ResidueConfig:
    designable: tuple[ResidueRef, ...]
    fixed: tuple[ResidueRef, ...]
    epitope: tuple[ResidueRef, ...]


@dataclass(frozen=True)
class ModelConfig:
    enabled: bool
    seed: int
    num_sequences: int | None = None
    num_predictions: int | None = None
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineConfig:
    run: RunConfig
    chains: ChainConfig
    residues: ResidueConfig
    generators: Mapping[str, ModelConfig]
    predictors: Mapping[str, ModelConfig]


@dataclass(frozen=True)
class ResidueInfo:
    ref: ResidueRef
    name3: str
    name1: str
    sequence_index: int


@dataclass(frozen=True)
class PreparedComplex:
    parent_id: str
    input_structure: Path
    chains: ChainConfig
    residues_by_chain: Mapping[str, tuple[ResidueInfo, ...]]
    heavy_sequence: str
    light_sequence: str
    antigen_sequences: Mapping[str, str]
    designable_positions: tuple[ResidueRef, ...]
    fixed_positions: tuple[ResidueRef, ...]
    epitope_positions: tuple[ResidueRef, ...]

    def sequence_index(self, ref: ResidueRef) -> int:
        for residue in self.residues_by_chain[ref.chain_id]:
            if residue.ref == ref:
                return residue.sequence_index
        raise KeyError(str(ref))


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    parent_id: str
    generator: str
    heavy_sequence: str
    light_sequence: str
    designed_positions: tuple[str, ...]
    mutation_count: int
    sequence_cluster: str
    seed: int
    generation_metrics: Mapping[str, Any] = field(default_factory=dict)
    liabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateManifestRow:
    candidate_id: str
    parent_id: str
    generator: str
    heavy_sequence: str
    light_sequence: str
    designed_positions: tuple[str, ...]
    mutation_count: int
    sequence_cluster: str
    prediction_model: str
    seed: int
    prediction_path: str
    raw_metrics: Mapping[str, Any]
    generation_metrics: Mapping[str, Any] = field(default_factory=dict)
    liabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
