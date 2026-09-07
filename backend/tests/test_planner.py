import pytest
from pydantic import ValidationError

from app.agent.planner import draft_to_trip
from app.schemas.generate import GenerateRequest

REQ = GenerateRequest.model_validate(
    {"destination": "重庆", "days": 2, "preferences": "带娃"}
)

GOOD_DRAFT = {
    "title": "重庆2日游",
    "days": [
        {
            "title": "D1",
            "activities": [
                {"name": "洪崖洞民俗风貌区", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0},
                {"name": "山城小汤圆", "type": "meal",
                 "startTime": "11:30", "endTime": "12:30", "cost": 30},
            ],
        },
        {
            "title": "D2",
            "activities": [
                {"name": "解放碑步行街", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0},
            ],
        },
    ],
}


def test_draft_to_trip_merges_request_fields():
    trip = draft_to_trip(GOOD_DRAFT, REQ)
    assert trip.destination == "重庆"
    assert trip.travelers.adults == 1
    assert trip.version == 1


def test_draft_to_trip_assigns_unique_activity_ids():
    # GLM 草稿不含 id，落库前必须补齐：前端卡片 key 与地图联动依赖它
    trip = draft_to_trip(GOOD_DRAFT, REQ)
    ids = [a.id for d in trip.days for a in d.activities]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_draft_to_trip_keeps_preferences():
    trip = draft_to_trip(GOOD_DRAFT, REQ)
    assert trip.preferences == "带娃"


def test_draft_to_trip_rejects_garbage():
    with pytest.raises(ValidationError):
        draft_to_trip({"days": "不是列表"}, REQ)
