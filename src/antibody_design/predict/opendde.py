from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from antibody_design.design.base import AdapterNotReadyError, AdapterPlan, ExternalCommand

from .base import ParsedPrediction, PredictionRequest, StructurePredictor
from .io import missing_prediction_assets, parse_prediction_outputs


OPENDDE_COMMIT = "5028caae7f4a3c36b7eee848cab84c4c05492204"
OPENDDE_CHECKPOINT_SHA256 = "5cf37441ddef2a2f148b81dd4a218ad274f996fecaf17dec901ab6cf1351713d"
_COMMON_FILES = ("components.cif", "components.cif.rdkit_mol.pkl")
_TEMPLATE_FILES = ("release_date_cache.json", "obsolete_to_successor.json")


class OpenDDEAdapter(StructurePredictor):
    name = "opendde_v1"

    def plan(self, request: PredictionRequest) -> AdapterPlan:
        executable = str(request.options.get("executable", "opendde"))
        runtime_value = request.options.get("runtime_root")
        runtime = Path(runtime_value) if runtime_value else Path("{opendde_runtime_root}")
        checkpoint = Path(
            request.options.get("checkpoint_path", runtime / "checkpoint/opendde_abag.pt")
        )
        model_name = str(request.options.get("model_name", "opendde_v1"))
        use_msa = bool(request.options.get("use_msa", True))
        use_template = bool(request.options.get("use_template", False))
        missing: list[str] = []
        if shutil.which(executable) is None:
            missing.append(f"OpenDDE executable: {executable}")
        if model_name != "opendde_v1":
            missing.append("OpenDDE architecture/model_name must be opendde_v1")
        if not runtime_value:
            missing.append("runtime_root")
        if checkpoint.name != "opendde_abag.pt" or not checkpoint.is_file():
            missing.append(f"explicit opendde_abag.pt checkpoint: {checkpoint}")
        for filename in (*_COMMON_FILES, *(_TEMPLATE_FILES if use_template else ())):
            path = runtime / "common" / filename
            if not path.is_file():
                missing.append(f"preinstalled OpenDDE cache file: {path}")
        missing.extend(
            missing_prediction_assets(
                request.input_path,
                use_msa,
                use_template,
                runtime / "search_database/mmcif",
            )
        )

        output_dir = request.output_dir / request.candidate.candidate_id / f"seed_{request.seed}"
        confidence_policy = str(request.options.get("save_confidence_arrays", "none"))
        need_arrays = confidence_policy == "all"
        if confidence_policy == "top1":
            missing.append(
                "save_confidence_arrays=top1 is reserved but not safely supported by the job-level upstream flag"
            )
        argv = [
            executable, "pred",
            "-i", str(request.input_path),
            "-o", str(request.output_dir),
            "-s", str(request.seed),
            "-e", str(request.samples_per_seed),
            "-n", "opendde_v1",
            "--load_checkpoint_path", str(checkpoint),
            "--use_msa", str(use_msa).lower(),
            "--use_template", str(use_template).lower(),
            "--use_rna_msa", "false",
            "--need_atom_confidence", str(need_arrays).lower(),
        ]
        dtype = request.options.get("dtype")
        if dtype is not None:
            if dtype not in {"bf16", "fp32"}:
                raise ValueError("OpenDDE dtype must be bf16 or fp32")
            argv.extend(("--dtype", str(dtype)))
        for option in ("step", "cycle"):
            value = request.options.get(option)
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    raise ValueError(f"OpenDDE {option} must be a positive integer")
                argv.extend((f"--{option}", str(value)))
        command = ExternalCommand(
            argv=tuple(argv),
            env={"OPENDDE_ROOT_DIR": str(runtime)},
            ready=not missing,
            missing=tuple(missing),
        )
        return AdapterPlan(
            stage="fold",
            adapter=self.name,
            commands=(command,),
            expected_outputs=(str(output_dir),),
            notes=(
                f"OpenDDE source is pinned to commit {OPENDDE_COMMIT}.",
                "opendde_v1 is the architecture; opendde_abag.pt is selected only by explicit checkpoint path.",
                "dtype/step/cycle are forwarded only when explicitly configured; reduced counts are smoke-only.",
                "No hotspot, epitope, contact restraint, or RFdiffusion pose is supplied.",
            ),
            metadata={
                "input_path": request.input_path,
                "runtime_root": runtime,
                "checkpoint_path": checkpoint,
                "checkpoint_sha256": OPENDDE_CHECKPOINT_SHA256,
                "source_commit": OPENDDE_COMMIT,
            },
        )

    def parse_outputs(self, output_root: Path, job_name: str, seed: int) -> list[ParsedPrediction]:
        return parse_prediction_outputs(output_root, job_name, seed, self.name)

    def predict(self, request: PredictionRequest) -> list[ParsedPrediction]:
        plan = self.plan(request)
        command = plan.commands[0]
        if not command.ready:
            raise AdapterNotReadyError("OpenDDE is not ready: " + "; ".join(command.missing))
        Path(plan.expected_outputs[0]).mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(command.env)
        completed = subprocess.run(command.argv, env=environment, check=False)
        if completed.returncode != 0:
            raise AdapterNotReadyError(f"OpenDDE failed with exit code {completed.returncode}")
        return self.parse_outputs(request.output_dir, request.candidate.candidate_id, request.seed)
