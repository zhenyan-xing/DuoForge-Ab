# Antibody sequence design skeleton

This is a minimal, non-inference project skeleton for local CDR sequence redesign
of an existing antibody-antigen complex. It keeps the input backbone, framework,
and starting binding pose fixed during sequence-design preparation, preserves both
AbMPNN and IgDesign candidate streams, and plans independent Protenix-v2 and
OpenDDE-ABAG refolding.

The stage layout mirrors RFantibody's composable sequence-design then refolding
workflow, while omitting RFdiffusion because this project starts from an existing
complex. See [stage contracts](docs/contracts.md) and [open questions](docs/open_questions.md).

## What runs now

With Python 3.11+ and PyYAML installed:

```bash
cd antibody-seq-design
PYTHONPATH=src python -m antibody_design.cli validate --config configs/example.yaml
PYTHONPATH=src python -m antibody_design.cli prepare --config configs/example.yaml
PYTHONPATH=src python -m antibody_design.cli run --config configs/example.yaml --dry-run
PYTHONPATH=src python -m unittest discover -s tests -v
```

`validate` checks YAML, chain/residue references, and extracts chain sequences from
the PDB. `prepare` writes normalized metadata and an unchanged PDB copy. `run`
defaults to dry-run and writes `outputs/example_run/run_plan.json`; it executes no
external command and creates no candidate manifest.

The included `mock_complex.pdb` is synthetic test data, not an antibody example.
The unit test injects explicit mock adapters to verify candidate normalization,
within-generator deduplication, liabilities, two-predictor expansion, and manifest
serialization without model weights.

## Adapter status

- AbMPNN: command plan for official ProteinMPNN parsing, arbitrary position masks,
  and an AbMPNN checkpoint.
- IgDesign: generates an upstream-compatible YAML plan with antibody/antigen,
  light-chain, epitope, and region context.
- Protenix-v2: command plan for `protenix pred` with an explicit local checkpoint.
- OpenDDE-ABAG: command plan for `opendde pred` with an explicit ABAG checkpoint.

All four adapters are dry-run only. `--execute` fails explicitly because upstream
output parsing and version-locked integration are not implemented. Missing local
executables/checkpoints are recorded as `ready: false`; the planners do not trigger
automatic checkpoint downloads.

Expected future external dependencies are separate checkouts/installations of
ProteinMPNN plus AbMPNN weights, IgDesign plus both of its checkpoints, Protenix-v2,
and OpenDDE plus `opendde_abag.pt`. None are installed by this project.

There is intentionally no scheduler, database, Quiver implementation, AntiFold
scoring, off-target execution, or cross-model total score in v0.1.
