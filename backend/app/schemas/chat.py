from typing import Literal

from pydantic import Field

from app.schemas.trip import CamelModel, Trip


class ChatRequest(CamelModel):
    trip: Trip
    message: str = Field(min_length=1, max_length=500)
    thinking_effort: Literal["low", "high"] | None = None
    profile: list[str] = Field(default_factory=list)  # 用户长期偏好档案（前端 localStorage）
