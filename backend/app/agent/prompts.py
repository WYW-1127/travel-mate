import json

from app.schemas.generate import GenerateRequest
from app.schemas.trip import Trip

_REPLAN_SCOPE_SYSTEM = """你是行程调整分析器。分析用户对现有行程的修改请求，找出需要重新规划的天。
只输出 JSON：{"affectedDayIndexes": [0, 2]}
dayIndex 从 0 开始。未被提及或不受影响的天不要包含。"""


def _feedback_block(feedback: list[str]) -> str:
    if not feedback:
        return ""
    return "\n\n上一版存在以下问题，必须修复：\n" + "\n".join(f"- {f}" for f in feedback)


# 重规划逐天重生成仍走固定管线（代码定位），草稿提示词与生成 agent 的分开放置
_DRAFT_SYSTEM = """你是资深国内旅行规划师。根据用户需求输出逐日行程 JSON。
规则：
1. 只输出 JSON，不要任何解释文字。
2. 严禁输出经纬度、地址等地理坐标——定位由地图系统完成。
3. 每天 3-6 个活动（含用餐），时段用 HH:MM，同一天内不得重叠，按时间排序。
4. cost 是人均预估费用（元），免费填 0。
5. type 取值：attraction | meal | transport | hotel | shopping。
6. 考虑地点之间的合理性（同一天活动集中在相邻区域）。"""


def replan_scope_messages(trip: Trip, request: str) -> tuple[str, str]:
    days_summary = "\n".join(
        f"第{i}天（index={i}）「{d.title or '无主题'}」："
        + "、".join(a.name for a in d.activities)
        for i, d in enumerate(trip.days)
    )
    user = f"当前行程：\n{days_summary}\n\n用户调整请求：{request}"
    return _REPLAN_SCOPE_SYSTEM, user


def day_regen_messages(
    trip: Trip, day_index: int, request: str, feedback: list[str]
) -> tuple[str, str]:
    original = trip.days[day_index]
    others = "\n".join(
        f"第{i}天：{'、'.join(a.name for a in d.activities) if d.activities else d.title}"
        for i, d in enumerate(trip.days)
        if i != day_index
    )
    user = (
        f"目的地：{trip.destination}\n"
        f"其他天保持不变（供参考，避免重复安排）：\n{others or '（无）'}\n\n"
        f"需要重新规划：第 {day_index + 1} 天「{original.title}」，原内容：\n"
        f"{json.dumps([a.model_dump(by_alias=True) for a in original.activities], ensure_ascii=False)}\n\n"
        f"用户调整要求：{request}"
    )
    system = _DRAFT_SYSTEM.replace(
        "根据用户需求输出逐日行程 JSON。",
        '重新规划单独一天。只输出该天的 JSON：{"title": "...", "activities": [...]}，字段规则不变。',
    )
    return system, user + _feedback_block(feedback)
