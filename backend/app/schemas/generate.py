from pydantic import Field

from app.schemas.trip import CamelModel, Travelers


class GenerateRequest(CamelModel):
    destination: str = Field(min_length=1, max_length=50)
    days: int = Field(ge=1, le=15)
    start_date: str | None = None
    travelers: Travelers = Travelers()
    budget_limit: float | None = Field(default=None, ge=0)
    preferences: str = Field(default="", max_length=1000)
