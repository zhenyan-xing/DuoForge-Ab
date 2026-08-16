from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .schemas import (
    ChainConfig,
    ModelConfig,
    PipelineConfig,
    ResidueConfig,
    ResidueRef,
    RunConfig,
)


class ConfigError(ValueError):
    pass


_PATH_OPTIONS = {
    "checkpoint_path",
    "entrypoint",
    "lmdesign_checkpoint",
    "pmpnn_checkpoint",
    "upstream_root",
}


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _resolve(base_dir: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def _residues(values: Any, field_name: str) -> tuple[ResidueRef, ...]:
    if not isinstance(values, list):
        raise ConfigError(f"residues.{field_name} must be a list")
    try:
        return tuple(ResidueRef.parse(value) for value in values)
    except ValueError as error:
        raise ConfigError(str(error)) from error


def _model_configs(
    raw: Any, section: str, base_dir: Path, default_seed: int
) -> dict[str, ModelConfig]:
    models = _mapping(raw, section)
    parsed: dict[str, ModelConfig] = {}
    count_field = "num_sequences" if section == "generators" else "num_predictions"
    for name, value in models.items():
        cfg = _mapping(value, f"{section}.{name}")
        enabled = bool(cfg.get("enabled", True))
        count = int(cfg.get(count_field, 1))
        if enabled and count < 1:
            raise ConfigError(f"{section}.{name}.{count_field} must be positive")
        options = {
            key: (_resolve(base_dir, item) if key in _PATH_OPTIONS and item else item)
            for key, item in cfg.items()
            if key not in {"enabled", "seed", "num_sequences", "num_predictions"}
        }
        parsed[name] = ModelConfig(
            enabled=enabled,
            seed=int(cfg.get("seed", default_seed)),
            num_sequences=count if section == "generators" else None,
            num_predictions=count if section == "predictors" else None,
            options=options,
        )
    return parsed


def _validate(config: PipelineConfig) -> None:
    antibody_chains = {config.chains.heavy, config.chains.light}
    if len(antibody_chains) != 2:
        raise ConfigError("heavy and light chain IDs must differ")
    if antibody_chains.intersection(config.chains.antigen):
        raise ConfigError("antigen chain IDs must differ from heavy/light chain IDs")

    designable = set(config.residues.designable)
    fixed = set(config.residues.fixed)
    overlap = designable.intersection(fixed)
    if overlap:
        refs = ", ".join(sorted(str(ref) for ref in overlap))
        raise ConfigError(f"Residues cannot be both designable and fixed: {refs}")
    if any(ref.chain_id not in antibody_chains for ref in designable):
        raise ConfigError("designable residues must belong to the heavy or light chain")
    if any(ref.chain_id not in antibody_chains for ref in fixed):
        raise ConfigError("fixed residues must belong to the heavy or light chain")
    if any(ref.chain_id not in config.chains.antigen for ref in config.residues.epitope):
        raise ConfigError("epitope residues must belong to an antigen chain")

    generator_counts = {
        model.num_sequences for model in config.generators.values() if model.enabled
    }
    predictor_counts = {
        model.num_predictions for model in config.predictors.values() if model.enabled
    }
    if len(generator_counts) > 1:
        raise ConfigError("enabled generators must request the same num_sequences")
    if len(predictor_counts) > 1:
        raise ConfigError("enabled predictors must request the same num_predictions")


def load_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    root = _mapping(raw, "config")
    base_dir = config_path.parent

    run_raw = _mapping(root.get("run"), "run")
    try:
        run = RunConfig(
            parent_id=str(run_raw["parent_id"]),
            input_structure=_resolve(base_dir, run_raw["input_structure"]),
            output_dir=_resolve(base_dir, run_raw["output_dir"]),
            seed=int(run_raw["seed"]),
        )
    except KeyError as error:
        raise ConfigError(f"Missing run field: {error.args[0]}") from error

    chains_raw = _mapping(root.get("chains"), "chains")
    antigen = chains_raw.get("antigen")
    if not isinstance(antigen, list) or not antigen:
        raise ConfigError("chains.antigen must be a non-empty list")
    try:
        chains = ChainConfig(
            heavy=str(chains_raw["heavy"]),
            light=str(chains_raw["light"]),
            antigen=tuple(str(chain) for chain in antigen),
        )
    except KeyError as error:
        raise ConfigError(f"Missing chains field: {error.args[0]}") from error
    if any(len(chain) != 1 for chain in (chains.heavy, chains.light, *chains.antigen)):
        raise ConfigError("chain IDs must be one character")

    residues_raw = _mapping(root.get("residues"), "residues")
    residues = ResidueConfig(
        designable=_residues(residues_raw.get("designable"), "designable"),
        fixed=_residues(residues_raw.get("fixed"), "fixed"),
        epitope=_residues(residues_raw.get("epitope"), "epitope"),
    )
    config = PipelineConfig(
        run=run,
        chains=chains,
        residues=residues,
        generators=_model_configs(root.get("generators"), "generators", base_dir, run.seed),
        predictors=_model_configs(root.get("predictors"), "predictors", base_dir, run.seed),
    )
    _validate(config)
    return config
