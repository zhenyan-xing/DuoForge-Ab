from __future__ import annotations

import json
import re
from pathlib import Path

from antibody_design.schemas import Candidate, MSAConfig, Parent, TemplateConfig

from .base import ParsedPrediction


def write_prediction_input(
    parent: Parent,
    candidate: Candidate,
    seed: int,
    output_dir: Path,
    msa: MSAConfig,
    templates: TemplateConfig,
) -> Path:
    """Write one shared logical Protenix/OpenDDE input; no paired Ab-Ag MSA."""

    input_dir = output_dir / "prediction_inputs" / candidate.candidate_id / f"seed_{seed}"
    msa_dir = input_dir / "msa"
    input_dir.mkdir(parents=True, exist_ok=True)
    chains = [
        (parent.heavy_chain, candidate.heavy_sequence),
        (parent.light_chain, candidate.light_sequence),
        *((chain, parent.target_sequences[chain]) for chain in parent.target_chains),
    ]
    sequence_entries = []
    logical_msa: dict[str, dict] = {}
    logical_templates: dict[str, str] = {}
    any_template = bool(templates.target_hits or templates.antibody_hits)
    empty_template_dir = input_dir / "templates"
    for chain, sequence in chains:
        protein = {"sequence": sequence, "count": 1, "id": [chain]}
        if msa.mode != "none":
            supplied = msa.unpaired.get(chain)
            if supplied:
                unpaired = supplied
                source = "user_precomputed"
            else:
                msa_dir.mkdir(parents=True, exist_ok=True)
                unpaired = msa_dir / f"{chain}.query_only.a3m"
                unpaired.write_text(f">query_{chain}\n{sequence}\n", encoding="utf-8")
                source = "query_only"
            protein["unpairedMsaPath"] = str(unpaired)
            logical_msa[chain] = {
                "unpaired": str(unpaired),
                "source": source,
                "paired": None,
            }
        template_path = templates.target_hits.get(chain) or templates.antibody_hits.get(chain)
        if template_path:
            protein["templatesPath"] = str(template_path)
            logical_templates[chain] = str(template_path)
        elif any_template:
            # An explicit empty file prevents both upstream CLIs from launching an
            # automatic template search for an untemplated chain.
            empty_template_dir.mkdir(parents=True, exist_ok=True)
            no_hits = empty_template_dir / f"{chain}.no_hits.a3m"
            no_hits.write_text("", encoding="utf-8")
            protein["templatesPath"] = str(no_hits)
            logical_templates[chain] = str(no_hits)
        sequence_entries.append({"proteinChain": protein})

    path = input_dir / "complex.json"
    payload = [
        {
            "name": candidate.candidate_id,
            "modelSeeds": [seed],
            "sequences": sequence_entries,
        }
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (input_dir / "logical_inputs.json").write_text(
        json.dumps(
            {
                "msa_mode": msa.mode,
                "msa": logical_msa,
                "templates": logical_templates,
                "target_template_structure": (
                    str(templates.target_structure) if templates.target_structure else None
                ),
                "framework_template_structure": (
                    str(templates.framework_structure) if templates.framework_structure else None
                ),
                "paired_antibody_target_msa": False,
                "blind_pose": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def parse_prediction_outputs(
    output_root: Path, job_name: str, seed: int, model_name: str
) -> list[ParsedPrediction]:
    candidates = list(output_root.glob(f"**/{job_name}/seed_{seed}/predictions"))
    candidates.extend(output_root.glob(f"**/seed_{seed}/predictions"))
    candidates.append(output_root / "predictions")
    prediction_dir = next((path for path in candidates if path.is_dir()), None)
    if prediction_dir is None:
        raise FileNotFoundError(
            f"No official predictions directory for job={job_name}, seed={seed} under {output_root}"
        )
    structures = sorted(
        (*prediction_dir.glob(f"{job_name}_sample_*.cif"), *prediction_dir.glob("*_sample_*.cif")),
        key=lambda path: _sample_index(path.stem),
    )
    unique_structures = list(dict.fromkeys(structures))
    if not unique_structures:
        raise FileNotFoundError(f"No predicted CIF structures in {prediction_dir}")
    parsed: list[ParsedPrediction] = []
    for structure in unique_structures:
        sample_index = _sample_index(structure.stem)
        summary_matches = list(
            prediction_dir.glob(f"*_summary_confidence_sample_{sample_index}.json")
        )
        if not summary_matches:
            raise FileNotFoundError(f"Missing confidence JSON for {structure}")
        metrics = json.loads(summary_matches[0].read_text(encoding="utf-8"))
        full_matches = list(prediction_dir.glob(f"*_full_data_sample_{sample_index}.json"))
        if full_matches:
            full = json.loads(full_matches[0].read_text(encoding="utf-8"))
            for key in ("interface_pae", "interface_pae_mean", "chain_pair_pae_min"):
                if key in full:
                    if key == "interface_pae":
                        values = list(_numeric_values(full[key]))
                        if values:
                            metrics["full_data_interface_pae_mean"] = sum(values) / len(values)
                    else:
                        metrics[f"full_data_{key}"] = full[key]
        parsed.append(
            ParsedPrediction(
                prediction_model=model_name,
                seed=seed,
                sample_index=sample_index,
                prediction_path=structure,
                raw_metrics=metrics,
                is_model_top1=sample_index == 0,
            )
        )
    return parsed


def _sample_index(stem: str) -> int:
    marker = "_sample_"
    if marker not in stem:
        return 10**9
    suffix = stem.rsplit(marker, 1)[1]
    return int(suffix.split("_", 1)[0])


def _numeric_values(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        yield float(value)
    elif isinstance(value, list):
        for item in value:
            yield from _numeric_values(item)


def missing_prediction_assets(
    input_path: Path,
    use_msa: bool,
    use_template: bool,
    template_mmcif_dir: Path | None = None,
) -> list[str]:
    if not input_path.is_file():
        return [f"prediction input JSON: {input_path}"]
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    missing: list[str] = []
    for entity in payload[0].get("sequences", []):
        protein = entity.get("proteinChain")
        if not protein:
            continue
        chain = protein.get("id", ["?"])[0]
        for enabled, field in (
            (use_msa, "unpairedMsaPath"),
            (use_template, "templatesPath"),
        ):
            value = protein.get(field)
            if enabled and (not value or not Path(value).is_file()):
                missing.append(f"{field} for chain {chain}: {value or '<absent>'}")
            if enabled and field == "templatesPath" and value and Path(value).is_file():
                for pdb_id in _template_hit_ids(Path(value)):
                    if template_mmcif_dir is None or not any(
                        path.is_file()
                        for path in (
                            template_mmcif_dir / f"{pdb_id}.cif",
                            template_mmcif_dir / f"{pdb_id.lower()}.cif",
                            template_mmcif_dir / f"{pdb_id.upper()}.cif",
                        )
                    ):
                        missing.append(
                            f"offline template mmCIF {pdb_id} for chain {chain} under {template_mmcif_dir}"
                        )
        if "pairedMsaPath" in protein:
            missing.append(f"pairedMsaPath is forbidden for antibody-target inputs (chain {chain})")
    return missing


def _template_hit_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if path.suffix.lower() == ".a3m" and line.startswith(">"):
            match = re.match(r">([A-Za-z0-9]{4})[_ ]", line)
        elif path.suffix.lower() == ".hhr" and line.startswith(">>"):
            match = re.match(r">>([A-Za-z0-9]{4})[_ ]", line)
        else:
            continue
        if match:
            ids.add(match.group(1).lower())
    return ids
