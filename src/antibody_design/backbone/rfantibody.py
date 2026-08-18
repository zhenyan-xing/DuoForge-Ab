from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from antibody_design.design.base import AdapterPlan, ExternalCommand
from antibody_design.schemas import PipelineConfig


RFANTIBODY_COMMIT = "8fe311415754e0276d1a39c87c57e69c88927a2d"
DEFAULT_FRAMEWORK_RELATIVE = Path("scripts/examples/example_inputs/hu-4D5-8_Fv.pdb")


@dataclass(frozen=True)
class RFdiffusionRequest:
    config: PipelineConfig
    output_dir: Path
    expanded_hotspots: tuple[str, ...] = ()
    cautious_override: bool | None = None


def _frameworks(request: RFdiffusionRequest, root: Path) -> tuple[Path, ...]:
    inputs = request.config.input
    if inputs.framework_auto:
        return (root / DEFAULT_FRAMEWORK_RELATIVE,)
    return inputs.frameworks


def _missing_file(path: Path, label: str, missing: list[str]) -> None:
    if not path.is_file():
        missing.append(f"{label}: {path}")


def _launcher_env(executable: str) -> dict[str, str]:
    """Keep RFantibody's nested ``python`` call in the launcher's environment."""
    executable_path = Path(executable)
    if not executable_path.is_absolute():
        return {}
    return {
        "PATH": os.pathsep.join(
            (str(executable_path.parent), os.environ.get("PATH", ""))
        ).rstrip(os.pathsep)
    }


class RFantibodyAdapter:
    """Thin command adapter around the pinned RFantibody ``rfdiffusion`` CLI."""

    name = "rfantibody-rfdiffusion"

    def plan(self, request: RFdiffusionRequest) -> AdapterPlan:
        config = request.config
        options: Mapping[str, Any] = config.backbone.options
        root = Path(options.get("upstream_root", "{RFantibody_root}"))
        executable = str(options.get("executable", "rfdiffusion"))
        qvextract = str(options.get("qvextract_executable", "qvextract"))
        checkpoint = Path(options.get("checkpoint_path", "{rfdiffusion_checkpoint}"))
        target = config.input.target_structure
        assert target is not None
        missing: list[str] = []

        if not options.get("upstream_root") or not (root / "src/rfantibody").is_dir():
            missing.append(f"pinned RFantibody checkout at commit {RFANTIBODY_COMMIT}")
        _missing_file(target, "target_structure", missing)
        if config.input.input_quiver:
            if shutil.which(qvextract) is None:
                missing.append(f"RFantibody Quiver extractor: {qvextract}")
        else:
            if shutil.which(executable) is None:
                missing.append(f"RFantibody executable: {executable}")
            if not options.get("checkpoint_path"):
                missing.append("explicit RFdiffusion checkpoint_path")
            else:
                _missing_file(checkpoint, "RFdiffusion checkpoint", missing)

        output_prefix = request.output_dir / "parent"
        output_quiver_value = options.get("output_quiver")
        output_quiver = (
            Path(output_quiver_value) if output_quiver_value else None
        )
        commands: list[ExternalCommand] = []
        command_outputs: list[tuple[str, ...]] = []
        frameworks = _frameworks(request, root)
        if output_quiver and len(frameworks) > 1:
            missing.append("output_quiver currently requires exactly one framework")
        if output_quiver and shutil.which(qvextract) is None:
            missing.append(f"RFantibody Quiver extractor: {qvextract}")

        if config.input.input_quiver:
            quiver = config.input.input_quiver
            _missing_file(quiver, "input_quiver", missing)
            output_parents = request.output_dir / "parents"
            argv = (
                qvextract, str(quiver), "--output-dir", str(output_parents), "--force"
            )
            commands.append(
                ExternalCommand(
                    argv=argv,
                    cwd=root if options.get("upstream_root") else None,
                    ready=not missing,
                    missing=tuple(missing),
                )
            )
            command_outputs.append((str(output_parents / "*.pdb"),))
        else:
            for framework_index, framework in enumerate(frameworks):
                per_command_missing = list(missing)
                _missing_file(framework, "framework", per_command_missing)
                loops = []
                lengths = options.get("loop_lengths", {})
                for loop in config.design.loops:
                    value = lengths.get(loop, "") if isinstance(lengths, dict) else ""
                    loops.append(f"{loop}:{value}")
                argv: list[str] = [
                    executable,
                    "--target", str(target),
                    "--framework", str(framework),
                    "--num-designs", str(int(options.get("num_designs", 1))),
                    "--design-loops", ",".join(loops),
                    "--hotspots", "",
                ]
                # Hotspots are expanded during preparation and stored with author IDs.
                hotspot_values = request.expanded_hotspots or tuple(
                    f"{item.chain_id}{item.selector}" for item in config.hotspots
                )
                argv[-1] = ",".join(item.replace(":", "") for item in hotspot_values)
                if output_quiver:
                    argv.extend(("--output-quiver", str(output_quiver)))
                    expected_for_command = (str(output_quiver),)
                else:
                    prefix = output_prefix.with_name(
                        f"{output_prefix.name}_f{framework_index:02d}"
                    )
                    argv.extend(("--output", str(prefix)))
                    expected_for_command = (str(prefix.with_name(prefix.name + "_*.pdb")),)
                argv.extend(("--weights", str(checkpoint)))
                argv.extend(("--diffuser-t", str(int(options.get("diffuser_t", 50)))))
                argv.extend(("--final-step", str(int(options.get("final_step", 1)))))
                if bool(options.get("deterministic", True)):
                    argv.append("--deterministic")
                if bool(options.get("no_trajectory", True)):
                    argv.append("--no-trajectory")
                cautious = (
                    bool(options.get("cautious", True))
                    if request.cautious_override is None
                    else request.cautious_override
                )
                if cautious:
                    argv.extend(("--extra", "inference.cautious=True"))
                for override in options.get("extra", ()):
                    argv.extend(("--extra", str(override)))
                commands.append(
                    ExternalCommand(
                        argv=tuple(argv),
                        cwd=root if options.get("upstream_root") else None,
                        env=_launcher_env(executable),
                        ready=not per_command_missing,
                        missing=tuple(dict.fromkeys(per_command_missing)),
                    )
                )
                command_outputs.append(expected_for_command)

            if output_quiver:
                output_parents = request.output_dir / "parents"
                commands.append(
                    ExternalCommand(
                        argv=(
                            qvextract, str(output_quiver), "--output-dir", str(output_parents), "--force"
                        ),
                        cwd=root if options.get("upstream_root") else None,
                        ready=not missing,
                        missing=tuple(missing),
                    )
                )
                command_outputs.append((str(output_parents / "*.pdb"),))

        expected = (
            (str(request.output_dir / "parents" / "*.pdb"),)
            if output_quiver or config.input.input_quiver
            else (str(request.output_dir / "*.pdb"),)
        )
        return AdapterPlan(
            stage="backbone",
            adapter=self.name,
            commands=tuple(commands),
            expected_outputs=expected,
            notes=(
                f"RFantibody source is pinned to commit {RFANTIBODY_COMMIT}.",
                "Hotspots constrain RFdiffusion only; they are not forwarded as co-fold restraints.",
                "Every emitted PDB/Quiver tag becomes an independent Parent.",
            ),
            metadata={
                "source_commit": RFANTIBODY_COMMIT,
                "target_path": target,
                "frameworks": [str(path) for path in frameworks],
                "output_prefix": output_prefix,
                "output_quiver": output_quiver,
                "command_expected_outputs": [list(items) for items in command_outputs],
                "expected_parent_count": (
                    int(options.get("num_designs", 1)) * len(frameworks)
                    if not config.input.input_quiver
                    else None
                ),
            },
        )
