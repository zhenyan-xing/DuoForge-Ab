#!/usr/bin/env python3
"""Run pinned IgDesign with all antigen chains without modifying its checkout."""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    upstream = Path(cfg["upstream_root"])
    sys.path.insert(0, str(upstream / "src"))

    import pandas as pd
    import torch
    from pytorch_lightning import seed_everything
    from igdesign.data.datasets.pdb_antibody import PdbAntibodyDataset
    from igdesign.inference_utils import sample
    from igdesign.model_wrapper import LMDesignIFWrapper
    from igdesign.utils import safe_to_device

    seed_everything(cfg["random_seed"])
    model = LMDesignIFWrapper.load_from_checkpoint(
        cfg["lmdesign_checkpoint"], strict=False, pmpnn_path=cfg["pmpnn_checkpoint"]
    ).eval().cuda()
    dataset_cfg = {
        "pdb": Path(cfg["structure_path"]).stem,
        "pdb_path": cfg["structure_path"],
        "heavy": {"chain": cfg["heavy_chain_id"], "has_sequence": True, "has_coords": True, "sequence": None},
        "light": {"chain": cfg["light_chain_id"], "has_sequence": True, "has_coords": True, "sequence": None},
        "antigens": [
            {"chain": chain, "has_sequence": True, "has_coords": True, "sequence": None}
            for chain in cfg["antigen_chain_ids"]
        ],
        "epitopes": cfg["epitopes"],
        "num_samples": int(cfg["batch_size"]),
        "name": Path(cfg["structure_path"]).stem,
    }
    crop = "closest_continuos" if cfg["epitopes"] else "none"
    dataset = PdbAntibodyDataset([dataset_cfg], include_light_chains=True, ag_crop_method=crop)
    batch = safe_to_device([dataset[0]], model.device)
    batch = model.collate(batch, precollate=dataset.collate)
    batch["tokenized_sequences"] = batch["tokenized_sequences"].long()
    light_offset = int((batch["chain_ids"][0] == 0).sum().item())
    for region in cfg["regions"].values():
        positions = torch.LongTensor(region["positions"])
        region["positions"] = positions
        region["offset_positions"] = positions if region["chain"] == "heavy" else positions + light_offset

    frame = sample(model=model, batch=batch, cfg=cfg)
    frame[cfg["region_order"]] = frame.sampled_seq.apply(lambda value: pd.Series(value.split("|")))
    frame = frame.drop(columns=["sampled_seq"])
    output = Path(cfg["save_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    with output.with_name(output.stem + "_config.pkl").open("wb") as handle:
        pickle.dump(cfg, handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
