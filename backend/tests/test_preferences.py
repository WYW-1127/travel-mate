from app.agent.preferences import extract_preferences
from app.services.glm import GLMService


class FakeGLM(GLMService):
    def __init__(self, result):
        super().__init__(api_key="fake")
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def chat_json(self, system, user, temperature=0.3):
        self.calls.append((system, user))
        return self.result


async def test_extracts_durable_preferences():
    glm = FakeGLM({"items": ["带5岁孩子出行", "不去网红店"]})
    items = await extract_preferences("带5岁孩子，不想太赶，不去网红店", glm=glm)
    assert items == ["带5岁孩子出行", "不去网红店"]
    assert "长期、可复用" in glm.calls[0][0]
    assert "带5岁孩子" in glm.calls[0][1]


async def test_garbage_and_non_string_entries_filtered():
    assert await extract_preferences("x", glm=FakeGLM({"items": "不是列表"})) == []
    assert await extract_preferences("x", glm=FakeGLM({"nope": 1})) == []
    items = await extract_preferences("x", glm=FakeGLM({"items": ["a", 123, "  ", "", "b"]}))
    assert items == ["a", "b"]


async def test_capped_at_eight_and_thirty_chars():
    raw = {"items": [f"偏好{i}" for i in range(12)] + ["x" * 50]}
    items = await extract_preferences("x", glm=FakeGLM(raw))
    assert len(items) == 8
    assert all(len(i) <= 30 for i in items)
