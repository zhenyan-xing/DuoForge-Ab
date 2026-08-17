# Scripts

The launchers here are narrow bridges into pinned, separately installed upstream
repositories; they do not vendor or patch upstream code:

- `igdesign_multichain_runner.py` preserves every configured target chain while
  calling IgDesign's official model objects.
- `antifold_exact_mask_runner.py` samples only the exact shared design mask from
  AntiFold logits and requires an explicit local checkpoint.
- `check_model_assets.py` performs the optional, read-only OpenDDE checkpoint
  digest check recorded in `models/manifest.yaml`.

They are invoked by the Python adapters during `--execute`. A dry run only records
the real argv, environment, missing assets, and expected outputs.
