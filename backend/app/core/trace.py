"""请求级 trace：contextvar 上下文 + JSONL 落盘。

每个生成/对话请求一条记录：LLM 调用明细（模型/耗时/是否出错）与工具调用明细
（参数/结果/耗时），出口统一写 data/traces.jsonl。eval 延迟指标与线上归因共用。
"""

import json
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

from app.core.config import get_settings

_ctx: ContextVar[dict | None] = ContextVar("trace_ctx", default=None)
_file_checked = False


def start_trace(kind: str, **meta) -> None:
    _ctx.set({
        "trace_id": uuid.uuid4().hex[:12],
        "kind": kind,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta": meta,
        "llm_calls": [],
        "tool_calls": [],
        "t0": time.monotonic(),
    })


def current() -> dict | None:
    return _ctx.get()


def record_llm(model: str, elapsed_ms: float, tool_calls: int, error: str = "") -> None:
    ctx = _ctx.get()
    if ctx is not None:
        ctx["llm_calls"].append(
            {"model": model, "elapsed_ms": round(elapsed_ms), "tool_calls": tool_calls, "error": error[:200]}
        )


def record_tool(call: dict) -> None:
    ctx = _ctx.get()
    if ctx is not None:
        ctx["tool_calls"].append(call)


def finish_trace(outcome: str, **extra) -> None:
    global _file_checked
    ctx = _ctx.get()
    if ctx is None:
        return
    _ctx.set(None)
    path = get_settings().trace_file
    if not path:
        return
    try:
        if not _file_checked:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            _file_checked = True
        record = {**ctx, "latency_s": round(time.monotonic() - ctx["t0"], 2), "outcome": outcome, **extra}
        record.pop("t0", None)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # trace 失败绝不影响主流程
