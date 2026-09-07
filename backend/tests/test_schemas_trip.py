import json

import pytest
from pydantic import ValidationError

from app.schemas.trip import Activity, Location, Trip


def _trip_data() -> dict:
    return {
        "destination": "重庆",
        "startDate": "2026-10-01",
        "travelers": {"adults": 2, "children": 1},
        "budgetLimit": 5000,
        "days": [
            {
                "title": "城市漫游",
                "activities": [
                    {
                        "name": "洪崖洞民俗风貌区",
                        "type": "attraction",
                        "startTime": "09:30",
                        "endTime": "12:00",
                        "cost": 0,
                        "location": {
                            "name": "洪崖洞民俗风貌区",
                            "longitude": 106.578,
                            "latitude": 29.562,
                            "resolved": True,
                        },
                    },
                    {"name": "午餐·山城小汤圆", "type": "meal", "cost": 30},
                ],
            }
        ],
    }


def test_trip_accepts_camel_case_and_aliases_back():
    trip = Trip.model_validate(_trip_data())
    assert trip.destination == "重庆"
    assert trip.start_date == "2026-10-01"
    assert trip.days[0].activities[0].location.resolved is True
    dumped = trip.model_dump(by_alias=True)
    assert dumped["budgetLimit"] == 5000
    assert dumped["days"][0]["activities"][0]["startTime"] == "09:30"


def test_trip_rejects_bad_time_format():
    data = _trip_data()
    data["days"][0]["activities"][0]["startTime"] = "9点半"
    with pytest.raises(ValidationError):
        Trip.model_validate(data)


def test_location_rejects_coords_outside_china():
    with pytest.raises(ValidationError):
        Location(name="x", longitude=139.69, latitude=35.69, resolved=True)


def test_extra_fields_ignored():
    data = _trip_data()
    data["llmSays"] = "trust me"
    trip = Trip.model_validate(data)
    assert trip.destination == "重庆"


def test_trip_thinking_field_round_trips():
    data = _trip_data()
    data["thinking"] = "推理过程……"
    trip = Trip.model_validate(data)
    assert trip.thinking == "推理过程……"
    assert Trip.model_validate(trip.model_dump(by_alias=True)).thinking == "推理过程……"


def test_trip_chat_and_preferences_roundtrip():
    trip = Trip.model_validate(
        {
            "destination": "重庆",
            "preferences": "带娃、不去网红店",
            "chat": [{"role": "user", "content": "别太赶", "ts": "2026-09-07T10:00:00"}],
        }
    )
    assert trip.preferences == "带娃、不去网红店"
    assert trip.chat[0].role == "user"
    dumped = json.loads(trip.model_dump_json(by_alias=True))
    assert dumped["chat"][0]["role"] == "user"
    # 旧行程无新字段可正常解析（向后兼容）
    old = Trip.model_validate({"destination": "重庆"})
    assert old.preferences == "" and old.chat == []
