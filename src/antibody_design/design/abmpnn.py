from __future__ import annotations

from .base import AdapterPlan, CapabilityError, DesignRequest, SequenceDesigner


class AbMPNNAdapter(SequenceDesigner):
    """Optional boundary retained until a specific accepted checkpoint is fixed."""

    name = "abmpnn"

    def plan(self, request: DesignRequest) -> AdapterPlan:
        del request
        raise CapabilityError(
            "AbMPNN is optional and not integrated: its accepted code revision and checkpoint "
            "identity must be fixed before this adapter can construct an executable command"
        )
