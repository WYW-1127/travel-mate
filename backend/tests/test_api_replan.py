import pytest

from app.api.trips import get_amap
from app.main import app
from app.schemas.events import CompleteEvent
from app.services.amap import AMapService

REPLANNER = "app.agent.replanner.replan_trip"



class StubAMap(AMapService):
    pass


@pytest.fixture(autouse=True)
def _install():
    async def fake_replan(req, glm=None, amap=None):
        yield CompleteEvent(trip=req.trip.model_copy(update={"version": 2}))

    import app.agent.replanner as replanner_mod
    import app.api.trips as trips_api

    trips_api.replan_trip = fake_replan
    app.dependency_overrides[get_amap] = lambda: StubAMap(key="x")
    yield
    app.dependency_overrides.clear()
    trips_api.replan_trip = replanner_mod.replan_trip


async def test_replan_streams_complete(client):
    resp = await client.post(
        "/api/trips/replan",
        json={
            "trip": {"destination": "重庆", "days": [], "version": 1},
            "request": "别太赶",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type":"complete"' in resp.text
    assert '"version":2' in resp.text


async def test_replan_validates_body(client):
    resp = await client.post("/api/trips/replan", json={"request": ""})
    assert resp.status_code == 422


async def test_replan_wiring_import_present():
    """防回归：trips 模块必须真实 import replan_trip/generate_trip（源码级检查，
    不受本文件 autouse stub 影响；缺失会在运行时 NameError 而 stub 测试无法发现）。"""
    import inspect

    import app.api.trips as trips_api

    src = inspect.getsource(trips_api)
    assert "from app.agent.replanner import replan_trip" in src
    assert "from app.agent.generation_graph import generate_trip" in src
