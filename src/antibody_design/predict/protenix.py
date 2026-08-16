from __future__ import annotations

import shutil
from pathlib import Path

from antibody_design.design.base import AdapterPlan, ExternalCommand

from .base import PredictionRequest, StructurePredictor


class ProtenixAdapter(StructurePredictor):
    name = "protenix-v2"

    def plan(self, request: PredictionRequest) -> AdapterPlan:
        executable = str(request.options.get("executable", "protenix"))
        checkpoint_value = request.options.get("checkpoint_path")
        checkpoint = Path(checkpoint_value) if checkpoint_value else Path("{protenix_v2_ckpt}")
        input_path = request.input_path or Path("{candidate_input_json}")
        missing: list[str] = []
        if shutil.which(executable) is None:
            missing.append("Protenix executable")
        if not checkpoint_value or not checkpoint.is_file():
            missing.append("existing checkpoint_path (prevents automatic download)")
        output_dir = request.output_dir / request.candidate.candidate_id
        command = ExternalCommand(
            argv=(
                executable,
                "pred",
                "-i",
                str(input_path),
                "-o",
                str(output_dir),
                "-s",
                str(request.seed),
                "-n",
                str(request.options.get("model_name", "protenix-v2")),
                "--load_checkpoint_path",
                str(checkpoint),
                "--use_msa",
                str(request.options.get("use_msa", False)).lower(),
                "--use_template",
                str(request.options.get("use_template", False)).lower(),
                "--use_default_params",
                "true",
            ),
            ready=not missing,
            missing=tuple(missing),
        )
        return AdapterPlan(
            stage="predict",
            adapter=self.name,
            commands=(command,),
            expected_outputs=(str(output_dir),),
            notes=(
                "The candidate input is an AlphaFold3-style sequence-complex JSON.",
                "Execution and metric parsing are intentionally not implemented in v0.1.",
            ),
        )
