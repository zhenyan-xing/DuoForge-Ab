from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from pathlib import Path

from .base import (
    AdapterNotReadyError,
    AdapterPlan,
    CapabilityError,
    DesignRequest,
    ExternalCommand,
    SequenceDesigner,
    SequenceProposal,
)


ANTIFOLD_COMMIT = "789d46786624c01eb44f177ef4c0deeeb6e77469"


def _number(value: str):
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_antifold_csv(path: Path, seed: int) -> list[SequenceProposal]:
    proposals: list[SequenceProposal] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row_number, row in enumerate(csv.DictReader(handle)):
            sample_index = int(row.pop("sample_index", row_number))
            heavy = row.pop("heavy_sequence")
            light = row.pop("light_sequence")
            metrics = {}
            for key, value in row.items():
                if value in {None, ""}:
                    continue
                try:
                    metrics[key] = float(value)
                except ValueError:
                    metrics[key] = value
            proposals.append(
                SequenceProposal(heavy, light, seed, sample_index, metrics)
            )
    return proposals


def parse_antifold_fasta(path: Path, seed: int) -> list[SequenceProposal]:
    """Parse official AntiFold H/L FASTA; omit its leading reference sequence."""

    records: list[tuple[str, str]] = []
    header = ""
    sequence: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            if header:
                records.append((header, "".join(sequence)))
            header, sequence = line[1:], []
        else:
            sequence.append(line.strip())
    if header:
        records.append((header, "".join(sequence)))

    proposals: list[SequenceProposal] = []
    for header, sequence in records:
        metrics = {}
        for match in re.finditer(r"([A-Za-z_]+)=([^, ]+)", header):
            metrics[match.group(1)] = _number(match.group(2))
        if "sample" not in metrics:
            continue
        if "/" not in sequence:
            raise ValueError("AntiFold paired H/L FASTA sequence lacks '/' separator")
        heavy, light = sequence.split("/", 1)
        proposals.append(
            SequenceProposal(
                heavy,
                light,
                seed,
                int(metrics["sample"]) - 1,
                metrics,
            )
        )
    return proposals


def _imgt_design_mask(request: DesignRequest) -> dict[str, list[str]]:
    mapping_path = request.parent.numbering_map_path
    if not mapping_path or not mapping_path.is_file():
        return {}
    by_author: dict[str, str] = {}
    for line in mapping_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        by_author[f"{item['chain_id']}:{item['author_residue_id']}"] = str(
            item["imgt_residue_id"]
        )
    missing = set(request.parent.designable_positions).difference(by_author)
    if missing:
        raise CapabilityError(
            "AntiFold exact design mask lacks IMGT mappings for: " + ", ".join(sorted(missing))
        )
    result = {request.parent.heavy_chain: [], request.parent.light_chain: []}
    for ref in request.parent.designable_positions:
        chain = ref.split(":", 1)[0]
        result[chain].append(by_author[ref])
    return result


class AntiFoldAdapter(SequenceDesigner):
    name = "antifold"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        root_value = request.options.get("upstream_root")
        root = Path(root_value) if root_value else Path("{AntiFold_root}")
        checkpoint = Path(request.options.get("checkpoint_path", "{antifold_checkpoint}"))
        python = str(request.options.get("python_executable", "python"))
        runner = Path(__file__).resolve().parents[3] / "scripts/antifold_exact_mask_runner.py"
        imgt = request.parent.imgt_structure_path
        mask = _imgt_design_mask(request)
        missing: list[str] = []
        if not root_value or not (root / "antifold/antiscripts.py").is_file():
            missing.append(f"pinned AntiFold checkout at commit {ANTIFOLD_COMMIT}")
        if not request.options.get("checkpoint_path") or not checkpoint.is_file():
            missing.append("existing AntiFold checkpoint_path")
        if shutil.which(python) is None:
            missing.append(f"python executable: {python}")
        if not imgt or not imgt.is_file():
            missing.append("IMGT-numbered complex from prepare/ANARCI")
        if not mask:
            missing.append("exact IMGT design mask from prepare/ANARCI")

        commands: list[ExternalCommand] = []
        outputs: list[str] = []
        for seed in request.seeds:
            output_csv = request.output_dir / f"seed_{seed}" / "candidates.csv"
            config_path = request.prepared_dir / "antifold" / f"seed_{seed}.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "source_commit": ANTIFOLD_COMMIT,
                "upstream_root": str(root),
                "checkpoint_path": str(checkpoint),
                "pdb_path": str(imgt or request.parent.structure_path),
                "heavy_chain": request.parent.heavy_chain,
                "light_chain": request.parent.light_chain,
                "target_chains": list(request.parent.target_chains),
                "design_imgt_positions": mask,
                "temperature": float(request.options.get("temperature", 0.2)),
                "num_samples": request.proposal_budget,
                "seed": seed,
                "output_csv": str(output_csv),
                "raw_output_dir": str(request.output_dir / f"seed_{seed}" / "raw"),
            }
            config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            commands.append(
                ExternalCommand(
                    argv=(python, str(runner), "--config", str(config_path)),
                    cwd=root if root_value else None,
                    ready=not missing,
                    missing=tuple(missing),
                )
            )
            outputs.append(str(output_csv))
        return AdapterPlan(
            stage="sequence-design",
            adapter=self.name,
            commands=tuple(commands),
            expected_outputs=tuple(outputs),
            notes=(
                f"AntiFold source is pinned to commit {ANTIFOLD_COMMIT}.",
                "The runner loads the explicit checkpoint and never calls AntiFold's auto-download path.",
                "Exact positions are sampled from official per-residue logits; target chains remain structural context.",
            ),
            metadata={"design_imgt_positions": mask, "proposal_budget_per_seed": request.proposal_budget},
        )

    def generate(self, request: DesignRequest) -> list[SequenceProposal]:
        plan = self.plan(request)
        proposals: list[SequenceProposal] = []
        for seed, command, output in zip(request.seeds, plan.commands, plan.expected_outputs):
            if not command.ready:
                raise AdapterNotReadyError("AntiFold is not ready: " + "; ".join(command.missing))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(command.argv, cwd=command.cwd, check=False)
            if completed.returncode != 0:
                raise AdapterNotReadyError(f"AntiFold failed with exit code {completed.returncode}")
            proposals.extend(parse_antifold_csv(Path(output), seed))
        return proposals
