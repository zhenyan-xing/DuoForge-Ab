#!/usr/bin/env python3
"""Validate real stage outputs without inventing replacement records."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from antibody_design.analysis.geometry import read_structure_atoms


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def job_states(run_dir: Path, prefix: str) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run_dir / "logs/jobs").glob(f"{prefix}*.json"))
    ]


def validate_backbone(run_dir: Path) -> tuple[str, dict]:
    parents = read_jsonl(run_dir / "parents.jsonl")
    states = job_states(run_dir, "backbone-")
    structures = [run_dir / item["structure_path"] for item in parents]
    prepared = all(path.is_file() and path.stat().st_size > 0 for path in structures)
    complete = bool(parents and states and prepared and all(item["status"] == "complete" for item in states))
    return ("complete" if complete else "failed"), {
        "parent_count": len(parents),
        "prepared_parent_files": [str(path) for path in structures],
        "job_statuses": [item["status"] for item in states],
    }


def validate_sequence(run_dir: Path) -> tuple[str, dict]:
    parents = {item["parent_id"]: item for item in read_jsonl(run_dir / "parents.jsonl")}
    candidates = read_jsonl(run_dir / "candidates.jsonl")
    generations = read_jsonl(run_dir / "generations.jsonl")
    antifold = [item for item in generations if item.get("generator") == "antifold"]
    csv_files = sorted((run_dir / "sequence-design").glob("*/antifold/seed_*/candidates.csv"))
    mask_valid = True
    for candidate in candidates:
        parent = parents.get(candidate["parent_id"])
        if not parent:
            mask_valid = False
            continue
        allowed = set(candidate.get("designed_positions", ()))
        for role, chain_key, sequence_key in (
            ("heavy", "heavy_chain", "heavy_sequence"),
            ("light", "light_chain", "light_sequence"),
        ):
            del role
            chain = parent[chain_key]
            before = parent[sequence_key]
            after = candidate[sequence_key]
            inverse = {
                index: ref
                for ref, index in parent.get("sequence_index_by_author", {}).items()
                if ref.startswith(f"{chain}:")
            }
            for index, (old, new) in enumerate(zip(before, after)):
                if old != new and inverse.get(index) not in allowed:
                    mask_valid = False
    complete = bool(
        candidates
        and antifold
        and csv_files
        and mask_valid
        and all(item.get("status") == "complete" for item in antifold)
    )
    return ("complete" if complete else "failed"), {
        "candidate_count": len(candidates),
        "antifold_generation_count": len(antifold),
        "igdesign_generation_count": sum(
            item.get("generator") == "igdesign" for item in generations
        ),
        "csv_files": [str(path) for path in csv_files],
        "fixed_positions_unchanged": mask_valid,
    }


def validate_fold(run_dir: Path) -> tuple[str, dict]:
    predictions = read_jsonl(run_dir / "predictions.jsonl")
    valid = []
    coordinate_sanity: dict[str, dict] = {}
    for item in predictions:
        path = run_dir / item["prediction_path"]
        if not (
            path.is_file()
            and path.stat().st_size > 0
            and item.get("raw_metrics")
            and item.get("geometry_metrics")
        ):
            continue
        try:
            atoms = read_structure_atoms(path)
        except (OSError, ValueError) as error:
            coordinate_sanity[item["prediction_id"]] = {
                "status": "unparseable",
                "error": str(error),
            }
            continue
        valid.append(item)
        ca = {(atom.chain, atom.residue_index): atom.xyz for atom in atoms if atom.name == "CA"}
        distances = []
        for chain in sorted({chain for chain, _ in ca}):
            chain_ca = sorted(
                (index, xyz) for (item_chain, index), xyz in ca.items() if item_chain == chain
            )
            distances.extend(
                math.dist(left.tolist(), right.tolist())
                for (_, left), (_, right) in zip(chain_ca, chain_ca[1:])
            )
        plausible = sum(3.0 <= distance <= 5.0 for distance in distances)
        fraction = plausible / len(distances) if distances else None
        coordinate_sanity[item["prediction_id"]] = {
            "status": "plausible" if fraction is not None and fraction >= 0.9 else "implausible",
            "ca_count": len(ca),
            "sequential_ca_distance_count": len(distances),
            "sequential_ca_distance_min_angstrom": min(distances) if distances else None,
            "sequential_ca_distance_median_angstrom": statistics.median(distances) if distances else None,
            "sequential_ca_distance_max_angstrom": max(distances) if distances else None,
            "sequential_ca_distance_3_to_5_angstrom_count": plausible,
            "sequential_ca_distance_3_to_5_angstrom_fraction": fraction,
        }
    models = {item["prediction_model"] for item in valid}
    if {"protenix-v2", "opendde_v1"}.issubset(models):
        status = "complete"
    elif models:
        status = "partial_smoke"
    else:
        status = "failed"
    states = job_states(run_dir, "prediction-")
    return status, {
        "valid_prediction_count": len(valid),
        "validated_models": sorted(models),
        "job_statuses": {item["job_id"]: item["status"] for item in states},
        "coordinate_sanity_by_prediction": coordinate_sanity,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("backbone", "sequence-design", "fold"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    validators = {
        "backbone": validate_backbone,
        "sequence-design": validate_sequence,
        "fold": validate_fold,
    }
    status, details = validators[args.stage](args.output_dir.resolve())
    payload = {"stage": args.stage, "status": status, **details}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return {"complete": 0, "partial_smoke": 3, "failed": 2}[status]


if __name__ == "__main__":
    raise SystemExit(main())
