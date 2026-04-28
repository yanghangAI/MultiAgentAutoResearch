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

    1. Reviewer (design)   - some design has design.md but no design_review.md.
                             (Runs first so a rejected review doesn't sit and
                             starve while Designer queues another design.)
    2. Designer            - idea has zero APPROVED design reviews. This covers
                             the "no design.md" case and the "all designs
                             rejected" case in one rule. `Expected Designs` is
                             advisory and does not gate transitions; the
                             scheduler may use it.
    3. Builder             - some non-tainted design has APPROVED design review
                             but no implementation_summary.md and no
                             implement_failed.md.
    4. Reviewer (code)     - some design has implementation_summary.md and no
                             code_review.md. Fires per-design-presence, not
                             per-idea-completeness.
    5. Submit              - some non-tainted design has APPROVED code review
                             but no job_submitted.txt.

    Tainted designs (scope_check.fail on self) are skipped by Builder, code
    review, and Submit; Designer/design-review still proceed normally so the
    idea isn't permanently stuck. Phase 2 does not yet handle Submission
    Stale / Training Failed; those land in Phase 3 with the run loop.
    """

    designs = idea.designs

    # Rule 1: Reviewer (design mode)
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

    # Rule 2: Designer (zero approved design reviews)
    if not any(d.design_review_approved for d in designs):
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

    # Rule 4: Reviewer (code mode) — at least one design with an
    # implementation_summary.md but no code_review.md.
    if any(d.has_implementation_summary and not d.code_review_text.strip() for d in designs):
        return Action(
            role="Reviewer",
            idea_id=idea.idea_id,
            design_id=None,
            review_mode="code",
            reason=(
                f"at least one implemented design under {idea.idea_id} "
                f"awaits code review"
            ),
            spawn_message=(
                f"Read agents/Reviewer/prompt.md and act as the Reviewer "
                f"for idea_id={idea.idea_id}. Mode: code review."
            ),
        )

    # Rule 5: Submit (skip tainted)
    if any(
        d.code_review_approved
        and not d.has_job_submitted
        and not d.is_tainted
        for d in designs
    ):
        return Action.submit_implemented()

    return None


def _why_designer(idea: IdeaState) -> str:
    designs_with_md = [d for d in idea.designs if d.has_design_md]
    if not designs_with_md:
        return f"{idea.idea_id} has no design.md yet"
    return (
        f"{idea.idea_id} has {len(designs_with_md)} design(s) but zero approved reviews"
    )


def _next_design_to_build(designs: tuple[DesignState, ...]) -> DesignState | None:
    for d in designs:
        if not d.design_review_approved:
            continue
        if d.has_implementation_summary or d.has_implement_failed:
            continue
        if d.is_tainted:
            continue  # tainted — driver does not advance these
        return d
    return None
