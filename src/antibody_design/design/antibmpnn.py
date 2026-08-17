from __future__ import annotations

from .base import AdapterPlan, CapabilityError, DesignRequest, SequenceDesigner


ANTIBMPNN_COMMIT = "7e6329ba3c317e7344c6b09add72dea2390af39a"


class AntiBMPNNAdapter(SequenceDesigner):
    """Declared optional boundary; model/checkpoint identity still needs a smoke test."""

    name = "antibmpnn"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        del request
        raise CapabilityError(
            "AntiBMPNN is optional and not integrated: confirm its model/checkpoint contract "
            f"against commit {ANTIBMPNN_COMMIT} before enabling it"
        )
