"""Personas: who is asking, which verticals they can see, and which tools exist for them.

Cloud Workbench ADR-007: a Vertical user can't take action because the action tool is never bound for
that persona, not because a prompt asks the model not to. The same rule is applied to data: every
query is filtered by the caller's verticals, the way the row access policy does in Snowflake.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    name: str
    verticals: tuple  # empty means every vertical
    can_propose_actions: bool

    def sees_all_verticals(self):
        return not self.verticals

    def check_vertical(self, vertical_id):
        if not self.sees_all_verticals() and vertical_id not in self.verticals:
            raise PermissionError(f"{vertical_id} is outside your verticals ({', '.join(self.verticals)})")


PLATFORM = Persona(name="platform", verticals=(), can_propose_actions=True)


def vertical_persona(*verticals):
    """A vertical's own view: its data only, and no action tools."""
    return Persona(name="vertical", verticals=tuple(verticals), can_propose_actions=False)


def from_environment():
    """FINOPS_PERSONA=platform, or FINOPS_PERSONA=vertical with FINOPS_VERTICALS=logistics,retail."""
    if os.environ.get("FINOPS_PERSONA", "platform") == "platform":
        return PLATFORM
    verticals = [v.strip() for v in os.environ.get("FINOPS_VERTICALS", "").split(",") if v.strip()]
    if not verticals:
        raise ValueError("FINOPS_PERSONA=vertical needs FINOPS_VERTICALS")
    return vertical_persona(*verticals)
