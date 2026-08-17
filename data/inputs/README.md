# User inputs

Place real run inputs here or point `my_run.yaml` at absolute paths.

- `target.pdb`: target structure for `de_novo`; keep every configured target chain.
- `target_<chain>.a3m`: optional precomputed, unpaired target-chain MSA.
- template `.a3m`/`.hhr` files: optional precomputed hit lists. Required hit mmCIF
  files must already be present in the predictor runtime cache before execution.

Normal config loading and pipeline execution never download these files.
