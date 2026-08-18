#!/usr/bin/env python3
"""Read-only IgDesign checkpoint identity and VRAM feasibility preflight."""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import zipfile
from pathlib import Path


EXPECTED_BYTES = 11_506_422_598


def free_vram_mib() -> int | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    values = [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
    return min(values) if result.returncode == 0 and values else None


def safe_tensor_bytes(path: Path) -> tuple[int | None, str]:
    try:
        import torch
        from torch._subclasses.fake_tensor import FakeTensorMode
    except (ImportError, AttributeError) as error:
        return None, f"FakeTensor metadata unavailable: {error}"
    parameters = inspect.signature(torch.load).parameters
    if "mmap" not in parameters or "weights_only" not in parameters:
        return None, "installed torch.load lacks mmap and/or weights_only"
    try:
        with FakeTensorMode():
            payload = torch.load(path, map_location="meta", mmap=True, weights_only=True)
        state = payload.get("state_dict", payload) if isinstance(payload, dict) else payload
        tensors = state.values() if isinstance(state, dict) else ()
        total = sum(
            tensor.numel() * tensor.element_size()
            for tensor in tensors
            if hasattr(tensor, "numel") and hasattr(tensor, "element_size")
        )
        return (total or None), "FakeTensorMode + mmap + weights_only"
    except Exception as error:  # The identity checks remain valid if metadata loading is unsupported.
        return None, f"safe tensor metadata load failed: {type(error).__name__}: {error}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--activation-margin-mib", type=int, default=1536)
    args = parser.parse_args()

    path = args.checkpoint.resolve()
    size = path.stat().st_size if path.is_file() else None
    format_verified = bool(path.is_file() and zipfile.is_zipfile(path))
    tensor_bytes, metadata_method = (
        safe_tensor_bytes(path) if size == EXPECTED_BYTES and format_verified else (None, "not attempted")
    )
    free_mib = free_vram_mib()
    parameter_estimate = tensor_bytes or size
    required_mib = (
        (parameter_estimate + 1024 * 1024 - 1) // (1024 * 1024)
        + args.activation_margin_mib
        if parameter_estimate is not None
        else None
    )
    identity_verified = size == EXPECTED_BYTES and format_verified
    if not identity_verified:
        status = "invalid_asset"
        reason = "size_or_pytorch_zip_identity_failed"
        exit_code = 2
    elif free_mib is None:
        status = "resource_unknown"
        reason = "free_vram_unavailable"
        exit_code = 2
    elif required_mib is not None and required_mib > free_mib:
        status = "resource_blocked"
        reason = "insufficient_vram"
        exit_code = 3
    else:
        status = "ready"
        reason = "parameter_estimate_plus_margin_fits"
        exit_code = 0

    report = {
        "model": "igdesign",
        "checkpoint": str(path),
        "checkpoint_bytes": size,
        "expected_bytes": EXPECTED_BYTES,
        "pytorch_zip_format_verified": format_verified,
        "tensor_bytes": tensor_bytes,
        "tensor_metadata_method": metadata_method,
        "parameter_storage_estimate_bytes": parameter_estimate,
        "activation_margin_mib": args.activation_margin_mib,
        "required_vram_mib": required_mib,
        "free_vram_mib": free_mib,
        "status": status,
        "reason": reason,
        "inference_verified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

