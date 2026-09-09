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


class ThinkingEvent(CamelModel):
    """GLM 思考模式输出的推理过程增量文本，仅用于前端展示。

    ts 为服务端产生时刻（epoch 毫秒）：断线重放时前端凭首个 ts 还原真实思考耗时。"""

    type: Literal["thinking"] = "thinking"
    content: str
    ts: int | None = None


class CompleteEvent(CamelModel):
    type: Literal["complete"] = "complete"
    trip: Trip


class ErrorEvent(CamelModel):
    type: Literal["error"] = "error"
    code: str
    message: str


StreamEvent = ProgressEvent | ThinkingEvent | CompleteEvent | ErrorEvent


def encode_event(event: StreamEvent) -> str:
    return f"data: {event.model_dump_json(by_alias=True)}\n\n"
