import pytest
from pydantic import ValidationError

from app.schemas.events import CompleteEvent, ErrorEvent, ProgressEvent, encode_event
from app.schemas.generate import GenerateRequest
from app.schemas.replan import ReplanRequest


def test_generate_request_defaults():
    req = GenerateRequest.model_validate({"destination": "重庆", "days": 3})
    assert req.travelers.adults == 1
    assert req.preferences == ""


def test_generate_request_rejects_zero_days():
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate({"destination": "重庆", "days": 0})


def test_replan_request_wraps_trip():
    req = ReplanRequest.model_validate(
        {"trip": {"destination": "重庆", "days": []}, "request": "别太赶"}
    )
    assert req.trip.destination == "重庆"


def test_encode_event_progress_frame():
    frame = encode_event(ProgressEvent(stage="plan", message="正在规划第 1 天"))
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert '"type":"progress"' in frame
    assert '"stage":"plan"' in frame


def test_encode_event_error_frame():
    frame = encode_event(ErrorEvent(code="GLM_ERROR", message="x"))
    assert '"type":"error"' in frame and '"code":"GLM_ERROR"' in frame


def test_encode_event_complete_contains_trip():
    frame = encode_event(CompleteEvent(trip={"destination": "重庆"}))
    assert '"type":"complete"' in frame
    assert '"destination":"重庆"' in frame
