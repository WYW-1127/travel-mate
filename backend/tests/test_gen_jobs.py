import json

import pytest


@pytest.fixture(autouse=True)
def _no_checkpoint(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB", "")
    import app.core.config as config_mod

    config_mod.get_settings.cache_clear()
    yield
    config_mod.get_settings.cache_clear()

from app.agent.generation_graph import generate_trip
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Trip
from app.services.gen_jobs import GenJobManager
from app.services.amap import AMapService
from app.services.glm import GLMService, ToolCall, ToolRound
from app.schemas.events import ErrorEvent

REQ = GenerateRequest.model_validate(
    {"destination": "重庆", "days": 1, "preferences": "带娃", "request_id": "rid-1"}
)

GOOD_DRAFT = {
    "title": "重庆一日游",
    "days": [
        {"title": "D1", "activities": [
            {"name": "洪崖洞民俗风貌区", "type": "attraction", "startTime": "09:00", "endTime": "11:00", "cost": 0,
             "location": {"name": "洪崖洞民俗风貌区", "address": "a", "longitude": 106.578, "latitude": 29.562, "resolved": True}},
        ]},
    ],
}

SEARCH_CALL = ToolCall(id="c1", name="search_poi", arguments='{"city": "重庆", "keyword": "洪崖洞民俗风貌区"}')


class FakeGLM(GLMService):
    def __init__(self, rounds: list):
        super().__init__(api_key="fake")
        self.rounds = list(rounds)

    async def chat_with_tools(self, messages, tools, on_thinking=None, temperature=0.3):
        if on_thinking:
            on_thinking("思考片段")
        r = self.rounds.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")

    async def resolve_admin(self, name):
        return {"city": name, "adcode": ""}

    async def search_poi(self, city, keyword):
        from app.services.amap import PoiResult

        return PoiResult(name=keyword, address="a", longitude=106.578, latitude=29.562, poi_id="P")


async def _drain(job):
    return [e async for e in job.subscribe()]


async def test_start_runs_job_and_buffers_events():
    mgr = GenJobManager()
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps({"title": "t", "days": GOOD_DRAFT["days"]}, ensure_ascii=False), tool_calls=[]),
    ])
    job = mgr.start(REQ, glm=glm, amap=FakeAMap())
    assert job.thread_id == "gen:rid-1"
    events = await _drain(job)
    assert events[-1].type == "complete"
    await job._task  # 等后台任务收尾（status 在 complete 发布后置位）
    assert job.status == "done"
    assert isinstance(job.events[-1].trip, Trip)
    assert job.events[-1].trip.days[0].activities[0].id  # 行程已补 id


async def test_replay_replays_all_buffered_events():
    mgr = GenJobManager()
    mgr.start(REQ, glm=FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ]), amap=FakeAMap())
    job = mgr.get("rid-1")
    # 任务已结束后再订阅（断线重连场景）：全量重放
    events = await _drain(job)
    types = [e.type for e in events]
    assert types[0] == "progress" and types[-1] == "complete"
    assert types.count("complete") == 1


async def test_cancel_publishes_error_and_blocks():
    mgr = GenJobManager()
    glm = FakeGLM([ToolRound(content="", tool_calls=[SEARCH_CALL]) for _ in range(50)])
    job = mgr.start(REQ, glm=glm, amap=FakeAMap())
    assert mgr.cancel("rid-1") is True
    events = await _drain(job)
    assert events[-1].type == "error"
    assert events[-1].code == "CANCELLED"
    assert job.status == "cancelled"


async def test_get_unknown_returns_none():
    assert GenJobManager().get("nope") is None
