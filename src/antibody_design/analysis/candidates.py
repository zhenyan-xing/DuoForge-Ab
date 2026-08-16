from __future__ import annotations

import re
from dataclasses import replace

from antibody_design.design.base import GeneratedSequence
from antibody_design.schemas import Candidate, PreparedComplex, ResidueRef


class CandidateError(ValueError):
    pass


_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")
_N_GLYC = re.compile(r"N[^P][ST]")


def _mutation_refs(
    prepared: PreparedComplex, heavy_sequence: str, light_sequence: str
) -> tuple[ResidueRef, ...]:
    mutations: list[ResidueRef] = []
    chain_pairs = (
        (prepared.chains.heavy, prepared.heavy_sequence, heavy_sequence),
        (prepared.chains.light, prepared.light_sequence, light_sequence),
    )
    for chain_id, parent, candidate in chain_pairs:
        if len(parent) != len(candidate):
            raise CandidateError(f"Candidate changes {chain_id} chain length")
        residues = prepared.residues_by_chain[chain_id]
        mutations.extend(
            residues[index].ref
            for index, (before, after) in enumerate(zip(parent, candidate))
            if before != after
        )
    return tuple(mutations)


def _new_motif_starts(parent: str, candidate: str) -> set[int]:
    return {match.start() for match in _N_GLYC.finditer(candidate)}.difference(
        match.start() for match in _N_GLYC.finditer(parent)
    )


def _liabilities(prepared: PreparedComplex, heavy: str, light: str) -> tuple[str, ...]:
    findings: list[str] = []
    for chain_id, parent, candidate in (
        (prepared.chains.heavy, prepared.heavy_sequence, heavy),
        (prepared.chains.light, prepared.light_sequence, light),
    ):
        for index in sorted(_new_motif_starts(parent, candidate)):
            findings.append(f"new_n_glycosylation:{chain_id}:{index + 1}")
        if candidate.count("C") > parent.count("C"):
            findings.append(f"new_cysteine:{chain_id}")
    return tuple(findings)


def normalize_candidates(
    prepared: PreparedComplex,
    generator: str,
    seed: int,
    generated: list[GeneratedSequence],
) -> list[Candidate]:
    """Normalize and de-duplicate exact sequences within one generator source."""

    allowed_positions = set(prepared.designable_positions)
    seen: set[tuple[str, str]] = set()
    candidates: list[Candidate] = []
    for item in generated:
        heavy = item.heavy_sequence.upper()
        light = item.light_sequence.upper()
        invalid = set(heavy + light).difference(_ALPHABET)
        if invalid:
            raise CandidateError(f"Candidate contains unsupported amino acids: {sorted(invalid)}")
        key = (heavy, light)
        if key in seen:
            continue
        mutations = _mutation_refs(prepared, heavy, light)
        outside_mask = set(mutations).difference(allowed_positions)
        if outside_mask:
            refs = ", ".join(sorted(str(ref) for ref in outside_mask))
            raise CandidateError(f"Candidate mutates residues outside design mask: {refs}")
        seen.add(key)
        candidates.append(
            Candidate(
                candidate_id=(
                    f"{prepared.parent_id}__{generator}__s{seed}__{len(candidates) + 1:04d}"
                ),
                parent_id=prepared.parent_id,
                generator=generator,
                heavy_sequence=heavy,
                light_sequence=light,
                designed_positions=tuple(str(ref) for ref in prepared.designable_positions),
                mutation_count=len(mutations),
                sequence_cluster="",
                seed=seed,
                generation_metrics=dict(item.raw_metrics),
                liabilities=_liabilities(prepared, heavy, light),
            )
        )
    return candidates


def assign_sequence_clusters(candidates: list[Candidate]) -> list[Candidate]:
    """Assign stable exact-sequence clusters without merging generator provenance."""

    clusters: dict[tuple[str, str], str] = {}
    assigned: list[Candidate] = []
    for candidate in candidates:
        key = (candidate.heavy_sequence, candidate.light_sequence)
        cluster = clusters.setdefault(key, f"exact-{len(clusters) + 1:04d}")
        assigned.append(replace(candidate, sequence_cluster=cluster))
    return assigned
