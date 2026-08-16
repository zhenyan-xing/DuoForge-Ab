from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .analysis.candidates import assign_sequence_clusters, normalize_candidates
from .analysis.report import write_candidates, write_manifest, write_summary
from .design.abmpnn import AbMPNNAdapter
from .design.base import AdapterPlan, DesignRequest, SequenceDesigner
from .design.igdesign import IgDesignAdapter
from .predict.base import PredictionRequest, StructurePredictor
from .predict.opendde import OpenDDEAdapter
from .predict.protenix import ProtenixAdapter
from .prepare import prepare_complex, write_prepared_complex
from .schemas import Candidate, CandidateManifestRow, PipelineConfig, PreparedComplex


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class PipelineResult:
    candidates: tuple[Candidate, ...] = ()
    manifest_rows: tuple[CandidateManifestRow, ...] = ()
    manifest_path: Path | None = None
    plan_path: Path | None = None


def _write_prediction_input(
    prepared: PreparedComplex,
    candidate: Candidate,
    seed: int,
    model_name: str,
    output_dir: Path,
) -> Path:
    safe_model = model_name.replace("/", "-")
    path = output_dir / "prediction_inputs" / (
        f"{candidate.candidate_id}__{safe_model}__s{seed}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    sequences = [candidate.heavy_sequence, candidate.light_sequence]
    sequences.extend(prepared.antigen_sequences[chain] for chain in prepared.chains.antigen)
    payload = [
        {
            "name": candidate.candidate_id,
            "modelSeeds": [seed],
            "covalent_bonds": [],
            "sequences": [
                {
                    "proteinChain": {
                        "sequence": sequence,
                        "count": 1,
                        "modifications": [],
                    }
                }
                for sequence in sequences
            ],
        }
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


class DesignPipeline:
    def __init__(
        self,
        designers: Mapping[str, SequenceDesigner],
        predictors: Mapping[str, StructurePredictor],
    ) -> None:
        self.designers = dict(designers)
        self.predictors = dict(predictors)

    @classmethod
    def from_config(cls, config: PipelineConfig) -> "DesignPipeline":
        del config
        return cls(
            designers={"abmpnn": AbMPNNAdapter(), "igdesign": IgDesignAdapter()},
            predictors={"protenix": ProtenixAdapter(), "opendde": OpenDDEAdapter()},
        )

    @staticmethod
    def _adapter(adapters: Mapping[str, object], name: str, section: str):
        try:
            return adapters[name]
        except KeyError as error:
            raise PipelineError(f"No adapter registered for enabled {section} '{name}'") from error

    def _design_request(
        self, config: PipelineConfig, prepared: PreparedComplex, name: str
    ) -> DesignRequest:
        model = config.generators[name]
        return DesignRequest(
            prepared=prepared,
            prepared_dir=config.run.output_dir / "prepared",
            output_dir=config.run.output_dir / "design" / name,
            num_sequences=model.num_sequences or 1,
            seed=model.seed,
            options=model.options,
        )

    def _dry_run(
        self, config: PipelineConfig, prepared: PreparedComplex
    ) -> PipelineResult:
        stages: list[AdapterPlan] = []
        for name, model in config.generators.items():
            if not model.enabled:
                continue
            adapter = self._adapter(self.designers, name, "generator")
            stages.append(adapter.plan(self._design_request(config, prepared, name)))

        placeholder = Candidate(
            candidate_id="{candidate_id}",
            parent_id=prepared.parent_id,
            generator="{generator}",
            heavy_sequence=prepared.heavy_sequence,
            light_sequence=prepared.light_sequence,
            designed_positions=tuple(str(ref) for ref in prepared.designable_positions),
            mutation_count=0,
            sequence_cluster="{sequence_cluster}",
            seed=config.run.seed,
        )
        for name, model in config.predictors.items():
            if not model.enabled:
                continue
            adapter = self._adapter(self.predictors, name, "predictor")
            request = PredictionRequest(
                prepared=prepared,
                candidate=placeholder,
                output_dir=config.run.output_dir / "predict" / name,
                seed=model.seed,
                input_path=None,
                options=model.options,
            )
            stages.append(adapter.plan(request))

        payload = {
            "dry_run": True,
            "parent_id": prepared.parent_id,
            "input_structure": str(prepared.input_structure),
            "output_dir": str(config.run.output_dir),
            "stages": [stage.to_dict() for stage in stages],
            "note": "No external command was executed and no candidate result was fabricated.",
        }
        plan_path = config.run.output_dir / "run_plan.json"
        plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return PipelineResult(plan_path=plan_path)

    def _execute(
        self, config: PipelineConfig, prepared: PreparedComplex
    ) -> PipelineResult:
        candidates: list[Candidate] = []
        for name, model in config.generators.items():
            if not model.enabled:
                continue
            adapter = self._adapter(self.designers, name, "generator")
            request = self._design_request(config, prepared, name)
            generated = adapter.generate(request)
            candidates.extend(
                normalize_candidates(prepared, adapter.name, model.seed, generated)
            )
        candidates = assign_sequence_clusters(candidates)
        write_candidates(candidates, config.run.output_dir)

        rows: list[CandidateManifestRow] = []
        for candidate in candidates:
            for name, model in config.predictors.items():
                if not model.enabled:
                    continue
                adapter = self._adapter(self.predictors, name, "predictor")
                for replicate in range(model.num_predictions or 1):
                    seed = model.seed + replicate
                    input_path = _write_prediction_input(
                        prepared,
                        candidate,
                        seed,
                        adapter.name,
                        config.run.output_dir,
                    )
                    prediction = adapter.predict(
                        PredictionRequest(
                            prepared=prepared,
                            candidate=candidate,
                            output_dir=config.run.output_dir / "predict" / name,
                            seed=seed,
                            input_path=input_path,
                            options=model.options,
                        )
                    )
                    rows.append(
                        CandidateManifestRow(
                            candidate_id=candidate.candidate_id,
                            parent_id=candidate.parent_id,
                            generator=candidate.generator,
                            heavy_sequence=candidate.heavy_sequence,
                            light_sequence=candidate.light_sequence,
                            designed_positions=candidate.designed_positions,
                            mutation_count=candidate.mutation_count,
                            sequence_cluster=candidate.sequence_cluster,
                            prediction_model=prediction.prediction_model,
                            seed=prediction.seed,
                            prediction_path=str(prediction.prediction_path),
                            raw_metrics=dict(prediction.raw_metrics),
                            generation_metrics=dict(candidate.generation_metrics),
                            liabilities=candidate.liabilities,
                        )
                    )
        manifest_path = write_manifest(rows, config.run.output_dir)
        write_summary(candidates, rows, config.run.output_dir)
        return PipelineResult(
            candidates=tuple(candidates),
            manifest_rows=tuple(rows),
            manifest_path=manifest_path,
        )

    def run(self, config: PipelineConfig, dry_run: bool = True) -> PipelineResult:
        config.run.output_dir.mkdir(parents=True, exist_ok=True)
        prepared = prepare_complex(config)
        write_prepared_complex(prepared, config.run.output_dir)
        return self._dry_run(config, prepared) if dry_run else self._execute(config, prepared)
