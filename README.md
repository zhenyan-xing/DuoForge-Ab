# DuoForge-Ab

DuoForge-Ab is a lightweight, file-and-command orchestrator for this fixed pipeline:

`target + hotspots → RFantibody/RFdiffusion → IgDesign + AntiFold → exact sequence deduplication → Protenix-v2 + OpenDDE-ABAG blind co-fold → native confidence + common geometry`

It implements `de_novo` and `local_redesign`. `full_backbone_de_novo` deliberately fails with `not implemented`; ordinary RFdiffusion is not presented as a framework-free antibody generator.

## Current status

The following are runnable without model weights: YAML validation, PDB chain extraction, hotspot expansion, RFantibody-compatible planning, model input construction, output parser fixture tests, and end-to-end `--dry-run`. ANARCI-backed preparation and all four external model adapters have execution paths, explicit asset preflights, subprocess logs, job states, and resume behavior.

Real model inference was not run in this implementation round. In particular, the IgDesign multi-antigen runner, exact-mask AntiFold runner, Protenix-v2 adapter, and OpenDDE-ABAG adapter are source-checked interfaces but remain unverified with real checkpoints. Missing executables, common data, or checkpoints fail explicitly; no normal pipeline path produces mock results or downloads assets.

## Install boundaries

Code and checkpoints are separate, explicit installations.

1. Install only this lightweight orchestrator:

   ```bash
   python -m pip install -e .
   ```

2. Clone/install each upstream at the revision in [`models/manifest.yaml`](models/manifest.yaml), preferably in its named independent conda/mamba environment. The project never edits those checkouts.
3. Obtain checkpoints and common inference files explicitly from their official distribution channels. Put them at paths you control, then edit the YAML. No checkpoint installer is run by config loading or pipeline execution.
4. Optionally verify the published OpenDDE-ABAG checksum without modifying the file:

   ```bash
   python scripts/check_model_assets.py --opendde-checkpoint /path/to/opendde_abag.pt
   ```

The repository contains no upstream weight, database, or model source copy. RFantibody's `framework: auto` resolves the small `hu-4D5-8_Fv.pdb` preset from the pinned external RFantibody checkout.

## Commands

Run from this directory before editable installation by adding `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m antibody_design.cli validate --config configs/example.yaml
PYTHONPATH=src python -m antibody_design.cli run --config configs/example.yaml --dry-run
PYTHONPATH=src python -m antibody_design.cli backbone --config configs/example.yaml --dry-run
PYTHONPATH=src python -m antibody_design.cli sequence-design --config configs/example.yaml --dry-run
PYTHONPATH=src python -m antibody_design.cli fold --config configs/example.yaml --dry-run
```

`prepare` runs ANARCI and writes an IMGT-only temporary structure plus mappings; it therefore requires the pinned ANARCI installation and a real antibody variable domain. The bundled PDB is deliberately tiny synthetic test data, so only `validate` and `--dry-run` are meaningful for the example.

Execution is always explicit:

```bash
duoforge-ab run --config my_run.yaml --execute
duoforge-ab run --config my_run.yaml --execute --resume
```

`--resume` skips a job only when its state is `complete` and all required outputs still exist. Failed or incomplete jobs are attempted once; independent jobs continue, and any failure makes the run `partial_failure` with a nonzero exit code.

Compatibility aliases do not run retired models:

- `proteinmpnn` aliases `sequence-design` and prints a migration message; default generators are IgDesign and AntiFold.
- `rf2` aliases `fold` and prints a migration message; predictors are Protenix-v2 and OpenDDE-ABAG.

## Modes and scientific semantics

- `de_novo` requires a target 3D structure, at least one hotspot, and a framework path/list or `auto`. Every RFdiffusion PDB/Quiver tag becomes a separate Parent. RFantibody's collapsed `T` chain is restored to every original target chain using `chain_map.json`.
- With `input_quiver`, `backbone --execute` extracts tags before Parent preparation. A first dry run can plan only that extraction because decoding is deliberately not performed in dry-run; downstream dry-runs become available after `parents.jsonl` exists.
- `local_redesign` starts from a fixed antibody–target complex and skips RFdiffusion.
- The final design mask is `(selected CDR loops ∪ explicit author residue IDs) − fixed residue IDs`. Target chains can never enter it.
- Hotspots reach RFdiffusion and IgDesign epitope context only. They are absent from the blind Protenix/OpenDDE input and are reused after prediction only as geometry labels.
- Every target chain is present in both sequence-model context and co-fold inputs.
- All contract-valid unique candidates reach both predictors. Chemistry liabilities are annotations, never filters or a total score.

## Sampling and identity

`run.seeds` is the explicit seed list. `run.samples_per_seed = K` means each predictor makes K structures for every seed. Each sequence generator receives the same seeds and aims for `len(seeds) × K` unique sequences per Parent. Its bounded `proposal_budget` may be larger to compensate for duplicates; inability to fill the target becomes a recorded shortfall.

Identity is deliberately split:

- Parent: one RFdiffusion backbone/pose or the local input complex.
- Candidate: one unique `(parent_id, heavy_sequence, light_sequence)`.
- GenerationRecord: one accepted generator/seed/sample provenance event.
- PredictionRecord: one model/seed/sample structure with native metrics and geometry.

The same H/L from IgDesign and AntiFold therefore has one Candidate, two generation records, and only one prediction job per model/seed.

## Prediction information policy

MSA mode is `none`, `target_only` (default), or experimental `all_unpaired`. Supplied MSAs are unpaired. Missing per-chain MSAs become query-only A3M files. No antibody–target paired MSA is created and no MSA/template search runs.

Both predictors consume the same AlphaFold-server-style logical input with H, L, and every target chain. Native `templatesPath` accepts precomputed `.a3m`/`.hhr` hits. A raw known target assembly cannot currently be passed directly through the fixed native schemas; it is recorded as logical provenance, not silently injected as a pose restraint. See [open questions](docs/open_questions.md).

## Outputs

An executed run writes:

```text
outputs/<run_id>/
├── run.json
├── parents.jsonl
├── candidates.jsonl
├── generations.jsonl
├── predictions.jsonl
├── candidate_manifest.csv
├── report.md
├── prepared/provenance/{config.yaml,model_manifest.yaml}
├── structures/
└── logs/
```

`prepared/provenance/` contains run-local snapshots of the input configuration and pinned model manifest. JSONL is canonical; CSV is a flattened generation × prediction export. Paths in canonical records are relative to the run directory. Every official ranked sample is retained. Native scores stay namespaced inside `raw_metrics`; Protenix and OpenDDE values are not assumed to share calibration, and no combined score is defined.

See [stage contracts](docs/contracts.md) for every field and metric, and [open questions](docs/open_questions.md) for the remaining real-weight uncertainties.

## Minimal checks

```bash
PYTHONPATH=src python -m py_compile $(rg --files src scripts tests -g '*.py')
PYTHONPATH=src python -m unittest discover -s tests -v
```
