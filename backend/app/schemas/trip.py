from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore"
    )


class ActivityType(str, Enum):
    attraction = "attraction"
    meal = "meal"
    transport = "transport"
    hotel = "hotel"
    shopping = "shopping"


def _check_hhmm(v: str | None) -> str | None:
    if v is None:
        return v
    parts = v.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"时间必须是 HH:MM，收到 {v!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间超出范围，收到 {v!r}")
    return v


class Location(CamelModel):
    name: str
    address: str = ""
    longitude: float | None = None
    latitude: float | None = None
    amap_poi_id: str = ""
    resolved: bool = False

    @field_validator("longitude")
    @classmethod
    def _lon_in_china(cls, v: float | None) -> float | None:
        if v is not None and not 73 <= v <= 136:
            raise ValueError("经纬度必须在中国范围内（GCJ-02）")
        return v

    @field_validator("latitude")
    @classmethod
    def _lat_in_china(cls, v: float | None) -> float | None:
        if v is not None and not 3 <= v <= 54:
            raise ValueError("纬度必须在中国范围内（GCJ-02）")
        return v


class Activity(CamelModel):
    id: str = ""
    name: str
    type: ActivityType = ActivityType.attraction
    start_time: str | None = None
    end_time: str | None = None
    cost: float | None = None
    notes: str = ""
    location: Location | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def _time_ok(cls, v: str | None) -> str | None:
        return _check_hhmm(v)


class Day(CamelModel):
    title: str = ""
    activities: list[Activity] = Field(default_factory=list)


class Travelers(CamelModel):
    adults: int = Field(default=1, ge=1)
    children: int = Field(default=0, ge=0)


class ChatMessage(CamelModel):
    role: Literal["user", "assistant"]
    content: str = ""
    ts: str = ""  # ISO 本地时间，前端展示用


class Trip(CamelModel):
    id: str = ""
    title: str = ""
    destination: str
    start_date: str | None = None
    travelers: Travelers = Travelers()
    budget_limit: float | None = None
    days: list[Day] = Field(default_factory=list)
    version: int = 1
    warnings: list[str] = Field(default_factory=list)
    # 最近一次生成/重规划的 AI 思考过程（前端写入，随行程持久化）
    thinking: str = ""
    # 思考耗时毫秒（前端从首个 thinking 事件计到完成，随行程持久化）
    thinking_ms: int | None = None
    # 生成时的偏好（带娃、不去网红店），对话式修改时注入提示词
    preferences: str = ""
    # 对话历史随行程持久化（≤50 条，超出由写入方裁剪）
    chat: list[ChatMessage] = Field(default_factory=list)
