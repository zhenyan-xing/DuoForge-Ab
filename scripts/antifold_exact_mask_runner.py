#!/usr/bin/env python3
"""Sample exact IMGT residues from pinned AntiFold per-residue logits."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    upstream = Path(cfg["upstream_root"])
    sys.path.insert(0, str(upstream))

    import pandas as pd
    import torch
    import torch.nn.functional as functional
    import antifold.esm
    from antifold.antiscripts import amino_list, get_pdbs_logits, load_IF1_checkpoint

    model, _ = antifold.esm.pretrained._load_IF1_local()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_IF1_checkpoint(model, cfg["checkpoint_path"]).eval().to(device)
    pdb_path = Path(cfg["pdb_path"])
    columns = ["pdb", "Hchain", "Lchain"] + [
        f"chain{index}" for index in range(3, 3 + len(cfg["target_chains"]))
    ]
    chains = [pdb_path.stem, cfg["heavy_chain"], cfg["light_chain"], *cfg["target_chains"]]
    context = pd.DataFrame([dict(zip(columns, chains))])
    raw_dir = Path(cfg["raw_output_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    logits = get_pdbs_logits(
        model=model,
        pdbs_csv_or_dataframe=context,
        pdb_dir=str(pdb_path.parent),
        out_dir=str(raw_dir),
        custom_chain_mode=True,
        save_flag=True,
        seed=int(cfg["seed"]),
    )[0]
    antibody = logits[logits["pdb_chain"].isin([cfg["heavy_chain"], cfg["light_chain"]])].copy()
    positions_by_chain = {
        str(chain): {str(value) for value in positions}
        for chain, positions in cfg["design_imgt_positions"].items()
    }
    selected = [
        str(position) in positions_by_chain.get(str(chain), set())
        for chain, position in zip(antibody["pdb_chain"], antibody["pdb_posins"])
    ]
    if sum(selected) != sum(len(items) for items in cfg["design_imgt_positions"].values()):
        raise ValueError("AntiFold logits do not contain every requested exact IMGT position")
    log_probs = functional.log_softmax(torch.tensor(antibody[amino_list].values), dim=1)
    temperature = float(cfg["temperature"])
    if temperature <= 0:
        raise ValueError("AntiFold sampling temperature must be positive")
    probabilities = functional.softmax(
        torch.tensor(antibody[amino_list].values) / temperature,
        dim=1,
    )
    original = antibody["pdb_res"].tolist()
    torch.manual_seed(int(cfg["seed"]))
    output = Path(cfg["output_csv"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sample_index", "heavy_sequence", "light_sequence", "score", "global_score"],
        )
        writer.writeheader()
        for sample_index in range(int(cfg["num_samples"])):
            sampled = list(original)
            chosen = torch.multinomial(probabilities[selected], 1).squeeze(-1).tolist()
            for row_index, amino_index in zip(
                [index for index, flag in enumerate(selected) if flag], chosen
            ):
                sampled[row_index] = amino_list[amino_index]
            sampled_indices = torch.tensor([amino_list.index(aa) for aa in sampled])
            losses = -log_probs[torch.arange(len(sampled)), sampled_indices]
            mask = torch.tensor(selected, dtype=torch.bool)
            heavy_length = int((antibody["pdb_chain"] == cfg["heavy_chain"]).sum())
            writer.writerow(
                {
                    "sample_index": sample_index,
                    "heavy_sequence": "".join(sampled[:heavy_length]),
                    "light_sequence": "".join(sampled[heavy_length:]),
                    "score": float(losses[mask].mean()),
                    "global_score": float(losses.mean()),
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
