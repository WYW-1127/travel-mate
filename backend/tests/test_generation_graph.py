import json

from app.agent.generation_graph import build_generation_graph, generate_trip
from app.schemas.generate import GenerateRequest
from app.services.amap import AMapService, PoiResult
from app.services.glm import GLMError, GLMService, ToolCall, ToolRound

REQ = GenerateRequest.model_validate({"destination": "重庆", "days": 1, "preferences": "带娃"})

SEARCH_CALL = ToolCall(id="c1", name="search_poi", arguments='{"city": "重庆", "keyword": "洪崖洞民俗风貌区"}')

GOOD_DRAFT = {
    "title": "重庆一日游",
    "days": [
        {"title": "D1", "activities": [
            {"name": "洪崖洞民俗风貌区", "type": "attraction", "startTime": "09:00", "endTime": "11:00", "cost": 0,
             "location": {"name": "洪崖洞民俗风貌区", "address": "a", "longitude": 106.578, "latitude": 29.562, "resolved": True}},
            {"name": "山城小汤圆", "type": "meal", "startTime": "11:30", "endTime": "12:30", "cost": 30,
             "location": {"name": "山城小汤圆", "address": "a", "longitude": 106.577, "latitude": 29.561, "resolved": True}},
        ]},
    ],
}


class FakeGLM(GLMService):
    def __init__(self, rounds: list):
        super().__init__(api_key="fake")
        self.rounds = list(rounds)
        self.calls: list[list[dict]] = []

    async def chat_with_tools(self, messages, tools, on_thinking=None, temperature=0.3):
        self.calls.append([dict(m) for m in messages])
        if on_thinking:
            on_thinking("思考片段")
        r = self.rounds.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeAMap(AMapService):
    def __init__(self, key="fake"):
        super().__init__(key=key)

    async def search_poi(self, city, keyword):
        return PoiResult(name=keyword, address="a", longitude=106.578, latitude=29.562, poi_id="P")


async def _collect(req=REQ, glm=None, amap=None):
    return [e async for e in generate_trip(req, glm=glm, amap=amap, checkpoint_db=None)]


async def test_tool_round_then_complete():
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    complete = events[-1]
    assert complete.type == "complete"
    trip = complete.trip
    assert trip.destination == "重庆"
    assert trip.preferences == "带娃"
    assert trip.title == "重庆一日游"
    acts = trip.days[0].activities
    assert all(a.id for a in acts)  # 补齐唯一 id
    assert acts[0].location.resolved is True
    assert acts[1].location.resolved is True
    assert any(e.type == "thinking" for e in events)
    assert any(e.type == "progress" and "定位" in e.message for e in events)
    assert any(m.get("role") == "tool" for m in glm.calls[1])


async def test_unresolved_poi_kept_with_flag():
    """定位失败的地点保留并打标；未配置高德时跳过 30% 熔断。"""
    draft = json.loads(json.dumps(GOOD_DRAFT))
    draft["days"][0]["activities"][1]["location"] = {"name": "山城小汤圆", "resolved": False}
    glm = FakeGLM([ToolRound(content=json.dumps(draft, ensure_ascii=False), tool_calls=[])])
    events = await _collect(glm=glm, amap=FakeAMap(key=""))
    complete = events[-1]
    assert complete.type == "complete"
    assert complete.trip.days[0].activities[1].location.resolved is False


async def test_validation_failure_retries_with_feedback():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][0]["endTime"] = "08:00"  # 结束早于开始
    glm = FakeGLM([
        ToolRound(content=json.dumps(bad, ensure_ascii=False), tool_calls=[]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "complete"
    assert len(glm.calls) == 2
    assert "问题" in glm.calls[1][-1]["content"]


async def test_exhausted_retries_yields_error():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][0]["endTime"] = "08:00"
    glm = FakeGLM([ToolRound(content=json.dumps(bad, ensure_ascii=False), tool_calls=[]) for _ in range(3)])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "error"
    assert events[-1].code == "VALIDATION_FAILED"


async def test_invalid_json_shape_retries():
    glm = FakeGLM([
        ToolRound(content="这不是json", tool_calls=[]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "complete"
    assert len(glm.calls) == 2


async def test_glm_error_yields_error_event():
    glm = FakeGLM([GLMError("GLM 连接失败")])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "error"
    assert events[-1].code == "GLM_ERROR"


async def test_rounds_cap_appends_force_finish(monkeypatch):
    import app.agent.generation_graph as mod
    monkeypatch.setattr(mod, "MAX_ROUNDS", 2)
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "complete"
    assert any("已达上限" in m.get("content", "") for m in glm.calls[2] if m.get("role") == "user")


def test_graph_compiles_and_mermaid_contains_nodes():
    graph = build_generation_graph()
    mermaid = graph.get_graph().draw_mermaid()
    assert "agent_call" in mermaid and "execute_tools" in mermaid and "finalize" in mermaid
