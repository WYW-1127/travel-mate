from pydantic import Field

from app.schemas.trip import CamelModel, Trip


class ReplanRequest(CamelModel):
    trip: Trip
    request: str = Field(min_length=1, max_length=2000)
