from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from antibody_design.schemas import Parent


@dataclass(frozen=True)
class Atom:
    chain: str
    residue_id: str
    residue_index: int
    name: str
    xyz: np.ndarray


def _indexed(records: list[tuple[str, str, str, float, float, float]]) -> list[Atom]:
    indices: dict[tuple[str, str], int] = {}
    next_index: dict[str, int] = {}
    atoms: list[Atom] = []
    for chain, residue_id, name, x, y, z in records:
        key = (chain, residue_id)
        if key not in indices:
            indices[key] = next_index.get(chain, 0)
            next_index[chain] = indices[key] + 1
        atoms.append(Atom(chain, residue_id, indices[key], name, np.array([x, y, z])))
    return atoms


def read_structure_atoms(path: Path) -> list[Atom]:
    text = path.read_text(encoding="utf-8")
    records: list[tuple[str, str, str, float, float, float]] = []
    if path.suffix.lower() in {".cif", ".mmcif"}:
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            if lines[index].strip() != "loop_":
                index += 1
                continue
            fields: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip().startswith("_atom_site."):
                fields.append(lines[index].strip())
                index += 1
            if not fields:
                continue
            lookup = {field: position for position, field in enumerate(fields)}
            while index < len(lines):
                line = lines[index].strip()
                if not line or line.startswith(("#", "loop_", "_")):
                    break
                values = shlex.split(line)
                if len(values) >= len(fields):
                    group = values[lookup.get("_atom_site.group_PDB", 0)]
                    if group in {"ATOM", "HETATM"}:
                        atom = values[lookup.get("_atom_site.label_atom_id", lookup.get("_atom_site.auth_atom_id", 3))]
                        chain = values[lookup.get("_atom_site.auth_asym_id", lookup.get("_atom_site.label_asym_id", 6))]
                        residue = values[lookup.get("_atom_site.auth_seq_id", lookup.get("_atom_site.label_seq_id", 8))]
                        insertion_key = lookup.get("_atom_site.pdbx_PDB_ins_code")
                        insertion = values[insertion_key] if insertion_key is not None else ""
                        if insertion in {"?", "."}:
                            insertion = ""
                        x = float(values[lookup["_atom_site.Cartn_x"]])
                        y = float(values[lookup["_atom_site.Cartn_y"]])
                        z = float(values[lookup["_atom_site.Cartn_z"]])
                        if not atom.startswith("H"):
                            records.append((chain, residue + insertion, atom, x, y, z))
                index += 1
            continue
    else:
        for line in text.splitlines():
            if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54:
                continue
            atom = line[12:16].strip()
            if atom.startswith("H"):
                continue
            records.append(
                (
                    line[21].strip(),
                    line[22:26].strip() + line[26].strip(),
                    atom,
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                )
            )
    if not records:
        raise ValueError(f"No heavy atoms parsed from predicted structure: {path}")
    return _indexed(records)


def _transform(moving: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    moving_center = moving.mean(axis=0)
    reference_center = reference.mean(axis=0)
    covariance = (moving - moving_center).T @ (reference - reference_center)
    left, _, right = np.linalg.svd(covariance)
    rotation = left @ right
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right
    translation = reference_center - moving_center @ rotation
    return rotation, translation


def _rmsd(
    predicted: dict[tuple[str, int, str], np.ndarray],
    reference: dict[tuple[str, int, str], np.ndarray],
    keys: set[tuple[str, int, str]],
    rotation: np.ndarray,
    translation: np.ndarray,
) -> float | None:
    common = sorted(keys.intersection(predicted, reference))
    if not common:
        return None
    delta = np.array([predicted[key] @ rotation + translation - reference[key] for key in common])
    return float(np.sqrt(np.mean(np.sum(delta * delta, axis=1))))


def compute_geometry(
    predicted_path: Path,
    reference_path: Path,
    parent: Parent,
    contact_cutoff_angstrom: float = 5.0,
) -> dict:
    """Compute observations only. No threshold here is a pass/fail criterion."""

    predicted_atoms = read_structure_atoms(predicted_path)
    reference_atoms = read_structure_atoms(reference_path)
    predicted = {(a.chain, a.residue_index, a.name): a.xyz for a in predicted_atoms}
    reference = {(a.chain, a.residue_index, a.name): a.xyz for a in reference_atoms}
    antibody_chains = {parent.heavy_chain, parent.light_chain}
    target_chains = set(parent.target_chains)
    design_indices = {
        (ref.split(":", 1)[0], parent.sequence_index_by_author[ref])
        for ref in parent.designable_positions
        if ref in parent.sequence_index_by_author
    }
    hotspot_indices = {
        ref: (ref.split(":", 1)[0], parent.sequence_index_by_author[ref])
        for ref in parent.hotspots
        if ref in parent.sequence_index_by_author
    }
    author_by_index = {
        (ref.split(":", 1)[0], index): ref
        for ref, index in parent.sequence_index_by_author.items()
    }

    cdr_atoms = [a for a in predicted_atoms if (a.chain, a.residue_index) in design_indices]
    target_atoms = [a for a in predicted_atoms if a.chain in target_chains]
    contacts: set[tuple[str, str]] = set()
    target_contact_refs: set[str] = set()
    cutoff_squared = contact_cutoff_angstrom**2
    for cdr in cdr_atoms:
        for target in target_atoms:
            if float(np.sum((cdr.xyz - target.xyz) ** 2)) <= cutoff_squared:
                cdr_ref = author_by_index.get(
                    (cdr.chain, cdr.residue_index), f"{cdr.chain}:{cdr.residue_index + 1}"
                )
                target_ref = author_by_index.get(
                    (target.chain, target.residue_index),
                    f"{target.chain}:{target.residue_index + 1}",
                )
                contacts.add((cdr_ref, target_ref))
                target_contact_refs.add(target_ref)

    hotspot_distances: dict[str, float | None] = {}
    for original_ref, (chain, index) in sorted(hotspot_indices.items()):
        atoms = [a for a in target_atoms if a.chain == chain and a.residue_index == index]
        values = [float(np.linalg.norm(a.xyz - b.xyz)) for a in atoms for b in cdr_atoms]
        hotspot_distances[original_ref] = min(values) if values else None
    finite_distances = [value for value in hotspot_distances.values() if value is not None]

    target_ca = {
        key for key in predicted if key[0] in target_chains and key[2] == "CA" and key in reference
    }
    framework_ca = {
        key
        for key in predicted
        if key[0] in antibody_chains
        and key[2] == "CA"
        and (key[0], key[1]) not in design_indices
        and key in reference
    }
    antibody_ca = {key for key in predicted if key[0] in antibody_chains and key[2] == "CA"}
    cdr_ca = {key for key in antibody_ca if (key[0], key[1]) in design_indices}

    def alignment(keys):
        common = sorted(keys)
        if not common:
            return np.eye(3), np.zeros(3)
        return _transform(
            np.array([predicted[key] for key in common]),
            np.array([reference[key] for key in common]),
        )

    target_rotation, target_translation = alignment(target_ca)
    framework_rotation, framework_translation = alignment(framework_ca)
    per_cdr = {}
    for loop, refs in parent.cdr_positions.items():
        indices = {
            (ref.split(":", 1)[0], parent.sequence_index_by_author[ref])
            for ref in refs
            if ref in parent.sequence_index_by_author
        }
        keys = {key for key in antibody_ca if (key[0], key[1]) in indices}
        per_cdr[loop] = _rmsd(
            predicted, reference, keys, framework_rotation, framework_translation
        )

    covered = sum(
        value is not None and value <= contact_cutoff_angstrom for value in hotspot_distances.values()
    )
    return {
        "distance_unit": "angstrom",
        "contact_cutoff_angstrom": contact_cutoff_angstrom,
        "hotspot_to_cdr_min_distance": hotspot_distances,
        "cdr_target_contact_count": len(contacts),
        "cdr_target_contact_map": [list(item) for item in sorted(contacts)],
        "contacted_target_residues": sorted(target_contact_refs),
        "hotspot_coverage_fraction": covered / len(hotspot_distances) if hotspot_distances else None,
        "target_aligned_antibody_ca_rmsd": _rmsd(predicted, reference, antibody_ca, target_rotation, target_translation),
        "target_aligned_cdr_ca_rmsd": _rmsd(predicted, reference, cdr_ca, target_rotation, target_translation),
        "framework_aligned_antibody_ca_rmsd": _rmsd(predicted, reference, antibody_ca, framework_rotation, framework_translation),
        "framework_aligned_cdr_ca_rmsd": _rmsd(predicted, reference, cdr_ca, framework_rotation, framework_translation),
        "framework_aligned_per_cdr_ca_rmsd": per_cdr,
        "rfantibody_hotspot_min_distance": min(finite_distances) if finite_distances else None,
        "rfantibody_hotspot_average_distance": (
            sum(finite_distances) / len(finite_distances) if finite_distances else None
        ),
    }
