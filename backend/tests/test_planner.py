import json

import pytest
from pydantic import ValidationError

from app.agent.planner import draft_to_trip, generate_trip
from app.schemas.events import ErrorEvent
from app.schemas.generate import GenerateRequest
from app.services.amap import AMapError, AMapService, PoiResult
from app.services.glm import GLMError, GLMService

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


class FakeGLM(GLMService):
    def __init__(self, drafts: list):
        super().__init__(api_key="fake")
        self.drafts = list(drafts)
        self.calls: list[tuple[str, str]] = []

    async def chat_json_stream(self, system, user, on_thinking, temperature=0.3):
        self.calls.append((system, user))
        on_thinking("模拟思考片段一。")
        on_thinking("模拟思考片段二。")
        d = self.drafts.pop(0)
        if isinstance(d, Exception):
            raise d
        return d


class FakeAMap(AMapService):
    def __init__(self, hits: set[str] | None = None, fail: bool = False, key: str = "fake"):
        super().__init__(key=key)
        self.hits = (
            hits if hits is not None else {"洪崖洞民俗风貌区", "山城小汤圆", "解放碑步行街"}
        )
        self.fail = fail

    async def search_poi(self, city: str, keyword: str):
        if self.fail:
            raise AMapError("amap down")
        if keyword in self.hits:
            return PoiResult(name=keyword, address="a", longitude=106.5, latitude=29.5, poi_id="P")
        return None

    async def geocode(self, addr: str, city: str = ""):
        return None


async def _collect(req=REQ, glm=None, amap=None):
    return [e async for e in generate_trip(req, glm=glm, amap=amap)]


def types(events):
    return [e.type for e in events]


async def test_happy_path_progress_then_complete():
    events = await _collect(glm=FakeGLM([GOOD_DRAFT]), amap=FakeAMap())
    assert types(events)[-1] == "complete"
    stages = [e.stage for e in events if e.type == "progress"]
    assert stages[0] == "analyze"
    assert "plan" in stages and "enrich" in stages
    trip = events[-1].trip
    assert trip.destination == "重庆"
    assert trip.title == "重庆2日游"
    assert trip.days[0].activities[0].location.resolved is True


async def test_thinking_events_streamed_before_complete():
    events = await _collect(glm=FakeGLM([GOOD_DRAFT]), amap=FakeAMap())
    thinking = [e for e in events if e.type == "thinking"]
    assert [t.content for t in thinking] == ["模拟思考片段一。", "模拟思考片段二。"]
    # thinking 全部出现在 complete 之前
    assert events.index(thinking[-1]) < len(events) - 1
    assert types(events)[-1] == "complete"


async def test_unresolved_poi_kept_with_flag():
    # 1/3 未解析会触发 30% 比例熔断，故用 configured=False 的假高德只验证"保留+打标"
    amap = FakeAMap(key="", hits={"洪崖洞民俗风貌区", "解放碑步行街"})
    events = await _collect(glm=FakeGLM([GOOD_DRAFT]), amap=amap)
    complete = events[-1]
    act = complete.trip.days[0].activities[1]
    assert act.name == "山城小汤圆"
    assert act.location is not None and act.location.resolved is False


async def test_validation_failure_triggers_retry_with_feedback():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][1]["startTime"] = "09:30"  # 与第一个重叠
    glm = FakeGLM([bad, GOOD_DRAFT])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert types(events)[-1] == "complete"
    assert len(glm.calls) == 2
    assert "重叠" in glm.calls[1][1]  # 反馈进入第二次 prompt


async def test_exhausted_retries_yields_error_event():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][1]["startTime"] = "09:30"
    glm = FakeGLM([bad, bad, bad])
    events = await _collect(glm=glm, amap=FakeAMap())
    last = events[-1]
    assert isinstance(last, ErrorEvent)
    assert last.code == "VALIDATION_FAILED"
    assert len(glm.calls) == 3  # 首次 + 2 次重试


async def test_glm_error_yields_error_event():
    glm = FakeGLM([GLMError("GLM_API_KEY 未配置")])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "GLM_ERROR"


async def test_invalid_draft_shape_counts_as_failure_and_retries():
    glm = FakeGLM([{"days": "不是列表"}, GOOD_DRAFT])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert types(events)[-1] == "complete"
    assert len(glm.calls) == 2


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


def test_draft_to_trip_rejects_garbage():
    with pytest.raises(ValidationError):
        draft_to_trip({"days": "不是列表"}, REQ)
