# DuoForge-Ab

DuoForge-Ab is a lightweight, file-and-command orchestrator for this fixed pipeline:

`target + hotspots → RFantibody/RFdiffusion → IgDesign + AntiFold → exact sequence deduplication → Protenix-v2 + OpenDDE-ABAG blind co-fold → native confidence + common geometry`

It implements `de_novo` and `local_redesign`. `full_backbone_de_novo` deliberately fails with `not implemented`; ordinary RFdiffusion is not presented as a framework-free antibody generator.

## Quick start

Requirements: Linux x86-64, an NVIDIA GPU/driver suitable for the pinned CUDA
runtimes, Git, and one of `mamba`, `micromamba`, or `conda`. A complete local
installation is not small: keep at least 70 GiB free unless you intentionally
override the preflight after reading [Disk use](#disk-use).

```bash
git clone https://github.com/zhenyan-xing/DuoForge-Ab.git
cd DuoForge-Ab

# 1. Inspect, then install pinned source and isolated environments.
./setup.sh --dry-run --root /data/duoforge-ab
./setup.sh --root /data/duoforge-ab

# 2. Inspect, then fetch checkpoints and required common inference files.
./fetch_assets.sh --dry-run --root /data/duoforge-ab
./fetch_assets.sh --root /data/duoforge-ab \
  --protenix-checkpoint /path/to/official/protenix-v2.pt

# 3. Expose the orchestrator and installation root to portable YAML paths.
source /data/duoforge-ab/env.sh

# 4. Put the real target at data/inputs/target.pdb, edit chains/hotspots in
#    my_run.yaml, and inspect the complete command plan before using the GPU.
duoforge-ab validate --config my_run.yaml
duoforge-ab run --config my_run.yaml --dry-run
duoforge-ab run --config my_run.yaml --execute
```

If the official Protenix-v2 CDN works from your region, omit
`--protenix-checkpoint`; the fetcher will use its pinned official URL. The URL
returned HTTP 403 during the 2026-08-17 audit and no official alternative mirror
was available, so the script never substitutes Protenix-v1 or a community copy.

Both scripts are resumable at file/environment granularity. Re-running them
reuses a checkout only when its exact commit matches, reuses complete assets,
and leaves `.part` downloads available for HTTP resume. `setup.sh` never fetches
model weights. `fetch_assets.sh` never installs code or Python packages. Normal
configuration loading and `duoforge-ab run` never access the network.

## Current status

The following are runnable without model weights: YAML validation, PDB chain extraction, hotspot expansion, RFantibody-compatible planning, model input construction, output parser fixture tests, and end-to-end `--dry-run`. ANARCI-backed preparation and all four external model adapters have execution paths, explicit asset preflights, subprocess logs, job states, and resume behavior.

Real model inference was not run in this implementation round. In particular, the IgDesign multi-antigen runner, exact-mask AntiFold runner, Protenix-v2 adapter, and OpenDDE-ABAG adapter are source-checked interfaces but remain unverified with real checkpoints. Missing executables, common data, or checkpoints fail explicitly; no normal pipeline path produces mock results or downloads assets.

## Installation layout and isolation

The default `standard` profile installs one lightweight orchestration environment
and five model environments:

| Environment | Fixed upstream runtime | Why it stays separate |
| --- | --- | --- |
| `orchestrator` | Python 3.11, PyYAML, NumPy | File/command orchestration only; no model framework. |
| `rfantibody` | Python 3.10, PyTorch 2.3, CUDA 11.8 | RFantibody's locked RFdiffusion runtime. |
| `igdesign` | Python 3.11.9, PyTorch 2.0, CUDA 11.8, HMMER, pinned ANARCI source | ANARCI is shared with IgDesign instead of creating a duplicate sixth model environment. |
| `antifold` | Python 3.10, PyTorch 2.2, CUDA 12.1 | Its PyTorch/PyG ABI differs from RFantibody and IgDesign. |
| `protenix` | Python 3.11, PyTorch 2.7.1, cuequivariance 0.8 | Official Protenix-v2 requirements. |
| `opendde` | Python 3.11, PyTorch 2.7.1, cuequivariance 0.10 | The cuequivariance pin conflicts with Protenix, although shared wheels can still be hard-linked. |

All prefixes live under `$DUOFORGE_HOME/envs`, sources under
`$DUOFORGE_HOME/sources`, and package caches under `$DUOFORGE_HOME/cache`.
Conda packages and uv wheels use shared caches/hard links on the same filesystem,
so identical files need not consume another physical copy. Source clones are
shallow and detached at the revisions in [`models/manifest.yaml`](models/manifest.yaml).

For development of only the lightweight orchestrator, without a runnable model
pipeline:

```bash
./setup.sh --profile bootstrap --root /data/duoforge-ab
```

This profile does not clone models or install their environments/weights and is
therefore not advertised as a complete pipeline installation.

To check a separately obtained OpenDDE-ABAG file without modifying it:

```bash
python scripts/check_model_assets.py --opendde-checkpoint /path/to/opendde_abag.pt
```

The Git repository itself contains no upstream source, model weight, or database.
RFantibody's `framework: auto` resolves the small `hu-4D5-8_Fv.pdb` preset from
the pinned external checkout.

## Disk use

`GB` means 10^9 bytes; `GiB` means 2^30 bytes. The following source values were
measured with `du` at the pinned commits on 2026-08-17. They are audit numbers,
not download quotas.

| Component | Size | Meaning |
| --- | ---: | --- |
| Six source trees, excluding `.git` | about 193 MiB | RFantibody 44, IgDesign 3.7, AntiFold 3.0, Protenix 98, OpenDDE 42, ANARCI 2.3 MiB. |
| Six source trees, including shallow/full local Git metadata measured during audit | about 279 MiB | Source is far below 5 GB and is not the storage problem. |
| RFdiffusion-Ab checkpoint | 0.450 GiB | Only RFdiffusion is fetched; retired RFantibody ProteinMPNN/RF2/TCR weights are excluded. |
| IgMPNN checkpoint | 0.006 GiB | Small auxiliary IgDesign checkpoint. |
| IgDesign LMDesign checkpoint | 10.716 GiB | The largest asset. Metadata inspection found inference `state_dict` and hyperparameters, but no optimizer state that could be safely stripped. |
| AntiFold checkpoint | 0.528 GiB | Official `model.pt`. |
| OpenDDE-ABAG checkpoint | 2.445 GiB | Exact published size and SHA-256 are checked. |
| Protenix-v2 checkpoint | not officially measurable from this region | The official model has 464.44 M parameters; roughly 1.7–2.0 GB is a planning estimate, not a verified file size. |
| Known checkpoints excluding Protenix-v2 | 14.146 GiB | Exact sum: 15,188,759,772 bytes. |
| Independent environments after cache/hard-link sharing | roughly 30–45 GiB | Estimate; GPU wheel availability and filesystem hard-link/reflink support affect it. |
| Complete steady installation | roughly 45–60 GiB | Environments, checkpoints, common data, sources, and modest cache. |

The standard preflight therefore defaults to 70 GiB free. Change it explicitly
with `--min-free-gib N` or `DUOFORGE_MIN_FREE_GIB=N`; `--skip-disk-check` is
available when an administrator knows that hard links, reflinks, or external
mounts make the estimate overly conservative.

Protein-only MSA/template handling remains deliberately light:

- A supplied per-target `.a3m` is normally KB–MB scale; missing chains use
  query-only A3M rather than triggering a network search.
- `fetch_assets.sh --with-template-db` explicitly adds only
  `pdb_seqres_2022_09_28.fasta` (about 220 MB after decompression).
- The 75 GB NT-RNA, 13 GB RNAcentral, and approximately 220 MB Rfam databases
  are never fetched because this is an antibody–protein mainline, not an RNA
  pipeline.
- Template hit files and required hit mmCIF files must be prepared explicitly
  before execution. Model adapters preflight them and prevent silent upstream
  downloads.

## Configure `my_run.yaml`

[`my_run.yaml`](my_run.yaml) is a real `de_novo` starting configuration using
the paths installed by the two scripts. At minimum edit:

| Parameter | What it means |
| --- | --- |
| `run.run_id` | Unique human name used in output metadata. |
| `input.target_structure` | PDB containing the complete target assembly. |
| `chains.target` | Every target chain to preserve; do not list H/L here. |
| `design.loops` | CDRs to redesign (`H1`–`H3`, `L1`–`L3`). |
| `hotspots` | Required exposed target residues used by RFdiffusion, e.g. `A:100` or `A:102-104`. They are not passed as restraints to co-fold predictors. |
| `backbone.rfantibody.loop_lengths` | RFdiffusion CDR length/range, e.g. `H3: 5-13`. |
| `run.seeds` | Explicit random seeds shared by generators and predictors. |
| `run.samples_per_seed` | `K`; each predictor produces K structures per candidate and seed. |

The complete bilingual parameter-by-parameter reference is in
[stage contracts](docs/contracts.md#configuration-parameters).

## Commands

Before installation, developers can run from this directory with `PYTHONPATH=src`:

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
