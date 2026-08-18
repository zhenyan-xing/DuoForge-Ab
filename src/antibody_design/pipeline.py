from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from .analysis.candidates import merge_generation_proposals
from .analysis.geometry import compute_geometry
from .analysis.report import write_markdown_report, write_records, write_summary
from .backbone import RFantibodyAdapter, RFdiffusionRequest
from .design.abmpnn import AbMPNNAdapter
from .design.antifold import AntiFoldAdapter, parse_antifold_csv
from .design.antibmpnn import AntiBMPNNAdapter
from .design.base import AdapterPlan, DesignRequest, ExternalCommand, SequenceDesigner
from .design.igdesign import IgDesignAdapter, parse_igdesign_csv
from .predict.base import PredictionRequest, StructurePredictor
from .predict.io import write_prediction_input
from .predict.opendde import OpenDDEAdapter
from .predict.protenix import ProtenixAdapter
from .prepare import (
    expand_hotspots,
    prepare_parent,
    read_pdb,
    restore_rfantibody_target_chains,
    write_prepared_complex,
)
from .schemas import (
    Candidate,
    GenerationRecord,
    Parent,
    PipelineConfig,
    PredictionJob,
    PredictionRecord,
    record_dict,
)


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class PipelineResult:
    parents: tuple[Parent, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    generations: tuple[GenerationRecord, ...] = ()
    predictions: tuple[PredictionRecord, ...] = ()
    manifest_path: Path | None = None
    plan_path: Path | None = None
    status: str = "complete"
    exit_code: int = 0


def expand_prediction_jobs(
    candidates: list[Candidate],
    seeds: tuple[int, ...],
    samples_per_seed: int,
    predictor_names: tuple[str, ...],
) -> list[PredictionJob]:
    return [
        PredictionJob(candidate.candidate_id, predictor, seed, samples_per_seed)
        for candidate in candidates
        for predictor in predictor_names
        for seed in seeds
    ]


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()
    return f"{prefix}-{digest[:14]}"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise PipelineError(f"Required prior-stage record is missing: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _load_parents(run_dir: Path) -> list[Parent]:
    parents = []
    for item in _read_jsonl(run_dir / "parents.jsonl"):
        for key in ("structure_path", "numbering_map_path", "imgt_structure_path", "chain_map_path"):
            if item.get(key):
                path = Path(item[key])
                item[key] = path if path.is_absolute() else run_dir / path
        for key in ("target_chains", "designable_positions", "fixed_positions", "hotspots"):
            item[key] = tuple(item.get(key, ()))
        item["cdr_positions"] = {
            key: tuple(value) for key, value in item.get("cdr_positions", {}).items()
        }
        parents.append(Parent(**item))
    return parents


def _load_candidates(run_dir: Path) -> list[Candidate]:
    candidates = []
    for item in _read_jsonl(run_dir / "candidates.jsonl"):
        for key in ("designed_positions", "liabilities"):
            item[key] = tuple(item.get(key, ()))
        candidates.append(Candidate(**item))
    return candidates


def _load_generations(run_dir: Path) -> list[GenerationRecord]:
    records = []
    for item in _read_jsonl(run_dir / "generations.jsonl"):
        item["designed_positions"] = tuple(item.get("designed_positions", ()))
        records.append(GenerationRecord(**item))
    return records


def _model_options(config: PipelineConfig, name: str) -> dict:
    options = dict(config.predictors[name].options)
    options["use_msa"] = config.msa.mode != "none"
    options["use_template"] = bool(
        config.templates.target_hits or config.templates.antibody_hits
    )
    options["save_confidence_arrays"] = config.run.save_confidence_arrays
    return options


def _run_metadata(config: PipelineConfig) -> dict:
    return {
        "run_id": config.run.run_id,
        "mode": config.mode,
        "config_path": "prepared/provenance/config.yaml",
        "seeds": list(config.run.seeds),
        "samples_per_seed": config.run.samples_per_seed,
        "save_confidence_arrays": config.run.save_confidence_arrays,
        "enabled_generators": [
            name for name, model in config.generators.items() if model.enabled
        ],
        "enabled_predictors": [
            name for name, model in config.predictors.items() if model.enabled
        ],
        "model_manifest": "prepared/provenance/model_manifest.yaml",
    }


def _expanded_target_hotspots(config: PipelineConfig) -> tuple[str, ...]:
    target = config.input.target_structure
    assert target is not None
    residues = read_pdb(target)
    missing = [chain for chain in config.chains.target if chain not in residues]
    if missing:
        raise PipelineError(
            f"Target chains not found in {target}: {', '.join(missing)}"
        )
    return tuple(str(item) for item in expand_hotspots(config, residues))


def _snapshot_run_provenance(config: PipelineConfig) -> None:
    provenance_dir = config.run.output_dir / "prepared/provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config.config_path, provenance_dir / "config.yaml")
    model_manifest = Path(__file__).resolve().parents[2] / "models/manifest.yaml"
    if not model_manifest.is_file():
        raise PipelineError(f"Required model manifest is missing: {model_manifest}")
    shutil.copy2(model_manifest, provenance_dir / "model_manifest.yaml")


def _required_complete(paths: tuple[str, ...]) -> bool:
    for value in paths:
        if "*" in value:
            parent = Path(value).parent
            if not parent.is_dir() or not list(parent.glob(Path(value).name)):
                return False
        else:
            path = Path(value)
            if not path.exists() or (path.is_dir() and not any(path.iterdir())):
                return False
    return True


def _assign_model_top1(
    records: list[PredictionRecord], seeds: tuple[int, ...]
) -> list[PredictionRecord]:
    seed_order = {seed: index for index, seed in enumerate(seeds)}
    grouped: dict[tuple[str, str], list[int]] = {}
    for index, record in enumerate(records):
        grouped.setdefault((record.candidate_id, record.prediction_model), []).append(index)
    selected: set[int] = set()
    for indices in grouped.values():
        score_field = (
            "final_score"
            if any(
                isinstance(records[index].raw_metrics.get("final_score"), (int, float))
                for index in indices
            )
            else "ranking_score"
        )

        def order(index: int):
            record = records[index]
            native = record.raw_metrics.get(score_field)
            if isinstance(native, (int, float)):
                return (1, float(native), -seed_order.get(record.seed, 10**6), -record.sample_index)
            return (0, 0.0, -seed_order.get(record.seed, 10**6), -record.sample_index)

        selected.add(max(indices, key=order))
    return [replace(record, is_model_top1=index in selected) for index, record in enumerate(records)]


class _JobStore:
    def __init__(self, run_dir: Path, resume: bool) -> None:
        self.run_dir = run_dir
        self.resume = resume
        self.jobs_dir = run_dir / "logs/jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _write(self, job_id: str, payload: dict) -> None:
        self._path(job_id).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _gpu_used_memory_mib() -> int | None:
        if os.environ.get("DUOFORGE_GPU_TELEMETRY") != "1":
            return None
        for query, aggregate in (
            ("--query-compute-apps=used_memory", sum),
            ("--query-gpu=memory.used", max),
        ):
            try:
                completed = subprocess.run(
                    ["nvidia-smi", query, "--format=csv,noheader,nounits"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            if completed.returncode != 0:
                continue
            values = [
                int(line.strip())
                for line in completed.stdout.splitlines()
                if line.strip().isdigit()
            ]
            if values:
                return aggregate(values)
        return None

    @staticmethod
    def _log_reports_oom(path: Path) -> bool:
        if not path.is_file():
            return False
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 1024 * 1024))
            tail = handle.read().decode("utf-8", errors="replace").lower()
        return "out of memory" in tail and ("cuda" in tail or "gpu" in tail)

    def may_skip(self, job_id: str, required: tuple[str, ...]) -> bool:
        path = self._path(job_id)
        if not self.resume or not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("status") == "complete" and _required_complete(required)

    def execute(self, job_id: str, command: ExternalCommand, required: tuple[str, ...]) -> bool:
        if self.may_skip(job_id, required):
            return True
        log_path = self.run_dir / "logs" / f"{job_id}.log"
        state_path = self._path(job_id)
        previous = (
            json.loads(state_path.read_text(encoding="utf-8"))
            if state_path.is_file()
            else {}
        )
        payload = {
            "job_id": job_id,
            "status": "pending",
            "status_history": [*previous.get("status_history", []), "pending"],
            "attempt": int(previous.get("attempt", 0)) + 1,
            "command": command.to_dict(),
            "exit_code": None,
            "elapsed_seconds": 0.0,
            "peak_gpu_memory_mib": None,
            "log_path": str(log_path.relative_to(self.run_dir)),
            "required_outputs": list(required),
        }
        self._write(job_id, payload)
        payload["status"] = "running"
        payload["status_history"].append("running")
        self._write(job_id, payload)
        if not command.ready:
            error = "; ".join(command.missing)
            status = (
                "external_asset_blocked"
                if "Protenix-v2 checkpoint" in error
                else "failed"
            )
            payload.update(status=status, error=error)
            payload["status_history"].append(status)
            self._write(job_id, payload)
            return False
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(command.env)
        started = time.monotonic()
        stop_monitor = threading.Event()
        peak_gpu_memory_mib = self._gpu_used_memory_mib()

        def monitor_gpu() -> None:
            nonlocal peak_gpu_memory_mib
            while not stop_monitor.wait(0.5):
                used = self._gpu_used_memory_mib()
                if used is not None:
                    peak_gpu_memory_mib = max(peak_gpu_memory_mib or 0, used)

        monitor = threading.Thread(target=monitor_gpu, daemon=True)
        if os.environ.get("DUOFORGE_GPU_TELEMETRY") == "1":
            monitor.start()
        try:
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    command.argv,
                    cwd=command.cwd,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
        except OSError as error:
            stop_monitor.set()
            if monitor.is_alive():
                monitor.join(timeout=4)
            payload["elapsed_seconds"] = round(time.monotonic() - started, 3)
            payload["peak_gpu_memory_mib"] = peak_gpu_memory_mib
            payload.update(status="failed", error=f"external command could not start: {error}")
            payload["status_history"].append("failed")
            self._write(job_id, payload)
            return False
        stop_monitor.set()
        if monitor.is_alive():
            monitor.join(timeout=4)
        payload["elapsed_seconds"] = round(time.monotonic() - started, 3)
        payload["peak_gpu_memory_mib"] = peak_gpu_memory_mib
        payload["exit_code"] = completed.returncode
        if completed.returncode != 0:
            status = "resource_blocked" if self._log_reports_oom(log_path) else "failed"
            payload.update(status=status, error="external command returned non-zero")
            payload["status_history"].append(status)
            self._write(job_id, payload)
            return False
        if not _required_complete(required):
            payload.update(status="failed", error="command exited zero but required outputs are incomplete")
            payload["status_history"].append("failed")
            self._write(job_id, payload)
            return False
        payload["status"] = "complete"
        payload["status_history"].append("complete")
        self._write(job_id, payload)
        return True

    def fail_parse(self, job_id: str, error: Exception) -> None:
        path = self._path(job_id)
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"job_id": job_id}
        payload.update(status="failed", error=f"output parse failed: {error}")
        payload.setdefault("status_history", []).append("failed")
        self._write(job_id, payload)


JobStore = _JobStore


class DesignPipeline:
    def __init__(
        self,
        backbone: RFantibodyAdapter,
        designers: Mapping[str, SequenceDesigner],
        predictors: Mapping[str, StructurePredictor],
    ) -> None:
        self.backbone = backbone
        self.designers = dict(designers)
        self.predictors = dict(predictors)

    @classmethod
    def from_config(cls, config: PipelineConfig) -> "DesignPipeline":
        del config
        return cls(
            RFantibodyAdapter(),
            designers={
                "igdesign": IgDesignAdapter(),
                "antifold": AntiFoldAdapter(),
                "abmpnn": AbMPNNAdapter(),
                "antibmpnn": AntiBMPNNAdapter(),
            },
            predictors={"protenix": ProtenixAdapter(), "opendde": OpenDDEAdapter()},
        )

    @staticmethod
    def _adapter(adapters: Mapping[str, object], name: str, section: str):
        try:
            return adapters[name]
        except KeyError as error:
            raise PipelineError(f"No adapter registered for enabled {section} '{name}'") from error

    def _design_request(self, config: PipelineConfig, parent: Parent, name: str) -> DesignRequest:
        options = config.generators[name].options
        target_unique = len(config.run.seeds) * config.run.samples_per_seed
        proposal_budget = int(options.get("proposal_budget", config.run.samples_per_seed * 2))
        return DesignRequest(
            parent=parent,
            prepared_dir=config.run.output_dir / "prepared" / parent.parent_id,
            output_dir=config.run.output_dir / "sequence-design" / parent.parent_id / name,
            seeds=config.run.seeds,
            unique_per_generator=target_unique,
            proposal_budget=proposal_budget,
            options=options,
        )

    def _prediction_request(
        self,
        config: PipelineConfig,
        parent: Parent,
        candidate: Candidate,
        name: str,
        seed: int,
        input_path: Path,
    ) -> PredictionRequest:
        return PredictionRequest(
            parent=parent,
            candidate=candidate,
            output_dir=config.run.output_dir / "fold" / name,
            seed=seed,
            samples_per_seed=config.run.samples_per_seed,
            input_path=input_path,
            options=_model_options(config, name),
        )

    def _dry_run(self, config: PipelineConfig, parent: Parent, only_stage: str | None) -> PipelineResult:
        stages: list[AdapterPlan] = []
        if config.mode == "de_novo" and only_stage in {None, "backbone"}:
            stages.append(
                self.backbone.plan(
                    RFdiffusionRequest(config, config.run.output_dir / "backbone", parent.hotspots)
                )
            )
        if only_stage in {None, "sequence-design"}:
            for name, model in config.generators.items():
                if model.enabled:
                    adapter = self._adapter(self.designers, name, "generator")
                    stages.append(adapter.plan(self._design_request(config, parent, name)))
        if only_stage in {None, "fold"}:
            placeholder = Candidate(
                candidate_id="{candidate_id}",
                parent_id=parent.parent_id,
                heavy_sequence=parent.heavy_sequence,
                light_sequence=parent.light_sequence,
                designed_positions=parent.designable_positions,
                mutation_count=0,
                sequence_cluster="{sequence_cluster}",
            )
            input_path = write_prediction_input(
                parent,
                placeholder,
                config.run.seeds[0],
                config.run.output_dir,
                config.msa,
                config.templates,
            )
            for name, model in config.predictors.items():
                if model.enabled:
                    adapter = self._adapter(self.predictors, name, "predictor")
                    stages.append(
                        adapter.plan(
                            self._prediction_request(
                                config, parent, placeholder, name, config.run.seeds[0], input_path
                            )
                        )
                    )
        payload = {
            "dry_run": True,
            "run_id": config.run.run_id,
            "mode": config.mode,
            "parent_id": parent.parent_id,
            "output_dir": str(config.run.output_dir),
            "seeds": list(config.run.seeds),
            "samples_per_seed": config.run.samples_per_seed,
            "stages": [stage.to_dict() for stage in stages],
            "note": "No external command was executed and no candidate or prediction result was fabricated.",
        }
        plan_path = config.run.output_dir / "run_plan.json"
        plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return PipelineResult(parents=(parent,), plan_path=plan_path)

    def _dry_run_input_quiver(self, config: PipelineConfig) -> PipelineResult:
        stage = self.backbone.plan(
            RFdiffusionRequest(
                config,
                config.run.output_dir / "backbone",
                _expanded_target_hotspots(config),
            )
        )
        payload = {
            "dry_run": True,
            "run_id": config.run.run_id,
            "mode": config.mode,
            "parent_id": None,
            "output_dir": str(config.run.output_dir),
            "seeds": list(config.run.seeds),
            "samples_per_seed": config.run.samples_per_seed,
            "stages": [stage.to_dict()],
            "note": (
                "Input Quiver is not decoded during dry-run, so H/L-dependent sequence and fold "
                "commands are deferred until extracted PDB tags become concrete Parents."
            ),
        }
        plan_path = config.run.output_dir / "run_plan.json"
        plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return PipelineResult(plan_path=plan_path)

    def _execute_backbone(
        self, config: PipelineConfig, jobs: _JobStore
    ) -> tuple[list[Parent], bool]:
        if config.mode == "local_redesign":
            parent = prepare_parent(config, execute_numbering=True)
            return [parent], False
        expanded_hotspots = _expanded_target_hotspots(config)
        plan = self.backbone.plan(
            RFdiffusionRequest(
                config,
                config.run.output_dir / "backbone",
                expanded_hotspots,
                cautious_override=True if jobs.resume else None,
            )
        )
        failed = False
        command_outputs = plan.metadata.get("command_expected_outputs", ())
        for index, command in enumerate(plan.commands):
            job_id = f"backbone-{index:03d}"
            command_required = (
                tuple(command_outputs[index])
                if index < len(command_outputs)
                else plan.expected_outputs
            )
            if not jobs.execute(job_id, command, command_required):
                failed = True
        parent_files: list[Path] = []
        for pattern in plan.expected_outputs:
            parent_files.extend(sorted(Path(pattern).parent.glob(Path(pattern).name)))
        expected_parent_count = plan.metadata.get("expected_parent_count")
        if expected_parent_count is not None and len(set(parent_files)) < int(expected_parent_count):
            failed = True
        parents: list[Parent] = []
        target = config.input.target_structure
        assert target is not None
        for index, path in enumerate(dict.fromkeys(parent_files)):
            parent_id = f"{config.run.run_id}-rf-{index:04d}"
            normalized = config.run.output_dir / "prepared/rfantibody_parents" / f"{parent_id}.pdb"
            try:
                restore_rfantibody_target_chains(
                    path, target, config.chains.target, normalized
                )
                parents.append(
                    prepare_parent(
                        config,
                        execute_numbering=True,
                        structure_override=normalized,
                        parent_id_override=parent_id,
                    )
                )
            except Exception as error:
                failed = True
                jobs.fail_parse(f"prepare-{parent_id}", error)
        if not parents:
            failed = True
        return parents, failed

    def _execute_sequence_design(
        self, config: PipelineConfig, parents: list[Parent], jobs: _JobStore
    ) -> tuple[list[Candidate], list[GenerationRecord], dict[str, int], bool]:
        all_candidates: list[Candidate] = []
        all_generations: list[GenerationRecord] = []
        all_shortfalls: dict[str, int] = {}
        failed = False
        for parent in parents:
            proposals_by_generator = {}
            for name, model in config.generators.items():
                if not model.enabled:
                    continue
                adapter = self._adapter(self.designers, name, "generator")
                request = self._design_request(config, parent, name)
                try:
                    plan = adapter.plan(request)
                except Exception as error:
                    failed = True
                    jobs.fail_parse(f"generation-{parent.parent_id}-{name}-plan", error)
                    proposals_by_generator[name] = []
                    continue
                proposals = []
                for seed, command, output in zip(config.run.seeds, plan.commands, plan.expected_outputs):
                    job_id = f"generation-{parent.parent_id}-{name}-s{seed}"
                    if not jobs.execute(job_id, command, (output,)):
                        failed = True
                        continue
                    try:
                        if name == "igdesign":
                            proposals.extend(
                                parse_igdesign_csv(
                                    Path(output),
                                    parent.heavy_sequence,
                                    parent.light_sequence,
                                    plan.metadata["regions"],
                                    seed,
                                )
                            )
                        elif name == "antifold":
                            proposals.extend(parse_antifold_csv(Path(output), seed))
                        else:
                            raise PipelineError(
                                f"Optional generator {name} has command planning but no verified output parser"
                            )
                    except Exception as error:
                        failed = True
                        jobs.fail_parse(job_id, error)
                proposals_by_generator[name] = proposals
            target_unique = len(config.run.seeds) * config.run.samples_per_seed
            try:
                candidates, generations, shortfalls = merge_generation_proposals(
                    parent, proposals_by_generator, target_unique
                )
            except Exception:
                raise
            all_candidates.extend(candidates)
            all_generations.extend(generations)
            for generator, count in shortfalls.items():
                all_shortfalls[f"{parent.parent_id}:{generator}"] = count
                failed = True
        return all_candidates, all_generations, all_shortfalls, failed

    def _execute_fold(
        self,
        config: PipelineConfig,
        parents: list[Parent],
        candidates: list[Candidate],
        jobs: _JobStore,
    ) -> tuple[list[PredictionRecord], bool]:
        predictions: list[PredictionRecord] = []
        failed = False
        parents_by_id = {parent.parent_id: parent for parent in parents}
        for candidate in candidates:
            parent = parents_by_id[candidate.parent_id]
            for seed in config.run.seeds:
                input_path = write_prediction_input(
                    parent, candidate, seed, config.run.output_dir, config.msa, config.templates
                )
                for name, model in config.predictors.items():
                    if not model.enabled:
                        continue
                    adapter = self._adapter(self.predictors, name, "predictor")
                    request = self._prediction_request(config, parent, candidate, name, seed, input_path)
                    job_id = f"prediction-{candidate.candidate_id}-{adapter.name}-s{seed}"
                    try:
                        plan = adapter.plan(request)
                    except Exception as error:
                        failed = True
                        jobs.fail_parse(job_id, error)
                        continue
                    if not jobs.execute(job_id, plan.commands[0], plan.expected_outputs):
                        failed = True
                        continue
                    try:
                        parsed = adapter.parse_outputs(
                            request.output_dir, candidate.candidate_id, seed
                        )
                        if len(parsed) != config.run.samples_per_seed:
                            raise PipelineError(
                                f"{adapter.name} produced {len(parsed)} samples; expected {config.run.samples_per_seed}"
                            )
                        for prediction in parsed:
                            suffix = prediction.prediction_path.suffix
                            structure_path = (
                                config.run.output_dir
                                / "structures"
                                / candidate.candidate_id
                                / adapter.name
                                / f"seed_{seed}_sample_{prediction.sample_index}{suffix}"
                            )
                            structure_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(prediction.prediction_path, structure_path)
                            geometry = compute_geometry(
                                structure_path, parent.structure_path, parent
                            )
                            predictions.append(
                                PredictionRecord(
                                    prediction_id=_stable_id(
                                        "pred", candidate.candidate_id, adapter.name, seed, prediction.sample_index
                                    ),
                                    candidate_id=candidate.candidate_id,
                                    prediction_model=adapter.name,
                                    seed=seed,
                                    sample_index=prediction.sample_index,
                                    prediction_path=str(structure_path.relative_to(config.run.output_dir)),
                                    raw_metrics=dict(prediction.raw_metrics),
                                    geometry_metrics=geometry,
                                    is_model_top1=prediction.is_model_top1,
                                )
                            )
                    except Exception as error:
                        failed = True
                        jobs.fail_parse(job_id, error)
        return _assign_model_top1(predictions, config.run.seeds), failed

    def run(
        self,
        config: PipelineConfig,
        dry_run: bool = True,
        resume: bool = False,
        only_stage: str | None = None,
    ) -> PipelineResult:
        config.run.output_dir.mkdir(parents=True, exist_ok=True)
        _snapshot_run_provenance(config)
        if dry_run:
            if config.input.input_quiver:
                parents_path = config.run.output_dir / "parents.jsonl"
                if parents_path.is_file() and only_stage != "backbone":
                    provisional = _load_parents(config.run.output_dir)[0]
                elif only_stage in {None, "backbone"}:
                    return self._dry_run_input_quiver(config)
                else:
                    raise PipelineError(
                        "Input Quiver must be extracted first: run backbone --execute, then dry-run the downstream stage"
                    )
            else:
                provisional = prepare_parent(config, execute_numbering=False)
                write_prepared_complex(provisional, config.run.output_dir)
            return self._dry_run(config, provisional, only_stage)

        jobs = _JobStore(config.run.output_dir, resume)
        if only_stage == "sequence-design":
            parents = (
                _load_parents(config.run.output_dir)
                if config.mode == "de_novo"
                else [prepare_parent(config, execute_numbering=True)]
            )
            candidates, generations, shortfalls, failed = self._execute_sequence_design(
                config, parents, jobs
            )
            status = "partial_failure" if failed else "complete"
            paths = write_records(
                config.run.output_dir, parents, candidates, generations, []
            )
            write_summary(
                config.run.output_dir,
                candidates,
                generations,
                [],
                shortfalls,
                status,
                _run_metadata(config),
            )
            write_markdown_report(config.run.output_dir, candidates, [], shortfalls)
            return PipelineResult(
                tuple(parents), tuple(candidates), tuple(generations),
                manifest_path=paths["manifest"], status=status, exit_code=int(failed)
            )
        if only_stage == "fold":
            parents = _load_parents(config.run.output_dir)
            candidates = _load_candidates(config.run.output_dir)
            generations = _load_generations(config.run.output_dir)
            predictions, failed = self._execute_fold(config, parents, candidates, jobs)
            status = "partial_failure" if failed else "complete"
            paths = write_records(
                config.run.output_dir, parents, candidates, generations, predictions
            )
            write_summary(
                config.run.output_dir,
                candidates,
                generations,
                predictions,
                {},
                status,
                _run_metadata(config),
            )
            write_markdown_report(config.run.output_dir, candidates, predictions, {})
            return PipelineResult(
                tuple(parents), tuple(candidates), tuple(generations), tuple(predictions),
                manifest_path=paths["manifest"], status=status, exit_code=int(failed)
            )
        parents, failed = self._execute_backbone(config, jobs)
        if only_stage == "backbone":
            paths = write_records(config.run.output_dir, parents, [], [], [])
            status = "partial_failure" if failed else "complete"
            write_summary(
                config.run.output_dir,
                [],
                [],
                [],
                {},
                status,
                _run_metadata(config),
            )
            return PipelineResult(tuple(parents), manifest_path=paths["manifest"], status=status, exit_code=int(failed))

        candidates, generations, shortfalls, design_failed = self._execute_sequence_design(
            config, parents, jobs
        )
        failed |= design_failed
        predictions: list[PredictionRecord] = []
        if only_stage != "sequence-design":
            predictions, prediction_failed = self._execute_fold(
                config, parents, candidates, jobs
            )
            failed |= prediction_failed
        status = "partial_failure" if failed else "complete"
        paths = write_records(config.run.output_dir, parents, candidates, generations, predictions)
        write_summary(
            config.run.output_dir,
            candidates,
            generations,
            predictions,
            shortfalls,
            status,
            _run_metadata(config),
        )
        write_markdown_report(config.run.output_dir, candidates, predictions, shortfalls)
        return PipelineResult(
            tuple(parents),
            tuple(candidates),
            tuple(generations),
            tuple(predictions),
            manifest_path=paths["manifest"],
            status=status,
            exit_code=int(failed),
        )
