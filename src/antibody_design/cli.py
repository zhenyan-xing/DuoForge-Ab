from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import DesignPipeline
from .prepare import prepare_complex, write_prepared_complex


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antibody-design")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "prepare"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path, required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    mode = run.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the external command plan without executing models (default).",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Attempt adapter execution; v0.1 adapters fail explicitly until integrated.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        prepared = prepare_complex(config)
        if args.command == "validate":
            print(
                f"valid: parent={prepared.parent_id} "
                f"heavy={len(prepared.heavy_sequence)} "
                f"light={len(prepared.light_sequence)} "
                f"antigen_chains={len(prepared.antigen_sequences)}"
            )
            return 0
        if args.command == "prepare":
            path = write_prepared_complex(prepared, config.run.output_dir)
            print(path)
            return 0

        result = DesignPipeline.from_config(config).run(
            config, dry_run=not args.execute
        )
        print(result.plan_path if result.plan_path else result.manifest_path)
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
