"""评分器单测（纯函数，离线）+ runner 冒烟（FakeGLM）。"""

import json

from evals.run import (
    aggregate,
    score_hallucination,
    score_outcome,
    score_params,
    score_tools,
)
from app.schemas.trip import Trip

TRIP = Trip.model_validate({
    "destination": "拉萨", "days": [
        {"title": "D1", "activities": [
            {"name": "大昭寺", "type": "attraction", "cost": 85,
             "location": {"name": "大昭寺", "resolved": True, "longitude": 91.139, "latitude": 29.652}},
        ]},
    ],
})


def _trip_with_new_coord(lon, lat, name="新地点"):
    t = TRIP.model_copy(deep=True)
    t.days[0].activities[0].location.longitude = lon
    t.days[0].activities[0].location.latitude = lat
    t.days[0].activities[0].name = name
    return t


def test_outcome_detects_days_change():
    changed = TRIP.model_copy(deep=True)
    changed.days[0].activities[0].cost = 99
    assert score_outcome({"outcome": "days_changed"}, TRIP, changed)["intent_match"] is True
    assert score_outcome({"outcome": "reply_only"}, TRIP, changed)["intent_match"] is False
    assert score_outcome({"outcome": "reply_only"}, TRIP, TRIP)["intent_match"] is True


def test_tools_whitelist_and_required():
    calls = [{"tool": "search_poi"}, {"tool": "weather"}]
    r = score_tools({"tools_allowed": ["search_poi"], "tools_required": ["search_poi"]}, calls)
    assert r["selection_ok"] is False and r["extra_tools"] == ["weather"]
    r2 = score_tools({"tools_allowed": ["search_poi", "weather"], "tools_required": ["poi_detail"]}, calls)
    assert r2["selection_ok"] is False and r2["missing_tools"] == ["poi_detail"]
    assert score_tools({"tools_allowed": None, "tools_required": []}, calls)["selection_ok"] is True


def test_params_contains_matching():
    calls = [{"tool": "search_poi", "arguments": '{"city": "拉萨", "keyword": "本地藏餐馆"}'}]
    ok = score_params({"params": [{"tool": "search_poi", "param_contains": {"keyword": "藏餐"}}]}, calls)
    assert ok["params_ok"] is True
    bad = score_params({"params": [{"tool": "search_poi", "param_contains": {"keyword": "川菜"}}]}, calls)
    assert bad["params_ok"] is False


def test_hallucination_flags_unknown_coord():
    tool_calls = [{"tool": "search_poi", "coords": [(91.15, 29.66)]}]
    # 新坐标来自工具返回 → 无幻觉
    r1 = score_hallucination(TRIP, _trip_with_new_coord(91.15, 29.66), tool_calls)
    assert r1["hallucination_count"] == 0
    # 新坐标凭空出现 → 幻觉
    r2 = score_hallucination(TRIP, _trip_with_new_coord(91.99, 29.99), tool_calls)
    assert r2["hallucination_count"] == 1
    # 原有坐标未动 → 不算新增
    r3 = score_hallucination(TRIP, TRIP, tool_calls)
    assert r3["hallucination_count"] == 0


def test_aggregate_shapes():
    from evals.run import ScenarioResult

    rs = [ScenarioResult(scenario_id="a", category="c", ok=True,
                         scores={"outcome": {"intent_match": True}, "tools": {"selection_ok": True},
                                 "params": {"params_ok": True}, "hallucination": {"hallucination_count": 0}},
                         tool_calls=[{"tool": "x", "is_error": False}], latency_s=1.0)]
    agg = aggregate(rs)
    assert agg["intent_accuracy"] == 1.0 and agg["avg_tool_calls"] == 1.0
