from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from antibody_design.schemas import Candidate, CandidateManifestRow


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def write_candidates(candidates: list[Candidate], output_dir: Path) -> Path:
    return _write_jsonl(
        output_dir / "candidates.jsonl", [asdict(candidate) for candidate in candidates]
    )


def write_manifest(rows: list[CandidateManifestRow], output_dir: Path) -> Path:
    return _write_jsonl(
        output_dir / "candidate_manifest.jsonl", [row.to_dict() for row in rows]
    )


def write_summary(
    candidates: list[Candidate], rows: list[CandidateManifestRow], output_dir: Path
) -> Path:
    payload = {
        "candidate_count": len(candidates),
        "manifest_row_count": len(rows),
        "candidates_by_generator": dict(Counter(item.generator for item in candidates)),
        "predictions_by_model": dict(Counter(item.prediction_model for item in rows)),
        "liability_flag_count": sum(bool(item.liabilities) for item in candidates),
        "combined_score": None,
        "note": "Raw metrics remain model-specific and are not added or averaged.",
    }
    path = output_dir / "summary.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
