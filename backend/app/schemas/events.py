from enum import Enum
from typing import Literal

from app.schemas.trip import CamelModel, Trip


class ProgressStage(str, Enum):
    analyze = "analyze"
    plan = "plan"
    enrich = "enrich"
    validate = "validate"


class ProgressEvent(CamelModel):
    type: Literal["progress"] = "progress"
    stage: ProgressStage
    message: str


class CompleteEvent(CamelModel):
    type: Literal["complete"] = "complete"
    trip: Trip


class ErrorEvent(CamelModel):
    type: Literal["error"] = "error"
    code: str
    message: str


StreamEvent = ProgressEvent | CompleteEvent | ErrorEvent


def encode_event(event: StreamEvent) -> str:
    return f"data: {event.model_dump_json(by_alias=True)}\n\n"
