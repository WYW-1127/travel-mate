import pytest

from app.main import app


@pytest.fixture(autouse=True)
def _install():
    async def fake_extract(text, glm=None):
        return ["带5岁孩子出行"]

    import app.api.preferences as prefs_api
    from app.api.preferences import extract_preferences

    prefs_api.extract_preferences = fake_extract
    yield
    prefs_api.extract_preferences = extract_preferences


async def test_extract_returns_items(client):
    resp = await client.post("/api/preferences/extract", json={"text": "带5岁孩子"})
    assert resp.status_code == 200
    assert resp.json() == {"items": ["带5岁孩子出行"]}


async def test_extract_validates_body(client):
    resp = await client.post("/api/preferences/extract", json={"text": ""})
    assert resp.status_code == 422


async def test_wiring_import_present():
    import inspect

    import app.api.preferences as prefs_api

    assert "from app.agent.preferences import extract_preferences" in inspect.getsource(prefs_api)
