from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from antibody_design.schemas import ResidueRef

from .base import AdapterPlan, DesignRequest, ExternalCommand, SequenceDesigner


class IgDesignAdapter(SequenceDesigner):
    """Dry-run adapter for the official AbSciBio IgDesign entrypoint."""

    name = "igdesign"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        root_value = request.options.get("upstream_root")
        root = Path(root_value) if root_value else Path("{IgDesign_root}")
        entrypoint = root / "predict.py"
        lmdesign_value = request.options.get("lmdesign_checkpoint")
        pmpnn_value = request.options.get("pmpnn_checkpoint")
        lmdesign = Path(lmdesign_value) if lmdesign_value else Path("{igdesign_ckpt}")
        pmpnn = Path(pmpnn_value) if pmpnn_value else Path("{igmpnn_ckpt}")
        python = str(request.options.get("python_executable", "python"))
        raw_regions = request.options.get("regions")
        missing: list[str] = []
        if not root_value or not entrypoint.is_file():
            missing.append("upstream_root containing predict.py")
        if not lmdesign_value or not lmdesign.is_file():
            missing.append("existing lmdesign_checkpoint")
        if not pmpnn_value or not pmpnn.is_file():
            missing.append("existing pmpnn_checkpoint")
        if not isinstance(raw_regions, dict) or not raw_regions:
            missing.append("regions mapping from IgDesign region names to residue refs")
            raw_regions = {}
        if len(request.prepared.chains.antigen) != 1:
            missing.append("single antigen chain for current IgDesign adapter")
        if shutil.which(python) is None:
            missing.append("python_executable")

        regions: dict[str, dict] = {}
        covered: set[ResidueRef] = set()
        for name, values in raw_regions.items():
            refs = [ResidueRef.parse(value) for value in values]
            chains = {ref.chain_id for ref in refs}
            if len(chains) != 1 or not chains:
                missing.append(f"one chain per IgDesign region ({name})")
                continue
            chain_id = next(iter(chains))
            if chain_id == request.prepared.chains.heavy:
                chain_role = "heavy"
            elif chain_id == request.prepared.chains.light:
                chain_role = "light"
            else:
                missing.append(f"antibody residues only in IgDesign region ({name})")
                continue
            covered.update(refs)
            regions[str(name)] = {
                "positions": [request.prepared.sequence_index(ref) for ref in refs],
                "chain": chain_role,
            }
        if covered != set(request.prepared.designable_positions):
            missing.append("IgDesign regions exactly covering the global design mask")

        output_csv = request.output_dir / "candidates.csv"
        adapter_config = request.prepared_dir / "igdesign" / "adapter_config.yaml"
        antigen_chain = request.prepared.chains.antigen[0]
        epitope_indices = [
            request.prepared.sequence_index(ref)
            for ref in request.prepared.epitope_positions
            if ref.chain_id == antigen_chain
        ]
        has_light_design = any(region["chain"] == "light" for region in regions.values())
        payload = {
            "structure_path": str(request.prepared.input_structure),
            "lmdesign_checkpoint": str(lmdesign),
            "pmpnn_checkpoint": str(pmpnn),
            "save_path": str(output_csv),
            "region_order": list(regions),
            "lmdesign_num_decoding_orders": 1,
            "lmdesign_num_pmpnn_seqs": 1,
            "lmdesign_num_lm_seqs": 1,
            "lmdesign_pmpnn_logit_temperature": request.options.get(
                "pmpnn_temperature", 0.5
            ),
            "lmdesign_output_logit_temperature": request.options.get(
                "output_temperature", 0.5
            ),
            "independent_loss": True,
            "condition_on_light_chain": not has_light_design,
            "condition_on_antigen": True,
            "predict_light_chain": has_light_design,
            "num_batches": request.num_sequences,
            "random_seed": request.seed,
            "epitope_idxs_or_all": epitope_indices,
            "antigen_chain_id": antigen_chain,
            "heavy_chain_id": request.prepared.chains.heavy,
            "light_chain_id": request.prepared.chains.light,
            "regions": regions,
        }
        adapter_config.parent.mkdir(parents=True, exist_ok=True)
        adapter_config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        ready = not missing
        command = ExternalCommand(
            argv=(python, str(entrypoint), "--config_name", str(adapter_config)),
            cwd=root if root_value else None,
            ready=ready,
            missing=tuple(dict.fromkeys(missing)),
        )
        return AdapterPlan(
            stage="design",
            adapter=self.name,
            commands=(command,),
            expected_outputs=(str(output_csv),),
            notes=(
                "IgDesign positions are translated to zero-based chain sequence indices.",
                "Execution and CSV parsing are intentionally not implemented in v0.1.",
            ),
        )
