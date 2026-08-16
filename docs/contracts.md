# Stage contracts

The orchestration follows RFantibody's separable-stage idea, but starts from an
existing complex and therefore omits backbone generation.

| Stage | Input | Output in v0.1 |
| --- | --- | --- |
| prepare | PDB, chain IDs, residue masks | `prepared/complex.json` and an unchanged PDB copy |
| design | prepared complex and model settings | normalized `GeneratedSequence` objects; real parsers pending |
| candidate analysis | both generator streams | `candidates.jsonl`, exact within-generator deduplication, liability flags |
| predict | candidate H/L plus antigen sequences | model-specific `PredictionResult`; real parsers pending |
| report | candidates and predictions | `candidate_manifest.jsonl` and `summary.json` |

RFantibody uses H/L/T-normalized PDBs and Quiver containers to carry structures,
tags, and scores between ProteinMPNN and RF2. This project keeps the same restartable
stage boundary but uses ordinary files and JSONL so upstream model code is not copied.

Sources inspected:

- https://github.com/RosettaCommons/RFantibody
- https://github.com/RosettaCommons/RFantibody/blob/main/src/rfantibody/cli/inference.py
- https://github.com/dauparas/ProteinMPNN
- https://github.com/AbSciBio/igdesign
- https://github.com/bytedance/Protenix
- https://github.com/aurekaresearch/OpenDDE

## Candidate manifest

There is one final manifest row per candidate, prediction model, and prediction
replicate. `raw_metrics` contains only that prediction model's native metrics;
`generation_metrics` contains only the source generator's native metrics. No
cross-model total is defined.

Exact duplicate sequences are removed within a generator stream. The same sequence
from different generators remains as two candidates with the same `sequence_cluster`,
preserving provenance and the requested per-generator prediction budget.

## Reserved later boundaries

- AntiFold will consume `candidates.jsonl` and emit a separate mutation-tolerance
  table keyed by `candidate_id`; it will not be folded into a total score.
- An off-target panel will consume candidate sequences plus an explicit panel spec
  (WT peptide, mutant peptides, alternative HLA) and emit separate prediction rows
  keyed by candidate and panel member.
