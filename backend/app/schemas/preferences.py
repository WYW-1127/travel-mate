from pydantic import Field

from app.schemas.trip import CamelModel


class ExtractRequest(CamelModel):
    text: str = Field(min_length=1, max_length=500)


class ExtractResult(CamelModel):
    items: list[str] = Field(default_factory=list)
