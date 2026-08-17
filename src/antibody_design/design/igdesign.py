from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

import yaml

from .base import (
    AdapterNotReadyError,
    AdapterPlan,
    DesignRequest,
    ExternalCommand,
    SequenceDesigner,
    SequenceProposal,
)


IGDESIGN_COMMIT = "70431eef0afaf0496d7d84e22dfdc1980ec9e70e"
_LOOP_TO_REGION = {
    "H1": "hcdr1", "H2": "hcdr2", "H3": "hcdr3",
    "L1": "lcdr1", "L2": "lcdr2", "L3": "lcdr3",
}


def _regions(parent) -> dict[str, dict]:
    allowed = set(parent.designable_positions)
    result: dict[str, dict] = {}
    covered: set[str] = set()
    for loop, refs in parent.cdr_positions.items():
        selected = [ref for ref in refs if ref in allowed]
        if selected:
            name = _LOOP_TO_REGION[loop]
            result[name] = {
                "chain": "heavy" if loop.startswith("H") else "light",
                "positions": [parent.sequence_index_by_author[ref] for ref in selected],
            }
            covered.update(selected)
    for role, chain in (("heavy", parent.heavy_chain), ("light", parent.light_chain)):
        selected = sorted(
            allowed.difference(covered).intersection(
                ref for ref in parent.sequence_index_by_author if ref.startswith(f"{chain}:")
            ),
            key=parent.sequence_index_by_author.__getitem__,
        )
        if selected:
            result[f"duoforge_{role}"] = {
                "chain": role,
                "positions": [parent.sequence_index_by_author[ref] for ref in selected],
            }
    return result


def _number(value: str):
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_igdesign_csv(
    path: Path,
    heavy_sequence: str,
    light_sequence: str,
    regions: Mapping[str, tuple[str, tuple[int, ...]] | Mapping],
    seed: int,
) -> list[SequenceProposal]:
    proposals: list[SequenceProposal] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for sample_index, row in enumerate(csv.DictReader(handle)):
            heavy = list(heavy_sequence)
            light = list(light_sequence)
            for name, specification in regions.items():
                if isinstance(specification, Mapping):
                    chain = str(specification["chain"])
                    positions = tuple(int(value) for value in specification["positions"])
                else:
                    chain, positions = specification
                sequence = row.get(name, "")
                if len(sequence) != len(positions):
                    raise ValueError(
                        f"IgDesign output region {name} has length {len(sequence)}, expected {len(positions)}"
                    )
                destination = heavy if chain == "heavy" else light
                for index, residue in zip(positions, sequence):
                    destination[index] = residue
            metrics = {
                key: _number(value)
                for key, value in row.items()
                if key not in regions and value not in {None, ""}
            }
            proposals.append(
                SequenceProposal(
                    "".join(heavy), "".join(light), seed, sample_index, metrics
                )
            )
    return proposals


class IgDesignAdapter(SequenceDesigner):
    name = "igdesign"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        root_value = request.options.get("upstream_root")
        root = Path(root_value) if root_value else Path("{IgDesign_root}")
        lmdesign = Path(request.options.get("lmdesign_checkpoint", "{igdesign_checkpoint}"))
        pmpnn = Path(request.options.get("pmpnn_checkpoint", "{igmpnn_checkpoint}"))
        python = str(request.options.get("python_executable", "python"))
        runner = Path(__file__).resolve().parents[3] / "scripts/igdesign_multichain_runner.py"
        regions = _regions(request.parent)
        missing: list[str] = []
        if not root_value or not (root / "src/igdesign").is_dir():
            missing.append(f"pinned IgDesign checkout at commit {IGDESIGN_COMMIT}")
        if not request.options.get("lmdesign_checkpoint") or not lmdesign.is_file():
            missing.append("existing lmdesign_checkpoint")
        if not request.options.get("pmpnn_checkpoint") or not pmpnn.is_file():
            missing.append("existing pmpnn_checkpoint")
        if shutil.which(python) is None:
            missing.append(f"python executable: {python}")
        if not runner.is_file():
            missing.append(f"project IgDesign runner: {runner}")
        if not regions:
            missing.append("non-empty mapped design mask (run prepare with ANARCI)")

        commands: list[ExternalCommand] = []
        output_files: list[str] = []
        for seed in request.seeds:
            output_csv = request.output_dir / f"seed_{seed}" / "candidates.csv"
            config_path = request.prepared_dir / "igdesign" / f"seed_{seed}.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            epitopes: dict[str, dict[str, list[int]]] = {}
            for chain in request.parent.target_chains:
                positions = [
                    request.parent.sequence_index_by_author.get(ref, -1)
                    for ref in request.parent.hotspots
                    if ref.startswith(f"{chain}:")
                ]
                positions = [position for position in positions if position >= 0]
                if positions:
                    epitopes[chain] = {"indices": positions}
            payload = {
                "source_commit": IGDESIGN_COMMIT,
                "upstream_root": str(root),
                "structure_path": str(request.parent.structure_path),
                "lmdesign_checkpoint": str(lmdesign),
                "pmpnn_checkpoint": str(pmpnn),
                "save_path": str(output_csv),
                "heavy_chain_id": request.parent.heavy_chain,
                "light_chain_id": request.parent.light_chain,
                "antigen_chain_ids": list(request.parent.target_chains),
                "epitopes": epitopes,
                "regions": regions,
                "region_order": list(regions),
                "condition_on_light_chain": not any(item["chain"] == "light" for item in regions.values()),
                "condition_on_antigen": True,
                "predict_light_chain": any(item["chain"] == "light" for item in regions.values()),
                "batch_size": 1,
                "num_batches": int(request.options.get("proposal_batches", 1)),
                "lmdesign_num_decoding_orders": int(request.options.get("decoding_orders", 1)),
                "lmdesign_num_pmpnn_seqs": int(request.options.get("pmpnn_sequences", request.proposal_budget)),
                "lmdesign_num_lm_seqs": int(request.options.get("lm_sequences", 1)),
                "lmdesign_pmpnn_logit_temperature": float(request.options.get("pmpnn_temperature", 0.5)),
                "lmdesign_output_logit_temperature": float(request.options.get("output_temperature", 0.5)),
                "independent_loss": bool(request.options.get("independent_loss", True)),
                "random_seed": seed,
            }
            config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            commands.append(
                ExternalCommand(
                    argv=(python, str(runner), "--config", str(config_path)),
                    cwd=root if root_value else None,
                    ready=not missing,
                    missing=tuple(missing),
                )
            )
            output_files.append(str(output_csv))
        return AdapterPlan(
            stage="sequence-design",
            adapter=self.name,
            commands=tuple(commands),
            expected_outputs=tuple(output_files),
            notes=(
                f"IgDesign source is pinned to commit {IGDESIGN_COMMIT}.",
                "The project runner uses PdbAntibodyDataset with every target chain; this path requires validation with real weights.",
                "Region positions are zero-based chain-local indices from the shared ANARCI mapping.",
            ),
            metadata={"regions": regions, "proposal_budget_per_seed": request.proposal_budget},
        )

    def generate(self, request: DesignRequest) -> list[SequenceProposal]:
        plan = self.plan(request)
        proposals: list[SequenceProposal] = []
        for seed, command, output in zip(request.seeds, plan.commands, plan.expected_outputs):
            if not command.ready:
                raise AdapterNotReadyError("IgDesign is not ready: " + "; ".join(command.missing))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(command.argv, cwd=command.cwd, check=False)
            if completed.returncode != 0:
                raise AdapterNotReadyError(f"IgDesign failed with exit code {completed.returncode}")
            proposals.extend(
                parse_igdesign_csv(
                    Path(output),
                    request.parent.heavy_sequence,
                    request.parent.light_sequence,
                    plan.metadata["regions"],
                    seed,
                )
            )
        return proposals
