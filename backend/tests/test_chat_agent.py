import json

from app.agent.chat_agent import chat_turn
from app.schemas.chat import ChatRequest
from app.services.amap import AMapService, PoiResult
from app.services.glm import GLMError, GLMService, ToolCall, ToolRound

TRIP_DATA = {
    "id": "t1",
    "title": "杭州一日游",
    "destination": "杭州",
    "version": 1,
    "preferences": "带娃",
    "days": [
        {
            "title": "D1",
            "activities": [
                {"id": "a1", "name": "西湖风景名胜区", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0,
                 "location": {"name": "西湖风景名胜区", "resolved": True, "longitude": 120.14, "latitude": 30.24}},
            ],
        },
        {
            "title": "D2",
            "activities": [
                {"id": "a2", "name": "灵隐飞来峰景区", "type": "attraction",
                 "startTime": "09:30", "endTime": "11:30", "cost": 75,
                 "location": {"name": "灵隐飞来峰景区", "resolved": True, "longitude": 120.097, "latitude": 30.241}},
            ],
        },
    ],
}

SEARCH_CALL = ToolCall(id="call_1", name="search_poi", arguments='{"city": "杭州", "keyword": "中国茶叶博物馆"}')

GOOD_EDIT = {
    "reply": "已把第 2 天的灵隐飞来峰换成中国茶叶博物馆，时间不变",
    "days": [
        {
            "index": 1,
            "title": "茶文化",
            "activities": [
                {"name": "中国茶叶博物馆", "type": "attraction", "startTime": "09:30", "endTime": "11:30", "cost": 0,
                 "location": {"name": "中国茶叶博物馆", "resolved": True, "longitude": 120.09, "latitude": 30.22}},
            ],
        }
    ],
}


class FakeGLM(GLMService):
    """按脚本依次返回 ToolRound；记录每轮完整 messages 供断言。"""

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
    def __init__(self):
        super().__init__(key="fake")

    async def search_poi(self, city, keyword):
        return PoiResult(name=keyword, address="a", longitude=120.09, latitude=30.22, poi_id="P")


def _req(message: str = "把第 2 天的灵隐寺换成中国茶叶博物馆") -> ChatRequest:
    return ChatRequest.model_validate({"trip": TRIP_DATA, "message": message})


async def test_tool_call_round_edits_day_and_appends_chat():
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps(GOOD_EDIT, ensure_ascii=False), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]

    complete = events[-1]
    assert complete.type == "complete"
    trip = complete.trip
    assert trip.version == 2
    assert trip.days[1].activities[0].name == "中国茶叶博物馆"
    assert trip.days[1].activities[0].id  # 新活动补了唯一 id
    assert trip.days[0].activities[0].name == "西湖风景名胜区"  # 未提的天原样
    assert [m.role for m in trip.chat] == ["user", "assistant"]
    assert trip.chat[0].content == "把第 2 天的灵隐寺换成中国茶叶博物馆"
    assert any(e.type == "progress" and "定位" in e.message for e in events)
    # 工具结果以 role=tool 回传进了下一轮
    assert any(m.get("role") == "tool" for m in glm.calls[1])
    # thinking 流式透传
    assert any(e.type == "thinking" for e in events)


async def test_pure_chat_keeps_trip_untouched():
    glm = FakeGLM([
        ToolRound(content=json.dumps({"reply": "人均约 375 元", "days": []}), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req("人均要花多少钱"), glm=glm, amap=FakeAMap())]
    trip = events[-1].trip
    assert trip.version == 1
    assert trip.days[1].activities[0].name == "灵隐飞来峰景区"
    assert trip.chat[-1].content == "人均约 375 元"


async def test_invalid_days_shape_retries_with_feedback():
    bad = {"reply": "改好了", "days": [{"index": 1, "title": "x", "activities": [
        {"name": "a", "startTime": "10:00", "endTime": "09:00"}]}]}
    glm = FakeGLM([
        ToolRound(content=json.dumps(bad, ensure_ascii=False), tool_calls=[]),
        ToolRound(content=json.dumps(GOOD_EDIT, ensure_ascii=False), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "complete"
    assert len(glm.calls) == 2
    last_user = glm.calls[1][-1]
    assert last_user["role"] == "user" and "问题" in last_user["content"]


async def test_rounds_cap_appends_force_finish(monkeypatch):
    import app.agent.chat_agent as mod
    monkeypatch.setattr(mod, "MAX_ROUNDS", 2)
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps({"reply": "好", "days": []}), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "complete"
    assert any("已达上限" in m.get("content", "") for m in glm.calls[2] if m.get("role") == "user")


async def test_glm_error_yields_error_event():
    glm = FakeGLM([GLMError("GLM 连接失败")])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "error"
    assert events[-1].code == "GLM_ERROR"
