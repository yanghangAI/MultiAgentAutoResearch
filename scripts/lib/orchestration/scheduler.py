"""Cross-idea scheduling.

Given a `RichState` (snapshot of every idea + design on disk), pick the
single next `Action` the orchestrator should take. Defaults to FIFO by
`idea_id`; a `prefer_in_flight` knob (config-driven, future) can promote
ideas that already have any work past `Not Designed`.

If no idea has actionable work, the scheduler returns the Architect action
so a new direction is proposed.
"""

from __future__ import annotations

from scripts.lib.orchestration.state import RichState, IdeaState
from scripts.lib.orchestration.transitions import Action, next_action_for_idea


def pick_next(state: RichState, *, prefer_in_flight: bool = False) -> Action:
    ordered = _order_ideas(state.ideas, prefer_in_flight=prefer_in_flight)
    for idea in ordered:
        action = next_action_for_idea(idea)
        if action is not None:
            return action
    return Action.architect()


def _order_ideas(
    ideas: tuple[IdeaState, ...], *, prefer_in_flight: bool
) -> list[IdeaState]:
    if not prefer_in_flight:
        return list(ideas)  # already sorted by idea_id from snapshot
    in_flight: list[IdeaState] = []
    fresh: list[IdeaState] = []
    for idea in ideas:
        if any(d.has_design_md for d in idea.designs):
            in_flight.append(idea)
        else:
            fresh.append(idea)
    return in_flight + fresh
