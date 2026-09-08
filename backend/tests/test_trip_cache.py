"""行程缓存测试：相似请求命中秒回，未命中走生成。"""

import json

import pytest

from app.schemas.events import CompleteEvent, ProgressEvent
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Trip
from app.services.gen_jobs import GenJobManager
from app.services.amap import AMapService
from app.services.glm import GLMService, ToolCall, ToolRound

REQ = GenerateRequest.model_validate(
    {"destination": "杭州", "days": 1, "preferences": "带5岁孩子； 不去网红店", "request_id": "c-1"}
)
# 偏好同义但顺序/空白不同 → 应命中同一键
REQ_SAME = GenerateRequest.model_validate(
    {"destination": "杭州", "days": 1, "preferences": "不去网红店；带5岁孩子", "request_id": "c-2"}
)
REQ_DIFF_PREF = GenerateRequest.model_validate(
    {"destination": "杭州", "days": 1, "preferences": "素食", "request_id": "c-3"}
)

GOOD_DRAFT = {
    "title": "杭州一日",
    "days": [{"title": "D1", "activities": [
        {"name": "西湖", "type": "attraction", "startTime": "09:00", "endTime": "11:00", "cost": 0,
         "location": {"name": "西湖", "resolved": True, "longitude": 120.15, "latitude": 30.24}},
    ]}],
}
SEARCH_CALL = ToolCall(id="c1", name="search_poi", arguments='{"city": "杭州", "keyword": "西湖"}')


class FakeGLM(GLMService):
    def __init__(self):
        super().__init__(api_key="fake")
        self.calls = 0

    async def chat_with_tools(self, messages, tools, on_thinking=None, temperature=0.3):
        self.calls += 1
        if on_thinking:
            on_thinking("思考")
        return ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[])


class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")

    async def resolve_admin(self, name):
        return {"city": name, "adcode": ""}

    async def search_poi(self, city, keyword):
        from app.services.amap import PoiResult

        return PoiResult(name=keyword, address="a", longitude=120.15, latitude=30.24, poi_id="P")


@pytest.fixture(autouse=True)
def _cache_tmp(tmp_path, monkeypatch):
    import app.services.trip_cache as tc

    monkeypatch.setattr(tc, "_db_path", str(tmp_path / "trip_cache.db"))
    tc.clear()
    yield
    tc.clear()


async def _drain(job):
    return [e async for e in job.subscribe()]


async def test_second_identical_request_hits_cache():
    mgr = GenJobManager()
    glm1 = FakeGLM()
    events1 = await _drain(mgr.start(REQ, glm=glm1, amap=FakeAMap()))
    assert events1[-1].type == "complete"

    glm2 = FakeGLM()
    events2 = await _drain(mgr.start(REQ_SAME, glm=glm2, amap=FakeAMap()))
    assert glm2.calls == 0  # 零模型调用
    assert events2[-1].type == "complete"
    assert events2[-1].trip.title == "杭州一日"
    assert any("相似行程" in e.message for e in events2 if e.type == "progress")
    # 思考过程也随缓存回放
    assert events2[-1].trip.thinking == "思考"


async def test_different_preferences_miss():
    mgr = GenJobManager()
    await _drain(mgr.start(REQ, glm=FakeGLM(), amap=FakeAMap()))
    glm2 = FakeGLM()
    events = await _drain(mgr.start(REQ_DIFF_PREF, glm=glm2, amap=FakeAMap()))
    assert glm2.calls > 0  # 未命中，走真实生成


async def test_cancelled_job_not_cached():
    mgr = GenJobManager()
    glm = FakeGLM()
    job = mgr.start(REQ, glm=glm, amap=FakeAMap())
    mgr.cancel(REQ.request_id)
    await _drain(job)
    # 取消的任务没有 complete → 不写缓存
    glm2 = FakeGLM()
    events = await _drain(mgr.start(REQ_SAME, glm=glm2, amap=FakeAMap()))
    assert glm2.calls > 0
