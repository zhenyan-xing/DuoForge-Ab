from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import DesignPipeline
from .prepare import PreparationError, expand_hotspots, prepare_parent, read_pdb, write_prepared_complex


def _execution_flags(command: argparse.ArgumentParser) -> None:
    mode = command.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Write real command/input plans without executing models (default).",
    )
    mode.add_argument("--execute", action="store_true", help="Execute configured external adapters.")
    command.add_argument(
        "--resume",
        action="store_true",
        help="Skip only complete jobs whose required outputs still exist; retry failed/incomplete jobs once.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="duoforge-ab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "prepare"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
    for name in ("backbone", "sequence-design", "fold", "run", "proteinmpnn", "rf2"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        _execution_flags(command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "validate":
            if config.input.input_quiver:
                target = config.input.target_structure
                assert target is not None
                residues = read_pdb(target)
                missing = [chain for chain in config.chains.target if chain not in residues]
                if missing:
                    raise PreparationError(
                        "Target chains not found: " + ", ".join(missing)
                    )
                hotspots = expand_hotspots(config, residues)
                print(
                    f"valid: mode={config.mode} parent=deferred-until-quiver-extraction "
                    f"quiver={config.input.input_quiver} hotspots={len(hotspots)}"
                )
                return 0
            parent = prepare_parent(config, execute_numbering=False)
            print(
                f"valid: mode={config.mode} parent={parent.parent_id} "
                f"heavy_length={len(parent.heavy_sequence)} "
                f"light_length={len(parent.light_sequence)} "
                f"target_chains={','.join(parent.target_chains)}"
            )
            return 0
        if args.command == "prepare":
            if config.input.input_quiver:
                raise PreparationError(
                    "input_quiver has no concrete Parent before extraction; run backbone --execute first"
                )
            parent = prepare_parent(config, execute_numbering=True)
            print(write_prepared_complex(parent, config.run.output_dir))
            return 0

        stage = None
        command = args.command
        if command == "proteinmpnn":
            print(
                "migration: 'proteinmpnn' now aliases 'sequence-design' (IgDesign + AntiFold); no ProteinMPNN/RFantibody weights are used.",
                file=sys.stderr,
            )
            stage = "sequence-design"
        elif command == "rf2":
            print(
                "migration: 'rf2' now aliases 'fold' (Protenix-v2 + OpenDDE-ABAG); RF2 is not run.",
                file=sys.stderr,
            )
            stage = "fold"
        elif command != "run":
            stage = command
        result = DesignPipeline.from_config(config).run(
            config,
            dry_run=not args.execute,
            resume=args.resume,
            only_stage=stage,
        )
        print(result.plan_path or result.manifest_path)
        return result.exit_code
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
