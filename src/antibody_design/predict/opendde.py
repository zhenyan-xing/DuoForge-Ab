from __future__ import annotations

import shutil
from pathlib import Path

from antibody_design.design.base import AdapterPlan, ExternalCommand

from .base import PredictionRequest, StructurePredictor


class OpenDDEAdapter(StructurePredictor):
    name = "opendde-abag"

    def plan(self, request: PredictionRequest) -> AdapterPlan:
        executable = str(request.options.get("executable", "opendde"))
        checkpoint_value = request.options.get("checkpoint_path")
        checkpoint = Path(checkpoint_value) if checkpoint_value else Path("{opendde_abag_ckpt}")
        input_path = request.input_path or Path("{candidate_input_json}")
        missing: list[str] = []
        if shutil.which(executable) is None:
            missing.append("OpenDDE executable")
        if not checkpoint_value or not checkpoint.is_file():
            missing.append("existing opendde_abag checkpoint_path")
        output_dir = request.output_dir / request.candidate.candidate_id
        command = ExternalCommand(
            argv=(
                executable,
                "pred",
                "-i",
                str(input_path),
                "-o",
                str(output_dir),
                "--load_checkpoint_path",
                str(checkpoint),
                "--seeds",
                str(request.seed),
                "--use_msa",
                str(request.options.get("use_msa", False)).lower(),
                "--use_template",
                str(request.options.get("use_template", False)).lower(),
                "--use_rna_msa",
                "false",
                "--sample",
                "1",
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
                "Uses the ABAG checkpoint explicitly; default checkpoint downloads are disabled.",
                "Execution and metric parsing are intentionally not implemented in v0.1.",
            ),
        )
