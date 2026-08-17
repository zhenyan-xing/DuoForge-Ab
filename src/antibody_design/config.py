from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .schemas import (
    CDR_LOOPS,
    ChainConfig,
    DesignConfig,
    HotspotSpec,
    InputConfig,
    ModelConfig,
    MSAConfig,
    NumberingConfig,
    PipelineConfig,
    ResidueRef,
    RunConfig,
    TemplateConfig,
)


class ConfigError(ValueError):
    pass


_PATH_KEYS = {
    "checkpoint_path",
    "framework_structure",
    "lmdesign_checkpoint",
    "output_quiver",
    "pmpnn_checkpoint",
    "runtime_root",
    "target_structure",
    "upstream_root",
}


def _mapping(value: Any, name: str, default: dict | None = None) -> dict[str, Any]:
    if value is None and default is not None:
        return default
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a list")
    return value


def _resolve(base_dir: Path, value: Any) -> Path:
    path = Path(_expand_environment(str(value))).expanduser()
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def _expand_environment(value: str) -> str:
    expanded = os.path.expandvars(value)
    unresolved = re.search(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", expanded)
    if unresolved:
        name = unresolved.group(1) or unresolved.group(2)
        raise ConfigError(
            f"Environment variable {name} is not set; source the generated env.sh first"
        )
    return expanded


def _residues(values: Any, name: str) -> tuple[ResidueRef, ...]:
    try:
        return tuple(ResidueRef.parse(str(value)) for value in _list(values, name))
    except ValueError as error:
        raise ConfigError(str(error)) from error


def _path_mapping(raw: Any, name: str, base_dir: Path) -> dict[str, Path]:
    values = _mapping(raw, name, {})
    return {str(chain): _resolve(base_dir, value) for chain, value in values.items()}


def _model_options(raw: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "enabled":
            continue
        if isinstance(value, str):
            value = _expand_environment(value)
        if value is not None and (key in _PATH_KEYS or key.endswith("_path")):
            options[key] = _resolve(base_dir, value)
        else:
            options[key] = value
    return options


def _models(raw: Any, name: str, base_dir: Path) -> dict[str, ModelConfig]:
    result: dict[str, ModelConfig] = {}
    for model_name, value in _mapping(raw, name).items():
        cfg = _mapping(value, f"{name}.{model_name}")
        result[str(model_name)] = ModelConfig(
            enabled=bool(cfg.get("enabled", True)),
            options=_model_options(cfg, base_dir),
        )
    return result


def _input_config(raw: dict[str, Any], mode: str, base_dir: Path) -> InputConfig:
    target = _resolve(base_dir, raw["target_structure"]) if raw.get("target_structure") else None
    complex_path = (
        _resolve(base_dir, raw["complex_structure"]) if raw.get("complex_structure") else None
    )
    input_quiver = _resolve(base_dir, raw["input_quiver"]) if raw.get("input_quiver") else None
    framework_value = raw.get("framework")
    framework_auto = framework_value == "auto"
    if framework_auto or framework_value is None:
        frameworks: tuple[Path, ...] = ()
    elif isinstance(framework_value, list):
        frameworks = tuple(_resolve(base_dir, value) for value in framework_value)
    else:
        frameworks = (_resolve(base_dir, framework_value),)

    if mode == "de_novo":
        if target is None:
            raise ConfigError("de_novo requires input.target_structure")
        if not (framework_auto or frameworks or input_quiver):
            raise ConfigError("de_novo requires input.framework, input.framework=auto, or input_quiver")
        if input_quiver and (framework_auto or frameworks):
            raise ConfigError("input_quiver cannot be combined with input.framework")
    elif mode == "local_redesign" and complex_path is None:
        raise ConfigError("local_redesign requires input.complex_structure")
    return InputConfig(target, complex_path, frameworks, framework_auto, input_quiver)


def _validate(config: PipelineConfig) -> None:
    antibody = {config.chains.heavy, config.chains.light}
    if len(antibody) != 2:
        raise ConfigError("heavy and light chain IDs must differ")
    if antibody.intersection(config.chains.target):
        raise ConfigError("target chain IDs must differ from heavy/light chain IDs")
    if len(set(config.chains.target)) != len(config.chains.target):
        raise ConfigError("target chain IDs must be unique")

    for ref in (*config.design.residues, *config.design.fixed_residues):
        if ref.chain_id not in antibody:
            raise ConfigError("design and fixed residues must belong to H/L chains")
    effective_explicit = set(config.design.residues).difference(config.design.fixed_residues)
    if not config.design.loops and not effective_explicit:
        raise ConfigError("design mask is empty after fixed_residues are removed")

    if config.mode == "de_novo" and not config.hotspots:
        raise ConfigError("de_novo requires at least one hotspot")
    if any(item.chain_id not in config.chains.target for item in config.hotspots):
        raise ConfigError("hotspots must belong to configured target chains")

    if config.msa.mode not in {"none", "target_only", "all_unpaired"}:
        raise ConfigError("msa.mode must be none, target_only, or all_unpaired")
    if config.msa.mode == "target_only" and set(config.msa.unpaired).difference(
        config.chains.target
    ):
        raise ConfigError("target_only MSA accepts precomputed MSA only for target chains")
    known_chains = antibody.union(config.chains.target)
    if set(config.templates.target_hits).difference(config.chains.target):
        raise ConfigError("templates.target_hits may contain only target chains")
    if set(config.templates.antibody_hits).difference(antibody):
        raise ConfigError("templates.antibody_hits may contain only H/L chains")
    if set(config.msa.unpaired).difference(known_chains):
        raise ConfigError("MSA mapping contains an unknown chain")

    for name, model in config.generators.items():
        if not model.enabled:
            continue
        if int(model.options.get("proposal_budget", config.run.samples_per_seed * 2)) < 1:
            raise ConfigError(f"generators.{name}.proposal_budget must be positive")
    antifold = config.generators.get("antifold")
    if antifold and antifold.enabled and float(antifold.options.get("temperature", 0.2)) <= 0:
        raise ConfigError("generators.antifold.temperature must be positive")
    igdesign = config.generators.get("igdesign")
    if igdesign and igdesign.enabled:
        for key in ("pmpnn_temperature", "output_temperature"):
            if float(igdesign.options.get(key, 0.5)) <= 0:
                raise ConfigError(f"generators.igdesign.{key} must be positive")


def load_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        root = _mapping(yaml.safe_load(handle), "config")
    base_dir = config_path.parent

    mode = str(root.get("mode", ""))
    if mode == "full_backbone_de_novo":
        raise ConfigError("full_backbone_de_novo is not implemented")
    if mode not in {"de_novo", "local_redesign"}:
        raise ConfigError("mode must be de_novo or local_redesign")

    run_raw = _mapping(root.get("run"), "run")
    try:
        seeds = tuple(int(seed) for seed in _list(run_raw["seeds"], "run.seeds"))
        run = RunConfig(
            run_id=str(run_raw["run_id"]),
            output_dir=_resolve(base_dir, run_raw["output_dir"]),
            seeds=seeds,
            samples_per_seed=int(run_raw["samples_per_seed"]),
            save_confidence_arrays=str(run_raw.get("save_confidence_arrays", "none")),
        )
    except KeyError as error:
        raise ConfigError(f"Missing run field: {error.args[0]}") from error
    if not run.seeds or len(set(run.seeds)) != len(run.seeds):
        raise ConfigError("run.seeds must be a non-empty list of unique integers")
    if run.samples_per_seed < 1:
        raise ConfigError("run.samples_per_seed must be positive")
    if run.save_confidence_arrays not in {"none", "top1", "all"}:
        raise ConfigError("save_confidence_arrays must be none, top1, or all")

    chains_raw = _mapping(root.get("chains"), "chains")
    try:
        target = tuple(str(chain) for chain in _list(chains_raw["target"], "chains.target"))
        chains = ChainConfig(str(chains_raw["heavy"]), str(chains_raw["light"]), target)
    except KeyError as error:
        raise ConfigError(f"Missing chains field: {error.args[0]}") from error
    if not target or any(len(chain) != 1 for chain in (chains.heavy, chains.light, *target)):
        raise ConfigError("heavy, light, and target chain IDs must be one-character IDs")

    design_raw = _mapping(root.get("design"), "design")
    loops = tuple(str(loop).upper() for loop in _list(design_raw.get("loops", []), "design.loops"))
    unknown_loops = set(loops).difference(CDR_LOOPS)
    if unknown_loops:
        raise ConfigError(f"Unknown CDR loops: {', '.join(sorted(unknown_loops))}")
    design = DesignConfig(
        loops=loops,
        residues=_residues(design_raw.get("residues", []), "design.residues"),
        fixed_residues=_residues(
            design_raw.get("fixed_residues", []), "design.fixed_residues"
        ),
    )

    try:
        hotspots = tuple(
            HotspotSpec.parse(str(value))
            for value in _list(root.get("hotspots", []), "hotspots")
        )
    except ValueError as error:
        raise ConfigError(str(error)) from error

    numbering_raw = _mapping(root.get("numbering"), "numbering", {})
    numbering = NumberingConfig(
        executable=_expand_environment(str(numbering_raw.get("executable", "ANARCI"))),
        scheme=str(numbering_raw.get("scheme", "imgt")),
    )
    if numbering.scheme != "imgt":
        raise ConfigError("numbering.scheme must be imgt")

    backbone_raw = _mapping(root.get("backbone"), "backbone", {})
    rfantibody_raw = _mapping(
        backbone_raw.get("rfantibody"), "backbone.rfantibody", {}
    )
    if mode == "de_novo" and "rfantibody" not in backbone_raw:
        raise ConfigError("de_novo requires backbone.rfantibody configuration")
    backbone = ModelConfig(True, _model_options(rfantibody_raw, base_dir))

    msa_raw = _mapping(root.get("msa"), "msa", {})
    msa = MSAConfig(
        mode=str(msa_raw.get("mode", "target_only")),
        unpaired=_path_mapping(msa_raw.get("unpaired"), "msa.unpaired", base_dir),
    )
    templates_raw = _mapping(root.get("templates"), "templates", {})
    templates = TemplateConfig(
        target_hits=_path_mapping(
            templates_raw.get("target_hits"), "templates.target_hits", base_dir
        ),
        antibody_hits=_path_mapping(
            templates_raw.get("antibody_hits"), "templates.antibody_hits", base_dir
        ),
        target_structure=(
            _resolve(base_dir, templates_raw["target_structure"])
            if templates_raw.get("target_structure")
            else None
        ),
        framework_structure=(
            _resolve(base_dir, templates_raw["framework_structure"])
            if templates_raw.get("framework_structure")
            else None
        ),
    )

    config = PipelineConfig(
        config_path=config_path,
        run=run,
        mode=mode,
        input=_input_config(_mapping(root.get("input"), "input"), mode, base_dir),
        chains=chains,
        design=design,
        hotspots=hotspots,
        numbering=numbering,
        backbone=backbone,
        generators=_models(root.get("generators"), "generators", base_dir),
        predictors=_models(root.get("predictors"), "predictors", base_dir),
        msa=msa,
        templates=templates,
    )
    _validate(config)
    return config
