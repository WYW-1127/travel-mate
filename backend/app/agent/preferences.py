from app.services.glm import GLMService

_EXTRACT_SYSTEM = """你是旅行偏好分析器。从用户输入中抽取「长期、可复用」的旅行偏好（跨行程有效），如同行人、花费习惯、兴趣喜好、明确忌讳；过滤掉仅对本次旅行有效的一次性需求（如「这次别去太远」「明天想休息」）。
只输出 JSON：{"items": ["短句", ...]}；没有可抽取的就输出 {"items": []}。每条不超过 20 字，最多 8 条。"""


async def extract_preferences(text: str, glm: GLMService | None = None) -> list[str]:
    """从用户输入抽取长期偏好短句；GLM 输出不可信时安全降级为空列表。"""
    glm = glm or GLMService(thinking_effort="low")
    data = await glm.chat_json(_EXTRACT_SYSTEM, f"用户输入：{text}")
    items = data.get("items")
    if not isinstance(items, list):
        return []
    cleaned = [i.strip()[:30] for i in items if isinstance(i, str) and i.strip()]
    return cleaned[:8]
