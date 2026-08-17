from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from antibody_design.schemas import (
    Candidate,
    GenerationRecord,
    Parent,
    PredictionRecord,
    record_dict,
)


def _relative(value: str, output_dir: Path) -> str:
    path = Path(value)
    try:
        return str(path.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        return str(path)


def _canonical_payload(record: object, output_dir: Path) -> dict:
    payload = record_dict(record)
    for key, value in tuple(payload.items()):
        if key.endswith("_path") and isinstance(value, str):
            payload[key] = _relative(value, output_dir)
    return payload


def _write_jsonl(path: Path, records: Iterable[object], output_dir: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(_canonical_payload(record, output_dir), sort_keys=True) + "\n")
    return path


def write_records(
    output_dir: Path,
    parents: list[Parent],
    candidates: list[Candidate],
    generations: list[GenerationRecord],
    predictions: list[PredictionRecord],
) -> dict[str, Path]:
    paths = {
        "parents": _write_jsonl(output_dir / "parents.jsonl", parents, output_dir),
        "candidates": _write_jsonl(output_dir / "candidates.jsonl", candidates, output_dir),
        "generations": _write_jsonl(output_dir / "generations.jsonl", generations, output_dir),
        "predictions": _write_jsonl(output_dir / "predictions.jsonl", predictions, output_dir),
    }
    by_candidate = {candidate.candidate_id: candidate for candidate in candidates}
    provenance: dict[str, list[GenerationRecord]] = {}
    for generation in generations:
        provenance.setdefault(generation.candidate_id, []).append(generation)
    predicted: dict[str, list[PredictionRecord]] = {}
    for prediction in predictions:
        predicted.setdefault(prediction.candidate_id, []).append(prediction)
    fields = [
        "candidate_id", "parent_id", "generation_id", "generator",
        "generation_seed", "generation_sample_index",
        "heavy_sequence", "light_sequence", "designed_positions", "mutation_count",
        "sequence_cluster", "liabilities", "prediction_id", "prediction_model",
        "prediction_seed", "prediction_sample_index", "is_model_top1", "prediction_path",
        "generation_metrics", "raw_metrics", "geometry_metrics",
    ]
    manifest_path = output_dir / "candidate_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in by_candidate.values():
            candidate_generations = provenance.get(candidate.candidate_id) or [None]
            candidate_predictions = predicted.get(candidate.candidate_id) or [None]
            for generation in candidate_generations:
                for prediction in candidate_predictions:
                    writer.writerow(
                        {
                            "candidate_id": candidate.candidate_id,
                            "parent_id": candidate.parent_id,
                            "generation_id": generation.generation_id if generation else "",
                            "generator": generation.generator if generation else "",
                            "generation_seed": generation.seed if generation else "",
                            "generation_sample_index": generation.sample_index if generation else "",
                            "heavy_sequence": candidate.heavy_sequence,
                            "light_sequence": candidate.light_sequence,
                            "designed_positions": json.dumps(candidate.designed_positions),
                            "mutation_count": candidate.mutation_count,
                            "sequence_cluster": candidate.sequence_cluster,
                            "liabilities": json.dumps(candidate.liabilities),
                            "prediction_id": prediction.prediction_id if prediction else "",
                            "prediction_model": prediction.prediction_model if prediction else "",
                            "prediction_seed": prediction.seed if prediction else "",
                            "prediction_sample_index": prediction.sample_index if prediction else "",
                            "is_model_top1": prediction.is_model_top1 if prediction else "",
                            "prediction_path": (
                                _relative(prediction.prediction_path, output_dir)
                                if prediction else ""
                            ),
                            "generation_metrics": json.dumps(
                                generation.raw_metrics if generation else {}, sort_keys=True
                            ),
                            "raw_metrics": json.dumps(
                                prediction.raw_metrics if prediction else {}, sort_keys=True
                            ),
                            "geometry_metrics": json.dumps(
                                prediction.geometry_metrics if prediction else {}, sort_keys=True
                            ),
                        }
                    )
    paths["manifest"] = manifest_path
    return paths


def write_summary(
    output_dir: Path,
    candidates: list[Candidate],
    generations: list[GenerationRecord],
    predictions: list[PredictionRecord],
    shortfalls: dict[str, int],
    run_status: str,
    run_metadata: Mapping | None = None,
) -> Path:
    payload = {
        "run_status": run_status,
        "candidate_count": len(candidates),
        "generation_count": len(generations),
        "prediction_count": len(predictions),
        "generation_records_by_generator": dict(Counter(item.generator for item in generations)),
        "predictions_by_model": dict(Counter(item.prediction_model for item in predictions)),
        "unique_candidate_shortfall_by_generator": shortfalls,
        "liability_flagged_candidate_count": sum(bool(item.liabilities) for item in candidates),
        "combined_score": None,
        "note": "Generator and predictor native scores are not calibrated across models; geometry is observation-only.",
    }
    if run_metadata:
        payload["run"] = dict(run_metadata)
    path = output_dir / "run.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_report(
    output_dir: Path,
    candidates: list[Candidate],
    predictions: list[PredictionRecord],
    shortfalls: dict[str, int],
) -> Path:
    lines = [
        "# DuoForge-Ab run report",
        "",
        f"- Unique candidates: {len(candidates)}",
        f"- Prediction structures: {len(predictions)}",
        f"- Generator shortfalls: `{json.dumps(shortfalls, sort_keys=True)}`",
        "- Cross-model total score: not defined",
        "",
        "## Metric semantics",
        "",
        "`ranking_score`, `final_score`, `pLDDT`, `pTM`, and `ipTM` are retained as native model outputs and must not be compared as if identically calibrated. Geometry fields use Å; RMSD arrows are not used because no pass/fail or optimization direction is defined.",
        "",
        "Chemistry liabilities are report-only. Every contract-valid unique sequence is sent to both predictors.",
    ]
    path = output_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
