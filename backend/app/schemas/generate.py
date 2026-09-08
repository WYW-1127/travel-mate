from typing import Literal

from pydantic import Field

from app.schemas.trip import CamelModel, Travelers


class GenerateRequest(CamelModel):
    destination: str = Field(min_length=1, max_length=50)
    days: int = Field(ge=1, le=15)
    start_date: str | None = None
    travelers: Travelers = Travelers()
    budget_limit: float | None = Field(default=None, ge=0)
    preferences: str = Field(default="", max_length=1000)
    # AI 思考深度档位；None = 跟随服务端默认（GLM_THINKING_EFFORT）
    thinking_effort: Literal["low", "high", "off"] | None = None
    # 客户端生成的请求标识：作为生成线程 id（gen:{request_id}），断线后凭它重放领取结果
    request_id: str | None = None
