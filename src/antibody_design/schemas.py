from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


CDR_LOOPS = ("H1", "H2", "H3", "L1", "L2", "L3")


@dataclass(frozen=True, order=True)
class ResidueRef:
    """Author residue identifier in ``CHAIN:NUMBER[INSERTION_CODE]`` form."""

    chain_id: str
    residue_id: str

    @classmethod
    def parse(cls, value: str) -> "ResidueRef":
        if not isinstance(value, str) or ":" not in value:
            raise ValueError(f"Invalid residue reference: {value!r}")
        chain_id, residue_id = value.split(":", 1)
        if len(chain_id) != 1 or not residue_id:
            raise ValueError(f"Invalid residue reference: {value!r}")
        number = residue_id.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        insertion = residue_id[len(number) :]
        if not number.lstrip("-").isdigit() or len(insertion) > 1:
            raise ValueError(f"Invalid residue reference: {value!r}")
        return cls(chain_id, residue_id)

    def __str__(self) -> str:
        return f"{self.chain_id}:{self.residue_id}"


@dataclass(frozen=True)
class HotspotSpec:
    chain_id: str
    selector: str

    @classmethod
    def parse(cls, value: str) -> "HotspotSpec":
        if not isinstance(value, str):
            raise ValueError(f"Invalid hotspot: {value!r}")
        if ":" in value:
            chain_id, selector = value.split(":", 1)
        else:
            chain_id, selector = value[:1], value[1:]
        if len(chain_id) != 1 or not selector:
            raise ValueError(f"Invalid hotspot: {value!r}")
        if selector != "*":
            parts = selector.split("-", 1)
            if any(not part.lstrip("-").isdigit() for part in parts):
                try:
                    ResidueRef.parse(f"{chain_id}:{selector}")
                except ValueError as error:
                    raise ValueError(f"Invalid hotspot: {value!r}") from error
        return cls(chain_id, selector)

    def __str__(self) -> str:
        return f"{self.chain_id}:{self.selector}"


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    output_dir: Path
    seeds: tuple[int, ...]
    samples_per_seed: int
    save_confidence_arrays: str = "none"


@dataclass(frozen=True)
class InputConfig:
    target_structure: Path | None = None
    complex_structure: Path | None = None
    frameworks: tuple[Path, ...] = ()
    framework_auto: bool = False
    input_quiver: Path | None = None


@dataclass(frozen=True)
class ChainConfig:
    heavy: str
    light: str
    target: tuple[str, ...]


@dataclass(frozen=True)
class DesignConfig:
    loops: tuple[str, ...]
    residues: tuple[ResidueRef, ...]
    fixed_residues: tuple[ResidueRef, ...]


@dataclass(frozen=True)
class NumberingConfig:
    executable: str = "ANARCI"
    scheme: str = "imgt"


@dataclass(frozen=True)
class ModelConfig:
    enabled: bool
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MSAConfig:
    mode: str = "target_only"
    unpaired: Mapping[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateConfig:
    target_hits: Mapping[str, Path] = field(default_factory=dict)
    antibody_hits: Mapping[str, Path] = field(default_factory=dict)
    target_structure: Path | None = None
    framework_structure: Path | None = None


@dataclass(frozen=True)
class PipelineConfig:
    config_path: Path
    run: RunConfig
    mode: str
    input: InputConfig
    chains: ChainConfig
    design: DesignConfig
    hotspots: tuple[HotspotSpec, ...]
    numbering: NumberingConfig
    backbone: ModelConfig
    generators: Mapping[str, ModelConfig]
    predictors: Mapping[str, ModelConfig]
    msa: MSAConfig
    templates: TemplateConfig


@dataclass(frozen=True)
class ResidueInfo:
    ref: ResidueRef
    name3: str
    name1: str
    sequence_index: int


@dataclass(frozen=True)
class NumberingMapEntry:
    chain_id: str
    author_residue_id: str
    sequence_index: int
    hlt_absolute_index: int
    imgt_residue_id: str | None


@dataclass(frozen=True)
class Parent:
    parent_id: str
    mode: str
    structure_path: Path
    heavy_chain: str
    light_chain: str
    target_chains: tuple[str, ...]
    heavy_sequence: str
    light_sequence: str
    target_sequences: Mapping[str, str] = field(default_factory=dict)
    sequence_index_by_author: Mapping[str, int] = field(default_factory=dict)
    designable_positions: tuple[str, ...] = ()
    fixed_positions: tuple[str, ...] = ()
    cdr_positions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    hotspots: tuple[str, ...] = ()
    numbering_map_path: Path | None = None
    imgt_structure_path: Path | None = None
    chain_map_path: Path | None = None

    def sequence_index(self, ref: ResidueRef, mapping: tuple[NumberingMapEntry, ...]) -> int:
        for item in mapping:
            if item.chain_id == ref.chain_id and item.author_residue_id == ref.residue_id:
                return item.sequence_index
        raise KeyError(str(ref))


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    parent_id: str
    heavy_sequence: str
    light_sequence: str
    designed_positions: tuple[str, ...]
    mutation_count: int
    sequence_cluster: str
    liabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationRecord:
    generation_id: str
    candidate_id: str
    parent_id: str
    generator: str
    seed: int
    sample_index: int
    raw_metrics: Mapping[str, Any]
    designed_positions: tuple[str, ...]
    status: str = "complete"


@dataclass(frozen=True)
class PredictionRecord:
    prediction_id: str
    candidate_id: str
    prediction_model: str
    seed: int
    sample_index: int
    prediction_path: str
    raw_metrics: Mapping[str, Any]
    geometry_metrics: Mapping[str, Any] = field(default_factory=dict)
    is_model_top1: bool = False
    status: str = "complete"


@dataclass(frozen=True)
class PredictionJob:
    candidate_id: str
    prediction_model: str
    seed: int
    samples_per_seed: int


def record_dict(record: object) -> dict[str, Any]:
    def convert(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [convert(item) for item in value]
        return value

    return convert(asdict(record))
