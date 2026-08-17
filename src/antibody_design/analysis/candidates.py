from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from antibody_design.design.base import SequenceProposal
from antibody_design.schemas import Candidate, GenerationRecord, Parent


class CandidateError(ValueError):
    pass


_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")
_N_GLYC = re.compile(r"N[^P][ST]")
_DEGRADATION = re.compile(r"(?:N[GST]|D[GSTP])")
_REPEAT = re.compile(r"(.)\1{3,}")
_HYDROPHOBIC = set("AILMFWVY")
_CHARGED = set("DEKR")


def _stable_id(prefix: str, *parts: object, length: int = 14) -> str:
    digest = hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()
    return f"{prefix}-{digest[:length]}"


def _chain_mutations(parent: Parent, heavy: str, light: str) -> tuple[str, ...]:
    if len(heavy) != len(parent.heavy_sequence):
        raise CandidateError("Candidate changes heavy-chain length in fixed-backbone mode")
    if len(light) != len(parent.light_sequence):
        raise CandidateError("Candidate changes light-chain length in fixed-backbone mode")
    mutations: list[str] = []
    for chain, before, after in (
        (parent.heavy_chain, parent.heavy_sequence, heavy),
        (parent.light_chain, parent.light_sequence, light),
    ):
        inverse = {
            index: ref
            for ref, index in parent.sequence_index_by_author.items()
            if ref.startswith(f"{chain}:")
        }
        for index, (old, new) in enumerate(zip(before, after)):
            if old != new:
                mutations.append(inverse.get(index, f"{chain}:{index + 1}"))
    return tuple(mutations)


def chemistry_liabilities(parent: Parent, heavy: str, light: str) -> tuple[str, ...]:
    """Report chemistry motifs; these annotations never filter candidates."""

    findings: list[str] = []
    for chain, before, after in (
        (parent.heavy_chain, parent.heavy_sequence, heavy),
        (parent.light_chain, parent.light_sequence, light),
    ):
        if after.count("C") > before.count("C"):
            findings.append(f"new_cysteine:{chain}")
        for match in _N_GLYC.finditer(after):
            findings.append(f"n_x_s_t:{chain}:{match.start() + 1}")
        for match in _DEGRADATION.finditer(after):
            findings.append(f"asn_asp_degradation:{chain}:{match.start() + 1}")
        for index, residue in enumerate(after):
            if residue in {"M", "W"}:
                findings.append(f"oxidation_residue:{chain}:{index + 1}:{residue}")
        for match in _REPEAT.finditer(after):
            findings.append(f"homopolymer:{chain}:{match.start() + 1}:{match.group(0)}")
        for index in range(max(0, len(after) - 6)):
            window = after[index : index + 7]
            if sum(aa in _HYDROPHOBIC for aa in window) >= 6:
                findings.append(f"hydrophobic_window:{chain}:{index + 1}")
            if sum(aa in _CHARGED for aa in window) >= 6:
                findings.append(f"charged_window:{chain}:{index + 1}")
    return tuple(dict.fromkeys(findings))


def merge_generation_proposals(
    parent: Parent,
    proposals_by_generator: Mapping[str, list[SequenceProposal]],
    unique_per_generator: int,
) -> tuple[list[Candidate], list[GenerationRecord], dict[str, int]]:
    """Select K unique sequences per generator, then merge across generators."""

    candidates_by_key: dict[tuple[str, str, str], Candidate] = {}
    generations: list[GenerationRecord] = []
    shortfalls: dict[str, int] = {}
    allowed = set(parent.designable_positions)

    for generator, proposals in proposals_by_generator.items():
        seen_for_generator: set[tuple[str, str]] = set()
        for proposal in proposals:
            heavy = proposal.heavy_sequence.upper()
            light = proposal.light_sequence.upper()
            invalid = set(heavy + light).difference(_ALPHABET)
            if invalid:
                raise CandidateError(
                    f"{generator} proposal contains unsupported residues: {sorted(invalid)}"
                )
            sequence_key = (heavy, light)
            if sequence_key in seen_for_generator:
                continue
            mutations = _chain_mutations(parent, heavy, light)
            outside = set(mutations).difference(allowed)
            if outside:
                refs = ", ".join(sorted(outside))
                raise CandidateError(f"Candidate mutates residues outside design mask: {refs}")

            seen_for_generator.add(sequence_key)
            key = (parent.parent_id, heavy, light)
            candidate = candidates_by_key.get(key)
            if candidate is None:
                candidate_id = _stable_id("cand", *key)
                candidate = Candidate(
                    candidate_id=candidate_id,
                    parent_id=parent.parent_id,
                    heavy_sequence=heavy,
                    light_sequence=light,
                    designed_positions=parent.designable_positions,
                    mutation_count=len(mutations),
                    sequence_cluster=_stable_id("exact", heavy, light, length=10),
                    liabilities=chemistry_liabilities(parent, heavy, light),
                )
                candidates_by_key[key] = candidate
            generations.append(
                GenerationRecord(
                    generation_id=_stable_id(
                        "gen", parent.parent_id, generator, proposal.seed, proposal.sample_index
                    ),
                    candidate_id=candidate.candidate_id,
                    parent_id=parent.parent_id,
                    generator=generator,
                    seed=proposal.seed,
                    sample_index=proposal.sample_index,
                    raw_metrics=dict(proposal.raw_metrics),
                    designed_positions=(
                        proposal.designed_positions or parent.designable_positions
                    ),
                )
            )
            if len(seen_for_generator) == unique_per_generator:
                break
        if len(seen_for_generator) < unique_per_generator:
            shortfalls[generator] = unique_per_generator - len(seen_for_generator)

    return list(candidates_by_key.values()), generations, shortfalls
