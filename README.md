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

The default `standard` setup installs all five model environments, and the
default asset fetch downloads all five mainline model asset groups. After these
one-time steps, ordinary use has the same high-level shape as RFantibody: edit
one YAML file, inspect the plan, and start the run with one command. DuoForge-Ab
uses its own `duoforge-ab run` CLI because it also coordinates two sequence
generators and two co-fold predictors; it does not pretend to be RFantibody's
exact command-line interface.

If the official Protenix-v2 CDN works from your region, omit
`--protenix-checkpoint`; the fetcher will use its pinned official URL. The URL
returned HTTP 403 during the 2026-08-17 audit and no official alternative mirror
was available, so the script never substitutes Protenix-v1 or a community copy.

## Staged 8 GB smoke workflow

[`configs/smoke_8ucd_crop_8gb.yaml`](configs/smoke_8ucd_crop_8gb.yaml) is the
explicit RTX 4060 8 GB compatibility smoke. It uses one GPU and the normal
blocking subprocess path, so RFantibody, AntiFold, Protenix, and OpenDDE never
occupy the GPU concurrently. Ordinary configuration loading and ordinary
`duoforge-ab run` still never download anything; network access occurs only in
the explicitly invoked setup/fetch workflow.

Inspect the complete workflow first, then execute it:

```bash
./run_smoke.sh --dry-run --root /tmp/duoforge-ab-smoke \
  --config configs/smoke_8ucd_crop_8gb.yaml --cleanup-on-success

./run_smoke.sh --execute --root /tmp/duoforge-ab-smoke \
  --config configs/smoke_8ucd_crop_8gb.yaml --cleanup-on-success
```

The equivalent manual lifecycle is:

```bash
./setup.sh --root /tmp/duoforge-ab-smoke
source /tmp/duoforge-ab-smoke/env.sh

./fetch_assets.sh --stage backbone --root /tmp/duoforge-ab-smoke
duoforge-ab backbone --config configs/smoke_8ucd_crop_8gb.yaml --execute --resume
./cleanup_assets.sh --stage backbone --root /tmp/duoforge-ab-smoke --dry-run
./cleanup_assets.sh --stage backbone --root /tmp/duoforge-ab-smoke --execute

./fetch_assets.sh --stage sequence-design --root /tmp/duoforge-ab-smoke
duoforge-ab sequence-design --config configs/smoke_8ucd_crop_8gb.yaml --execute --resume
./cleanup_assets.sh --stage sequence-design --root /tmp/duoforge-ab-smoke --execute

./fetch_assets.sh --stage fold --root /tmp/duoforge-ab-smoke
duoforge-ab fold --config configs/smoke_8ucd_crop_8gb.yaml --execute --resume
# Fold cleanup is optional and should follow only a complete validated fold.
./cleanup_assets.sh --stage fold --root /tmp/duoforge-ab-smoke --execute
```

`fetch_assets.sh --stage all` is equivalent to the default fetch behavior.
An explicitly supplied `--stage` cannot be combined with `--skip`; this avoids
ambiguous precedence. The staged asset sets are:

| Stage | Files | Published/known size |
| --- | --- | ---: |
| `backbone` | `RFdiffusion_Ab.pt` | 483,452,922 bytes (0.450 GiB) |
| `sequence-design` | IgDesign LMDesign, IgMPNN, and AntiFold `model.pt` | 12,080,035,341 bytes (11.250 GiB) |
| `fold` | official Protenix-v2 + Protenix common files; OpenDDE-ABAG + OpenDDE common files | OpenDDE part: 3,271,388,768 bytes (3.047 GiB); official Protenix total is not published |

The 20 GiB value is a per-stage **soft budget for checkpoint and model common
files only**. It excludes conda/uv environments, package caches, source trees,
prepared inputs, logs, and final outputs; those are reported separately. The
fetcher prints its known estimate before downloading and actual completed-file
usage afterward, and warns rather than silently changing the model if the soft
budget is exceeded. No large MSA, RNA, or full template database is part of this
smoke.

Cleanup is deliberately narrow. `cleanup_assets.sh` defaults to a dry run,
rejects `/`, `$HOME`, and the repository root, and removes only the exact
checkpoint/common allowlist for one stage plus matching `.part`/`.partial`
downloads. It never removes sources, environments, caches, outputs, prepared
files, logs, user input, or unknown files. Failed stages retain assets for
diagnosis.

### 8UCD crop scope and scientific limitation

The smoke target is [`examples/8ucd_crop_target_4.pdb`](examples/8ucd_crop_target_4.pdb):
chain A has 24 residues (187–210), B has 24 (186–209), and C has 27
(187–213), totaling 75 residues and 681 atoms. The complete
[`examples/8UCD.cif`](examples/8UCD.cif) is used only to audit the crop and the
experimental Fab contacts; it is never supplied as a blind predictor template.
The experimental H/L Fab contains 225 residues, so the predicted complex is
about 300 protein tokens and about 2,400 atoms. The crop retains all
experimental Fab-contact residues within 6 Å.

This is an engineering compatibility case, not a scientific-quality benchmark.
The three short STEAP1 fragments no longer have the complete trimeric/membrane
protein scaffold, so success proves checkpoint loading, forward execution,
output parsing, chain handling, and record generation only. It cannot establish
that the generated antibody or co-folded structure is physically correct.

### Smoke parameter glossary

| Parameter | 中文含义 | Meaning in this smoke |
| --- | --- | --- |
| `mode: de_novo` | 从头生成抗体骨架模式 | RFantibody creates one antibody parent around the supplied target crop. |
| `framework: auto` | 自动选择固定框架 | Uses RFantibody's pinned hu-4D5-8 Fv preset; it does not mean framework-free generation. |
| `chains.heavy/light: H/L` | 抗体重链/轻链标识 | Output antibody chains are H and L. |
| `chains.target: [A,B,C]` | 靶标链列表 | All three crop chains remain present in every stage. |
| `design.loops: [H3]` | 仅设计重链 CDR3 | Only H3 positions may change during sequence design. |
| `hotspots` | RFdiffusion/IgDesign 使用的靶点热点 | `A:201`, `B:201`, and `C:200-203`; they are not blind-fold restraints. |
| `num_designs: 1` | 骨架候选数 | Generates one RFantibody parent. |
| `diffuser_t: 20` | RFdiffusion 去噪时间步数 | Reduced from the production-oriented 50 solely to shorten the compatibility smoke; not a production-quality setting. |
| `run.seeds: [101]` | 随机种子 | One deterministic seed is shared across adapters. |
| `samples_per_seed: 1` | 每个种子、每个预测器的结构样本数 | Each enabled fold model requests exactly one structure per candidate. |
| `proposal_budget: 1` | 每个序列生成器的最大原始提案数 | Minimal one-proposal budget; raise only to 2 if exact deduplication causes a documented shortfall. |
| `save_confidence_arrays: none` | 不保存大型逐原子置信度数组 | Native scalar metrics remain, while bulky arrays are omitted. |
| `msa.mode: none` | 不使用多序列比对 | H/L and target use query information only; no MSA search or download occurs. |
| empty `templates.*_hits` | 不使用模板命中 | The complete 8UCD, original Fab, and RFdiffusion pose are not injected into blind co-folding. |
| `dtype: bf16` | bfloat16 数值类型 | OpenDDE stores many inference activations in 16-bit brain floating point to reduce VRAM; Protenix-v2 keeps its official default BF16 path. |
| `FP32` | 32 位单精度浮点 | The official IgDesign checkpoint is loaded by its upstream FP32 path; no quantization or silent precision substitution is used. |
| `N_token` | 模型序列 token 数 | Approximately 300 protein residues/tokens; pairwise work often grows roughly with `N_token²`. |
| `N_atom` | 原子数 | Approximately 2,400 predicted atoms; atom-level heads and output memory scale with this count. |
| `step: 2` | OpenDDE 扩散去噪步数 | Smoke-only reduction from the upstream default 200; validates loading/forward/output, not structural quality. |
| `cycle: 1` | OpenDDE Pairformer 循环次数 | Smoke-only reduction from the upstream default 10; likewise not a production setting. |

On an RTX 4060 8 GB, RFantibody and AntiFold are the more plausible real
inference paths; Protenix-v2 and OpenDDE must be measured. The 10.716 GiB
IgDesign LMDesign file alone exceeds total VRAM before the required 1.5 GiB
activation margin, so the 8 GB config disables IgDesign inference after a
separate official-size/format/resource preflight. Its status must be reported as
`resource_blocked`, never as successful inference; AntiFold success does not
mean both sequence generators succeeded. Use
[`configs/smoke_8ucd_crop_full.yaml`](configs/smoke_8ucd_crop_full.yaml) on a
server with at least 24 GB VRAM to attempt all adapters without changing their
identities.

Both scripts are resumable at file/environment granularity. Re-running them
reuses a checkout only when its exact commit matches, reuses complete assets,
and leaves `.part` downloads available for HTTP resume. `setup.sh` never fetches
model weights. `fetch_assets.sh` never installs code or Python packages. Normal
configuration loading and `duoforge-ab run` never access the network.

## Current status

The staged smoke above was executed on 2026-08-17/18 on an NVIDIA GeForce RTX
4060 Laptop GPU (8,188 MiB) with driver 581.29. These are compatibility results,
not quality claims:

| Component | Exact status | Real smoke evidence |
| --- | --- | --- |
| RFantibody | `complete` | One parent PDB; 304.037 s; CUDA tensors logged. Peak VRAM is unavailable because the initial per-process WSL telemetry returned no numeric value. |
| ANARCI preparation | `complete` | One Parent with complete IMGT numbering, 11 H3 designable positions, three target chains, and six expanded hotspots. |
| IgDesign | `resource_blocked` | Official 11,506,422,598-byte PyTorch ZIP verified; conservative requirement 12,510 MiB versus 6,995 MiB free. Inference was not attempted. |
| AntiFold | `complete` | One real candidate in 6.101 s; 10 mutations, all confined to the 11-position H3 mask. Peak VRAM is unavailable from the initial telemetry. |
| Protenix-v2 | `external_asset_blocked` | The official checkpoint CDN returned HTTP 403; no older model or fabricated checkpoint was substituted. |
| OpenDDE-ABAG | execution `complete`; coordinate sanity `implausible` | BF16, sample 1, step 2, cycle 1; `N_asym=5`, `N_token=302`, `N_atom=2450`, `N_msa=1`; 40.013 s job and 26.82 s model forward; one parseable mmCIF plus confidence JSON. Device-total used-memory peak was 7,495 MiB, including pre-existing GPU use. All 297 sequential CA distances fell outside 3–5 Å (median 2,235.18 Å), so the two-step output is not a chemically meaningful structure. |

The resulting run is therefore `partial_smoke`: the real backbone → AntiFold →
OpenDDE path completed and produced one parsed prediction, while IgDesign is
resource-blocked and Protenix-v2 is external-asset-blocked. Successful backbone
and sequence-design assets were cleaned after validation. Fold assets are
retained because the fold stage is only partial and can be resumed after an
official Protenix-v2 checkpoint is supplied. The deliberately reduced two-step
OpenDDE schedule validates the software path only: its native confidence scores
must not be interpreted as scientific evidence when the coordinate sanity check
fails. No normal pipeline path produces mock results or downloads assets.

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

`fetch_assets.sh` downloads every mainline model by default. To save space, pass
`--skip MODEL` more than once if needed. The option skips both the checkpoint
and that model's required common inference files; it does not remove an existing
download and it does not alter `my_run.yaml` automatically.

```bash
# Save about 10.72 GiB of checkpoints by omitting IgDesign.
./fetch_assets.sh --root /data/duoforge-ab --skip igdesign

# Example local-redesign asset set using AntiFold + OpenDDE only.
./fetch_assets.sh --root /data/duoforge-ab \
  --skip rfantibody --skip igdesign --skip protenix
```

| `--skip` value | Storage not downloaded | Required configuration change |
| --- | ---: | --- |
| `rfantibody` | 0.450 GiB checkpoint | Valid only for `mode: local_redesign`; `de_novo` requires RFdiffusion. |
| `igdesign` | 10.722 GiB across the LMDesign and IgMPNN checkpoints | Set `generators.igdesign.enabled: false`. The current adapter requires both checkpoints; an IgMPNN-only route is not implemented. |
| `antifold` | 0.528 GiB checkpoint | Set `generators.antifold.enabled: false`. |
| `protenix` | Protenix-v2 checkpoint plus its common files; exact total is not published/accessible from the audited region | Set `predictors.protenix.enabled: false`; do not also pass `--protenix-checkpoint`. |
| `opendde` | about 3.047 GiB including its checkpoint and known common files | Set `predictors.opendde.enabled: false`. |

Keep at least one enabled generator and one enabled predictor. The default
scientific comparison requires all four adapters, so selective downloads create
a deliberately reduced pipeline rather than an equivalent full run. The
20-GiB asset preflight remains conservative after skipping models; lower it
explicitly with `--min-free-gib N` when the printed asset plan justifies doing
so. `setup.sh` still installs all model environments under `standard`: skipping
an environment is not exposed because the IgDesign environment also supplies
the shared ANARCI numbering executable. Use `--profile bootstrap` only for
orchestrator development, not for real model execution.

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
