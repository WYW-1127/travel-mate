"""Agent Evaluation Runner：按 dataset.jsonl 逐场景执行并自动评分。

用法：
  python -m evals.run                     # 全量（真 GLM，走 POI 缓存省配额）
  python -m evals.run --category chat_query --limit 3
  python -m evals.run --offline           # 仅离线模式（FakeGLM 冒烟，出不了真数字，验证评分器）

产出：evals/results.json + evals/report.md（简历数字来源，禁止手工编辑）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.agent import chat_graph
from app.agent.chat_tools import ToolExecutor
from app.schemas.chat import ChatRequest
from app.schemas.trip import Trip
from app.services.amap import AMapService
from app.services.glm import GLMService

EVAL_DIR = Path(__file__).parent
SCENARIO_TIMEOUT_S = 240  # 单场景墙钟上限：防工具循环/重试环最坏路径挂死 runner
ALL_TOOLS = ["search_poi", "geocode", "poi_detail", "search_around", "weather"]


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    ok: bool
    scores: dict = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)
    latency_s: float = 0.0
    error: str = ""


class RecordingExecutor(ToolExecutor):
    """捕获实例供评分器读取 calls（生产行为完全一致）。"""

    captured: list["RecordingExecutor"] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        RecordingExecutor.captured.append(self)


# ---------------- 评分器（纯函数，单测覆盖） ----------------

def score_outcome(expect: dict, input_trip: Trip, result_trip: Trip | None) -> dict:
    """意图/结果判定：days 是否被改动。"""
    if result_trip is None:
        return {"intent_match": False, "reason": "无 complete 结果"}
    days_before = [d.model_dump() for d in input_trip.days]
    days_after = [d.model_dump() for d in result_trip.days]
    changed = days_before != days_after
    want = expect["outcome"]
    if want == "days_changed":
        ok = changed
    elif want == "reply_only":
        ok = not changed
    else:  # reply_only_or_valid / any
        ok = True
    return {"intent_match": ok, "days_changed": changed}


def score_tools(expect: dict, calls: list[dict]) -> dict:
    """工具选择：实际 ⊆ 白名单 且 ⊇ 必选。"""
    used = [c["tool"] for c in calls]
    allowed = set(expect.get("tools_allowed") or ALL_TOOLS)
    required = set(expect.get("tools_required") or [])
    extra = sorted(set(used) - allowed)
    missing = sorted(required - set(used))
    return {
        "tools_used": used,
        "selection_ok": not extra and not missing,
        "extra_tools": extra,
        "missing_tools": missing,
    }


def score_params(expect: dict, calls: list[dict]) -> dict:
    """参数准确：期望片段包含匹配（关键词级）。"""
    checks = []
    for p in expect.get("params") or []:
        tool = p["tool"]
        want = p.get("param_contains", {})
        matched = False
        for c in calls:
            if c["tool"] != tool:
                continue
            try:
                args = json.loads(c["arguments"])
            except json.JSONDecodeError:
                continue
            if all(str(v) in str(args.get(k, "")) for k, v in want.items()):
                matched = True
                break
        checks.append({"tool": tool, "want": want, "param_ok": matched})
    return {"param_checks": checks, "params_ok": all(c["param_ok"] for c in checks) if checks else None}


def score_hallucination(input_trip: Trip, result_trip: Trip | None, calls: list[dict]) -> dict:
    """幻觉率：新出现的坐标必须来自工具返回集合（容差 1e-6）。"""
    if result_trip is None:
        return {"hallucinated": [], "hallucination_count": 0}
    old_coords = {
        (a.location.longitude, a.location.latitude)
        for d in input_trip.days for a in d.activities
        if a.location and a.location.resolved and a.location.longitude is not None
    }

    def close(c1: tuple, c2: tuple) -> bool:
        return abs(c1[0] - c2[0]) < 1e-6 and abs(c1[1] - c2[1]) < 1e-6

    tool_coords: list[tuple] = []
    for c in calls:
        tool_coords.extend(tuple(xy) for xy in c.get("coords") or [])

    hallucinated = []
    for d in result_trip.days:
        for a in d.activities:
            loc = a.location
            if not (loc and loc.resolved and loc.longitude is not None):
                continue
            new = (loc.longitude, loc.latitude)
            if any(close(new, o) for o in old_coords):
                continue  # 原有活动，不算新增
            if not any(close(new, t) for t in tool_coords):
                hallucinated.append({"activity": a.name, "coord": new})
    return {"hallucinated": hallucinated, "hallucination_count": len(hallucinated)}


def aggregate(results: list[ScenarioResult]) -> dict:
    """汇总指标（简历引用的最终数字）。"""
    n = len(results)
    valid = [r for r in results if r.ok]
    total_calls = sum(len(r.tool_calls) for r in results)
    error_calls = sum(1 for r in results for c in r.tool_calls if c["is_error"])
    halluc = sum(r.scores.get("hallucination", {}).get("hallucination_count", 0) for r in results)
    new_coords = 1  # 占位避免除零：幻觉率按事件计
    latencies = sorted(r.latency_s for r in results)
    return {
        "scenarios": n,
        "scenarios_ok": len(valid),
        "intent_accuracy": round(len([r for r in valid if r.scores.get("outcome", {}).get("intent_match")]) / n, 4) if n else None,
        "tool_selection_accuracy": round(len([r for r in valid if r.scores.get("tools", {}).get("selection_ok")]) / n, 4) if n else None,
        "param_accuracy": round(
            len([r for r in valid if r.scores.get("params", {}).get("params_ok") is not False]) / n, 4) if n else None,
        "invalid_tool_call_rate": round(error_calls / total_calls, 4) if total_calls else 0,
        "tool_success_rate": round(1 - (error_calls / total_calls), 4) if total_calls else None,
        "coord_hallucination_events": halluc,
        "avg_tool_calls": round(total_calls / n, 2) if n else None,
        "latency_p50_s": latencies[len(latencies) // 2] if latencies else None,
        "latency_max_s": max(latencies) if latencies else None,
    }


# ---------------- 执行 ----------------

def load_dataset(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run_scenario(scenario: dict, glm: GLMService, amap: AMapService) -> ScenarioResult:
    fixture = json.loads((EVAL_DIR / "fixtures" / scenario["input"]["trip_fixture"]).read_text(encoding="utf-8"))
    input_trip = Trip.model_validate(fixture)
    req = ChatRequest.model_validate({
        "trip": fixture,
        "message": scenario["input"]["message"],
        "thinking_effort": scenario.get("effort", "low"),
    })
    RecordingExecutor.captured = []
    orig = chat_graph.ToolExecutor
    chat_graph.ToolExecutor = RecordingExecutor
    t0 = time.monotonic()
    result_trip: Trip | None = None
    error = ""

    async def collect():
        nonlocal result_trip, error
        async for ev in chat_graph.chat_turn(req, glm=glm, amap=amap, checkpoint_db=None):
            if ev.type == "complete":
                result_trip = ev.trip
            elif ev.type == "error":
                error = f"{ev.code}: {ev.message[:120]}"

    try:
        await asyncio.wait_for(collect(), timeout=SCENARIO_TIMEOUT_S)
    except asyncio.TimeoutError:
        error = f"TIMEOUT>{SCENARIO_TIMEOUT_S}s（工具循环/校验重试未收敛）"
    finally:
        chat_graph.ToolExecutor = orig

    calls = RecordingExecutor.captured[0].calls if RecordingExecutor.captured else []
    expect = scenario["expect"]
    scores = {
        "outcome": score_outcome(expect, input_trip, result_trip),
        "tools": score_tools(expect, calls),
        "params": score_params(expect, calls),
        "hallucination": score_hallucination(input_trip, result_trip, calls),
    }
    ok = (
        not error
        and scores["outcome"]["intent_match"]
        and scores["tools"]["selection_ok"]
        and scores["params"]["params_ok"] is not False
        and scores["hallucination"]["hallucination_count"] == 0
    )
    return ScenarioResult(
        scenario_id=scenario["id"], category=scenario["category"], ok=ok, scores=scores,
        tool_calls=calls, latency_s=round(time.monotonic() - t0, 1), error=error,
    )


def write_report(results: list[ScenarioResult], agg: dict, mode: str) -> None:
    lines = [
        "# Agent Evaluation Report",
        "",
        f"- 模式：{mode}（真 GLM）｜时间：{time.strftime('%Y-%m-%d %H:%M')}｜场景数：{agg['scenarios']}",
        "",
        "## 汇总指标",
        "",
        "| 指标 | 值 |", "|---|---|",
    ]
    label = {
        "intent_accuracy": "Intent 准确率", "tool_selection_accuracy": "工具选择准确率",
        "param_accuracy": "参数准确率（含 N/A 通过）", "invalid_tool_call_rate": "无效工具调用率",
        "tool_success_rate": "工具调用成功率", "coord_hallucination_events": "坐标幻觉事件数",
        "avg_tool_calls": "平均工具调用数", "latency_p50_s": "延迟 P50（秒）",
        "latency_max_s": "延迟最大（秒）", "scenarios_ok": "全维度通过场景",
    }
    for k, v in agg.items():
        lines.append(f"| {label.get(k, k)} | {v} |")
    lines += ["", "## 明细", "", "| 场景 | 类别 | 通过 | 工具序列 | 延迟s | 备注 |", "|---|---|---|---|---|---|"]
    for r in results:
        note = r.error or ("；".join(
            f"{k}✗" for k, v in [("intent", r.scores["outcome"]["intent_match"]),
                                  ("tools", r.scores["tools"]["selection_ok"]),
                                  ("params", r.scores["params"]["params_ok"] is not False),
                                  ("hallu", r.scores["hallucination"]["hallucination_count"] == 0)] if not v) or "✓")
        tools = ",".join(c["tool"] for c in r.tool_calls) or "-"
        lines.append(f"| {r.scenario_id} | {r.category} | {'✅' if r.ok else '❌'} | {tools} | {r.latency_s} | {note} |")
    (EVAL_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (EVAL_DIR / "results.json").write_text(
        json.dumps({"aggregate": agg, "results": [r.__dict__ for r in results]}, ensure_ascii=False, indent=1),
        encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", default=None, help="逗号分隔的指定场景")
    parser.add_argument("--effort", default="low")
    args = parser.parse_args()

    dataset = load_dataset(EVAL_DIR / "dataset.jsonl")
    if args.category:
        dataset = [s for s in dataset if s["category"] == args.category]
    if args.ids:
        want = set(args.ids.split(","))
        dataset = [s for s in dataset if s["id"] in want]
    if args.limit:
        dataset = dataset[: args.limit]
    for s in dataset:
        s.setdefault("effort", args.effort)

    glm = GLMService(thinking_effort=args.effort)
    amap = AMapService()
    results = []
    for s in dataset:
        print(f"▶ {s['id']} …", flush=True)
        r = await run_scenario(s, glm, amap)
        results.append(r)
        print(f"  {'✅' if r.ok else '❌'} {r.latency_s}s tools={[c['tool'] for c in r.tool_calls]}", flush=True)

    agg = aggregate(results)
    write_report(results, agg, mode=f"online/{args.effort}")
    print(json.dumps(agg, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
