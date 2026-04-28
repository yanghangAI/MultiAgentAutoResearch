"""Per-idea transitions.

Given one `IdeaState`, return the single next `Action` the orchestrator should
take, or `None` if this idea has no work the orchestrator can advance.

Transitions are pure functions of the rich-state snapshot. Cross-idea
ordering is the scheduler's job.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.lib.orchestration.state import IdeaState, DesignState


@dataclass(frozen=True)
class Action:
    role: str  # "Architect" | "Designer" | "Reviewer" | "Builder" | "Submit" | "Idle"
    idea_id: str | None
    design_id: str | None
    review_mode: str | None  # "design" | "code" | None
    reason: str
    spawn_message: str  # what would be sent to the agent CLI; "" for Submit / Idle

    @staticmethod
    def architect() -> Action:
        return Action(
            role="Architect",
            idea_id=None,
            design_id=None,
            review_mode=None,
            reason="no idea has actionable work; propose a new direction",
            spawn_message="Read agents/Architect/prompt.md and act as the Architect.",
        )

    @staticmethod
    def submit_implemented() -> Action:
        return Action(
            role="Submit",
            idea_id=None,
            design_id=None,
            review_mode=None,
            reason="one or more designs have approved code review; submit training jobs",
            spawn_message="",
        )


def next_action_for_idea(idea: IdeaState) -> Action | None:
    """Return the highest-priority action for this idea, or None.

    Priority order (each rule checks state of designs under this idea):

    1. Designer needed     - idea has fewer designs than expected and either no
                             designs yet or the existing ones do not all have a
                             design_review.md.
    2. Reviewer (design)   - some design has design.md but no design_review.md.
    3. Builder             - some design has APPROVED design review but no
                             implementation_summary.md and no implement_failed.md.
    4. Reviewer (code)     - some design has implementation_summary.md but no
                             code_review.md.
    5. Submit              - some design has APPROVED code review but no
                             job_submitted.txt.

    If none of the above match, return None and let the scheduler decide
    whether to skip the idea or default to Architect.
    """

    designs = idea.designs

    # Rule 1: Designer
    if _needs_designer(idea):
        return Action(
            role="Designer",
            idea_id=idea.idea_id,
            design_id=None,
            review_mode=None,
            reason=_why_designer(idea),
            spawn_message=(
                f"Read agents/Designer/prompt.md and act as the Designer "
                f"for idea_id={idea.idea_id}."
            ),
        )

    # Rule 2: Reviewer (design mode)
    pending_review = [
        d for d in designs if d.has_design_md and not d.design_review_text.strip()
    ]
    if pending_review:
        return Action(
            role="Reviewer",
            idea_id=idea.idea_id,
            design_id=None,
            review_mode="design",
            reason=(
                f"{len(pending_review)} design(s) under {idea.idea_id} await design review"
            ),
            spawn_message=(
                f"Read agents/Reviewer/prompt.md and act as the Reviewer "
                f"for idea_id={idea.idea_id}. Mode: design review."
            ),
        )

    # Rule 3: Builder (per-design)
    next_build = _next_design_to_build(designs)
    if next_build is not None:
        return Action(
            role="Builder",
            idea_id=idea.idea_id,
            design_id=next_build.design_id,
            review_mode=None,
            reason=(
                f"design {next_build.idea_id}/{next_build.design_id} is approved "
                f"but not implemented"
            ),
            spawn_message=(
                f"Read agents/Builder/prompt.md and act as the Builder "
                f"for idea_id={next_build.idea_id}, design_id={next_build.design_id}."
            ),
        )

    # Rule 4: Reviewer (code mode) — once all approved designs have either
    # implementation_summary.md or implement_failed.md.
    if _ready_for_code_review(designs):
        return Action(
            role="Reviewer",
            idea_id=idea.idea_id,
            design_id=None,
            review_mode="code",
            reason=(
                f"all approved designs under {idea.idea_id} are implemented "
                f"or marked failed; ready for code review"
            ),
            spawn_message=(
                f"Read agents/Reviewer/prompt.md and act as the Reviewer "
                f"for idea_id={idea.idea_id}. Mode: code review."
            ),
        )

    # Rule 5: Submit
    if any(d.code_review_approved and not d.has_job_submitted for d in designs):
        return Action.submit_implemented()

    return None


def _needs_designer(idea: IdeaState) -> bool:
    designs_with_md = [d for d in idea.designs if d.has_design_md]
    if not designs_with_md:
        return True
    if idea.expected_designs is not None and len(designs_with_md) < idea.expected_designs:
        # More designs expected; spawn Designer to add the missing ones,
        # but only if the existing ones have all been reviewed (so Designer
        # is not racing the Reviewer).
        if all(d.design_review_text.strip() for d in designs_with_md):
            return True
    return False


def _why_designer(idea: IdeaState) -> str:
    designs_with_md = [d for d in idea.designs if d.has_design_md]
    if not designs_with_md:
        return f"{idea.idea_id} has no design.md yet"
    return (
        f"{idea.idea_id} has {len(designs_with_md)} design(s); "
        f"expected {idea.expected_designs}"
    )


def _next_design_to_build(designs: tuple[DesignState, ...]) -> DesignState | None:
    for d in designs:
        if not d.design_review_approved:
            continue
        if d.has_implementation_summary or d.has_implement_failed:
            continue
        return d
    return None


def _ready_for_code_review(designs: tuple[DesignState, ...]) -> bool:
    approved = [d for d in designs if d.design_review_approved]
    if not approved:
        return False
    # All approved designs must have either an implementation summary or be
    # marked implement-failed; and at least one must have a summary needing
    # review (not all failed); and none must already have a code review.
    if not all(d.has_implementation_summary or d.has_implement_failed for d in approved):
        return False
    if not any(d.has_implementation_summary for d in approved):
        return False
    if any(d.code_review_text.strip() for d in approved if d.has_implementation_summary):
        return False
    return True
