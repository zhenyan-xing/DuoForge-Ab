#!/usr/bin/env python3
"""Read-only asset preflight. It never downloads or edits checkpoints."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opendde-checkpoint", type=Path)
    args = parser.parse_args()
    if not args.opendde_checkpoint:
        print("No asset path supplied; see models/manifest.yaml and configs/example.yaml.")
        return 0
    if not args.opendde_checkpoint.is_file():
        print(f"missing: {args.opendde_checkpoint}")
        return 2
    digest = hashlib.sha256()
    with args.opendde_checkpoint.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    expected = "5cf37441ddef2a2f148b81dd4a218ad274f996fecaf17dec901ab6cf1351713d"
    print(f"sha256={digest.hexdigest()}")
    return 0 if digest.hexdigest() == expected else 2


if __name__ == "__main__":
    raise SystemExit(main())
