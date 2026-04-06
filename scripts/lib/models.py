from __future__ import annotations

from dataclasses import dataclass


class Status:
    NOT_DESIGNED = "Not Designed"
    DESIGNED = "Designed"
    NOT_IMPLEMENTED = "Not Implemented"
    IMPLEMENTED = "Implemented"
    SUBMITTED = "Submitted"
    TRAINING = "Training"
    DONE = "Done"


DESIGN_STATUS_ORDER = (
    Status.NOT_IMPLEMENTED,
    Status.IMPLEMENTED,
    Status.SUBMITTED,
    Status.TRAINING,
    Status.DONE,
)

IDEA_STATUS_ORDER = (
    Status.NOT_DESIGNED,
    Status.DESIGNED,
    Status.IMPLEMENTED,
    Status.TRAINING,
    Status.DONE,
)

ALLOWED_BOOTSTRAP_SOURCE_STATUSES = {
    Status.IMPLEMENTED,
    Status.SUBMITTED,
    Status.TRAINING,
    Status.DONE,
}


@dataclass(frozen=True)
class IdeaRecord:
    idea_id: str
    idea_name: str
    status: str


@dataclass(frozen=True)
class DesignRecord:
    design_id: str
    description: str
    status: str


@dataclass(frozen=True)
class ResultRecord:
    idea_id: str
    design_id: str
    epoch: str
    train_mpjpe_weighted: str
    val_mpjpe_weighted: str
