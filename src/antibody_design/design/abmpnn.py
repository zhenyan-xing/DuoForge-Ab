from __future__ import annotations

import shutil
from pathlib import Path

from .base import AdapterPlan, DesignRequest, ExternalCommand, SequenceDesigner


class AbMPNNAdapter(SequenceDesigner):
    """Dry-run adapter for AbMPNN through the official ProteinMPNN scripts."""

    name = "abmpnn"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        root_value = request.options.get("upstream_root")
        checkpoint_value = request.options.get("checkpoint_path")
        root = Path(root_value) if root_value else Path("{ProteinMPNN_root}")
        checkpoint = (
            Path(checkpoint_value) if checkpoint_value else Path("{abmpnn_checkpoint}.pt")
        )
        python = str(request.options.get("python_executable", "python"))
        missing: list[str] = []
        required_scripts = (
            root / "helper_scripts" / "parse_multiple_chains.py",
            root / "helper_scripts" / "assign_fixed_chains.py",
            root / "helper_scripts" / "make_fixed_positions_dict.py",
            root / "protein_mpnn_run.py",
        )
        if not root_value:
            missing.append("upstream_root")
        elif any(not path.is_file() for path in required_scripts):
            missing.append("ProteinMPNN scripts under upstream_root")
        if not checkpoint_value:
            missing.append("checkpoint_path")
        elif not checkpoint.is_file():
            missing.append("existing AbMPNN checkpoint_path")
        if shutil.which(python) is None:
            missing.append("python_executable")

        model_dir = request.prepared_dir / "abmpnn"
        input_dir = request.prepared_dir / "input_structure"
        parsed = model_dir / "parsed_pdbs.jsonl"
        assigned = model_dir / "assigned_pdbs.jsonl"
        fixed = model_dir / "fixed_positions.jsonl"
        designed_by_chain: dict[str, list[int]] = {}
        for ref in request.prepared.designable_positions:
            designed_by_chain.setdefault(ref.chain_id, []).append(
                request.prepared.sequence_index(ref) + 1
            )
        chains = " ".join(designed_by_chain)
        position_list = ", ".join(
            " ".join(str(index) for index in designed_by_chain[chain])
            for chain in designed_by_chain
        )
        ready = not missing

        def command(*argv: object) -> ExternalCommand:
            return ExternalCommand(
                argv=tuple(str(item) for item in argv),
                cwd=root if root_value else None,
                ready=ready,
                missing=tuple(missing),
            )

        commands = (
            command(
                python,
                required_scripts[0],
                "--input_path",
                input_dir,
                "--output_path",
                parsed,
            ),
            command(
                python,
                required_scripts[1],
                "--input_path",
                parsed,
                "--output_path",
                assigned,
                "--chain_list",
                chains,
            ),
            command(
                python,
                required_scripts[2],
                "--input_path",
                parsed,
                "--output_path",
                fixed,
                "--chain_list",
                chains,
                "--position_list",
                position_list,
                "--specify_non_fixed",
            ),
            command(
                python,
                required_scripts[3],
                "--jsonl_path",
                parsed,
                "--chain_id_jsonl",
                assigned,
                "--fixed_positions_jsonl",
                fixed,
                "--out_folder",
                request.output_dir,
                "--path_to_model_weights",
                checkpoint.parent,
                "--model_name",
                checkpoint.stem,
                "--num_seq_per_target",
                request.num_sequences,
                "--sampling_temp",
                request.options.get("temperature", 0.1),
                "--seed",
                request.seed,
                "--batch_size",
                request.options.get("batch_size", 1),
                "--omit_AAs",
                request.options.get("omit_aas", "CX"),
            ),
        )
        return AdapterPlan(
            stage="design",
            adapter=self.name,
            commands=commands,
            expected_outputs=(str(request.output_dir / "seqs"),),
            notes=(
                "Uses AbMPNN weights with the official ProteinMPNN runner.",
                "Execution and FASTA parsing are intentionally not implemented in v0.1.",
            ),
        )
