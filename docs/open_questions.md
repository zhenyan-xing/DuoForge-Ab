# Decisions and open questions

## Fixed for v0.1

- No upstream repository is cloned, no checkpoint is downloaded, and no expensive
  inference is run.
- Upstream source is not vendored or modified. Each model has an independent adapter.
- The input complex, backbone, framework, and starting pose are treated as fixed.
- AbMPNN and IgDesign use equal requested generation counts; Protenix-v2 and
  OpenDDE-ABAG use equal requested prediction counts.
- Exact duplicates are removed only within each generator stream, so generator
  provenance is not lost.
- Prediction metrics remain model-specific. There is no unified score.
- The included PDB is synthetic and exists only for configuration/dry-run tests.
- JSONL is used instead of RFantibody Quiver in v0.1. A Quiver compatibility layer
  would be a later, explicit decision.

## Questions to settle before real model integration

1. Which antibody numbering scheme is authoritative (raw PDB IDs, IMGT, Chothia,
   AHo), and where is the mapping persisted?
2. Must every real input be renumbered/rechained, or must original chain IDs and
   insertion codes be preserved end to end?
3. Is the design mask a single global residue mask, or may IgDesign use a different
   region mask because its native interface is region-based?
4. For IgDesign, what exact `region_order`, zero-based sequence indices, epitope crop,
   light-chain conditioning mode, and sampling-factor product correspond to the
   requested number of final sequences?
5. Which exact AbMPNN checkpoint/version and ProteinMPNN commit are accepted, and
   should antigen chains be present as fixed structural context during sampling?
6. Should design generation be exactly N raw samples per generator or N unique,
   liability-passing candidates after deduplication?
7. What is the structure-prediction input policy: no MSA/template, paired/unpaired
   MSA, templates allowed, and are pMHC subchains always retained in full?
8. Which Protenix-v2 and OpenDDE releases/checkpoints are frozen, and which native
   output files/metrics are mandatory to parse into `raw_metrics`?
9. What counts as one prediction budget unit: seed, diffusion sample, recycle/cycle,
   or one final ranked structure? Must the two predictors have numerically identical
   seeds even though their stochastic processes differ?
10. Which sequence liabilities are hard filters versus annotations, and are checks
    applied only to mutations or to the complete variable domains?
11. What pose-consistency measurements are required after refolding (CDR RMSD,
    interface RMSD, peptide/HLA alignment, contacts, clashes), and against which
    atoms and alignment frame?
12. What output is the scientific decision object: every candidate-model replicate,
    a per-candidate bundle, or a filtered shortlist with an explicit audit trail?
