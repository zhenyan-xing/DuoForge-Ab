from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from .schemas import PipelineConfig, PreparedComplex, ResidueInfo, ResidueRef


class PreparationError(ValueError):
    pass


_AA3_TO_1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "MSE": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def _read_pdb(path: Path) -> dict[str, tuple[ResidueInfo, ...]]:
    if not path.is_file():
        raise PreparationError(f"Input structure does not exist: {path}")
    observed: dict[str, list[tuple[ResidueRef, str]]] = defaultdict(list)
    seen: set[ResidueRef] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("ATOM") or len(line) < 27:
                continue
            altloc = line[16].strip()
            if altloc not in {"", "A"}:
                continue
            chain_id = line[21].strip()
            residue_number = line[22:26].strip()
            insertion_code = line[26].strip()
            name3 = line[17:20].strip().upper()
            if not chain_id or not residue_number:
                continue
            ref = ResidueRef(chain_id, residue_number + insertion_code)
            if ref in seen:
                continue
            if name3 not in _AA3_TO_1:
                raise PreparationError(f"Unsupported residue {name3} at {ref}")
            seen.add(ref)
            observed[chain_id].append((ref, name3))

    residues: dict[str, tuple[ResidueInfo, ...]] = {}
    for chain_id, chain_residues in observed.items():
        residues[chain_id] = tuple(
            ResidueInfo(
                ref=ref,
                name3=name3,
                name1=_AA3_TO_1[name3],
                sequence_index=index,
            )
            for index, (ref, name3) in enumerate(chain_residues)
        )
    return residues


def prepare_complex(config: PipelineConfig) -> PreparedComplex:
    residues_by_chain = _read_pdb(config.run.input_structure)
    required_chains = {
        config.chains.heavy,
        config.chains.light,
        *config.chains.antigen,
    }
    missing_chains = sorted(required_chains.difference(residues_by_chain))
    if missing_chains:
        raise PreparationError(f"Chains not found in input structure: {', '.join(missing_chains)}")

    available = {residue.ref for chain in residues_by_chain.values() for residue in chain}
    configured = {
        *config.residues.designable,
        *config.residues.fixed,
        *config.residues.epitope,
    }
    missing_residues = sorted(configured.difference(available))
    if missing_residues:
        refs = ", ".join(str(ref) for ref in missing_residues)
        raise PreparationError(f"Configured residues not found in input structure: {refs}")

    def sequence(chain_id: str) -> str:
        return "".join(residue.name1 for residue in residues_by_chain[chain_id])

    return PreparedComplex(
        parent_id=config.run.parent_id,
        input_structure=config.run.input_structure,
        chains=config.chains,
        residues_by_chain=residues_by_chain,
        heavy_sequence=sequence(config.chains.heavy),
        light_sequence=sequence(config.chains.light),
        antigen_sequences={chain: sequence(chain) for chain in config.chains.antigen},
        designable_positions=config.residues.designable,
        fixed_positions=config.residues.fixed,
        epitope_positions=config.residues.epitope,
    )


def write_prepared_complex(prepared: PreparedComplex, output_dir: Path) -> Path:
    prepared_dir = output_dir / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    structure_dir = prepared_dir / "input_structure"
    structure_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(prepared.input_structure, structure_dir / prepared.input_structure.name)
    path = prepared_dir / "complex.json"
    payload = {
        "parent_id": prepared.parent_id,
        "input_structure": str(prepared.input_structure),
        "chains": {
            "heavy": prepared.chains.heavy,
            "light": prepared.chains.light,
            "antigen": list(prepared.chains.antigen),
        },
        "sequences": {
            "heavy": prepared.heavy_sequence,
            "light": prepared.light_sequence,
            "antigen": dict(prepared.antigen_sequences),
        },
        "designable_positions": [str(ref) for ref in prepared.designable_positions],
        "fixed_positions": [str(ref) for ref in prepared.fixed_positions],
        "epitope_positions": [str(ref) for ref in prepared.epitope_positions],
        "sequence_index_by_residue": {
            str(residue.ref): residue.sequence_index
            for chain in prepared.residues_by_chain.values()
            for residue in chain
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
