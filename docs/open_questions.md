# Remaining open questions

The basic modes, identity model, sampling semantics, fixed upstream revisions, Protenix-v2 CLI shape, OpenDDE architecture/checkpoint distinction, exact AntiFold mask behavior, and cross-generator deduplication are settled in code. The remaining questions require installed dependencies, real weights, or a separate scientific decision:

1. **Real-weight smoke validation.** Run one tiny authorized case for the IgDesign multi-antigen dataset path, AntiFold exact-logit runner, Protenix v2.0.0, and OpenDDE-ABAG. Confirm GPU/runtime versions, exact output layout, native metric keys, and whether `samples_per_seed` always yields K retained CIFs.
2. **Template assembly semantics.** Fixed Protenix/OpenDDE native inputs accept per-chain `.a3m`/`.hhr` template hits, not an arbitrary target-assembly PDB. Determine an upstream-supported way to preserve a known peptide–HLA–β2m internal pose without exposing the antibody–target pose. Until then, `target_structure` is provenance only and default prediction is template-free.
3. **Antibody template masking.** Validate that pre-gapped H/L template hit files fully mask every designed CDR coordinate in both predictors. A project converter should be added only after the native mapping is verified.
4. **Framework preset distribution.** `framework: auto` currently references `hu-4D5-8_Fv.pdb` inside the fixed MIT RFantibody checkout. Decide whether a future release should vendor that small preset with attribution/license text or keep the checkout dependency.
5. **Confidence-array `top1` mode.** Both upstream CLIs expose atom-confidence generation at job level. Confirm a non-destructive way to retain only model top-1 arrays while leaving upstream outputs intact.
6. **Optional sequence models.** Identify and validate an accepted AbMPNN checkpoint/version. AntiBMPNN remains a capability placeholder at its pinned commit until its exact input/output/checkpoint contract is selected.
7. **Framework-free generation.** Select a scientifically valid model for `full_backbone_de_novo`; ordinary RFdiffusion must not be relabeled as this capability.
8. **Downstream selection.** Define, with experimental evidence, any future cross-model geometry or assay selection rule. Current native scores and geometry remain separate observations.
9. **Off-target panel.** Specify WT/mutant peptide and alternative-HLA panel semantics before adding this independent prediction stage.
