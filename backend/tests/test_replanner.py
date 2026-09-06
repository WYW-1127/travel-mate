from app.agent.replanner import replan_trip
from app.schemas.replan import ReplanRequest
from app.services.amap import AMapService, PoiResult
from app.services.glm import GLMService

TRIP_DATA = {
    "id": "t1",
    "title": "重庆2日游",
    "destination": "重庆",
    "version": 1,
    "travelers": {"adults": 2, "children": 1},
    "budgetLimit": 5000,
    "days": [
        {
            "title": "D1",
            "activities": [
                {"id": "a1", "name": "长江索道", "type": "attraction",
                 "startTime": "09:00", "endTime": "10:00", "cost": 20,
                 "location": {"name": "长江索道", "resolved": True,
                              "longitude": 106.58, "latitude": 29.56}},
                {"id": "a2", "name": "洪崖洞", "type": "attraction",
                 "startTime": "11:00", "endTime": "13:00", "cost": 0,
                 "location": {"name": "洪崖洞", "resolved": True,
                              "longitude": 106.58, "latitude": 29.56}},
            ],
        },
        {
            "title": "D2",
            "activities": [
                {"id": "a3", "name": "解放碑", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0,
                 "location": {"name": "解放碑", "resolved": True,
                              "longitude": 106.577, "latitude": 29.558}},
            ],
        },
    ],
}


class FakeGLM(GLMService):
    def __init__(self, responses: list):
        super().__init__(api_key="fake")
        self.responses = list(responses)
        self.users: list[str] = []

    async def chat_json_stream(self, system, user, on_thinking, temperature=0.3):
        self.users.append(user)
        on_thinking("分析受影响的天…")
        return self.responses.pop(0)


class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")

    async def search_poi(self, city, keyword):
        return PoiResult(name=keyword, address="", longitude=106.5, latitude=29.5, poi_id="P")


NEW_DAY = {
    "title": "D1-悠闲",
    "activities": [
        {"name": "山城步道", "type": "attraction", "startTime": "10:00", "endTime": "12:00", "cost": 0},
        {"name": "午餐·小面", "type": "meal", "startTime": "12:30", "endTime": "13:30", "cost": 25},
    ],
}


def _req() -> ReplanRequest:
    return ReplanRequest.model_validate(
        {"trip": TRIP_DATA, "request": "第一天别太赶，不要长江索道"}
    )


async def test_replan_replaces_only_affected_day():
    glm = FakeGLM([{"affectedDayIndexes": [0]}, NEW_DAY])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    complete = events[-1]
    assert complete.type == "complete"
    trip = complete.trip
    assert trip.version == 2
    assert trip.days[0].title == "D1-悠闲"
    assert trip.days[1].title == "D2"  # 未受影响
    assert trip.days[1].activities[0].id == "a3"  # 原 activity 原样保留
    assert trip.id == "t1"
    assert trip.days[0].activities[0].location.resolved is True


async def test_replan_assigns_ids_to_regenerated_activities():
    # 重新生成的天来自 GLM 草稿（无 id），必须补齐否则地图联动失效
    glm = FakeGLM([{"affectedDayIndexes": [0]}, NEW_DAY])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    trip = events[-1].trip
    new_ids = [a.id for a in trip.days[0].activities]
    assert all(new_ids)
    assert "a3" in [a.id for a in trip.days[1].activities]  # 未受影响天不受影响


async def test_scope_prompt_contains_trip_and_request():
    glm = FakeGLM([{"affectedDayIndexes": [0]}, NEW_DAY])
    _ = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert "长江索道" in glm.users[0]
    assert "别太赶" in glm.users[0]


async def test_empty_scope_yields_error():
    glm = FakeGLM([{"affectedDayIndexes": []}])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "error"
    assert events[-1].code == "SCOPE_EMPTY"


async def test_out_of_range_indexes_filtered():
    glm = FakeGLM([{"affectedDayIndexes": [0, 7, -1]}, NEW_DAY])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "complete"


async def test_bad_day_retried_once_then_error():
    bad_day = {
        "title": "bad",
        "activities": [
            {"name": "x", "startTime": "10:00", "endTime": "09:00", "cost": 0}
        ],
    }
    glm = FakeGLM([{"affectedDayIndexes": [0]}, bad_day, bad_day])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "error"
    assert events[-1].code == "VALIDATION_FAILED"
