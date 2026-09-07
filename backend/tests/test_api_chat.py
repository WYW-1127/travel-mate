import pytest

from app.main import app
from app.schemas.events import CompleteEvent


@pytest.fixture(autouse=True)
def _install():
    async def fake_chat(req, glm=None, amap=None):
        yield CompleteEvent(trip=req.trip.model_copy(update={"version": 2}))

    import app.agent.chat_graph as chat_mod
    import app.api.trips as trips_api

    trips_api.chat_turn = fake_chat
    yield
    trips_api.chat_turn = chat_mod.chat_turn


async def test_chat_streams_complete(client):
    resp = await client.post(
        "/api/trips/chat",
        json={
            "trip": {"destination": "重庆", "days": [], "version": 1, "chat": []},
            "message": "别太赶",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type":"complete"' in resp.text
    assert '"version":2' in resp.text


async def test_chat_validates_body(client):
    resp = await client.post("/api/trips/chat", json={"trip": {"destination": "重庆"}, "message": ""})
    assert resp.status_code == 422


async def test_chat_wiring_import_present():
    """防回归：trips 模块必须真实 import chat_turn（源码级检查）。"""
    import inspect

    import app.api.trips as trips_api

    assert "from app.agent.chat_graph import chat_turn" in inspect.getsource(trips_api)
