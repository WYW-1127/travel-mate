import pytest

from app.api.trips import get_amap, get_glm
from app.main import app
from app.schemas.events import CompleteEvent, ProgressEvent
from app.services.amap import AMapService
from app.services.glm import GLMService

PLANNER = "app.agent.planner.generate_trip"


class StubGLM(GLMService):
    pass


class StubAMap(AMapService):
    pass


@pytest.fixture(autouse=True)
def _restore():
    yield
    import app.agent.planner as planner_mod
    import app.api.trips as trips_api

    trips_api.generate_trip = planner_mod.generate_trip
    app.dependency_overrides.clear()


async def test_generate_streams_sse_frames(client):
    async def fake_generate(req, glm=None, amap=None):
        yield ProgressEvent(stage="analyze", message="hi")
        yield CompleteEvent(trip={"destination": "重庆"})

    import app.api.trips as trips_api

    trips_api.generate_trip = fake_generate
    app.dependency_overrides[get_glm] = lambda: StubGLM(api_key="x")
    app.dependency_overrides[get_amap] = lambda: StubAMap(key="x")

    resp = await client.post(
        "/api/trips/generate", json={"destination": "重庆", "days": 2}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    frames = [ln for ln in resp.text.split("\n\n") if ln]
    assert frames[0].startswith("data: ")
    assert '"type":"progress"' in frames[0]
    assert '"type":"complete"' in frames[-1]


async def test_generate_wraps_internal_error(client):
    async def boom(req, glm=None, amap=None):
        yield ProgressEvent(stage="analyze", message="start")
        raise RuntimeError("意外崩溃")

    import app.api.trips as trips_api

    trips_api.generate_trip = boom
    app.dependency_overrides[get_glm] = lambda: StubGLM(api_key="x")
    app.dependency_overrides[get_amap] = lambda: StubAMap(key="x")

    resp = await client.post(
        "/api/trips/generate", json={"destination": "重庆", "days": 2}
    )
    assert resp.status_code == 200
    assert '"type":"error"' in resp.text
    assert '"code":"INTERNAL"' in resp.text


async def test_generate_validates_request(client):
    resp = await client.post("/api/trips/generate", json={"destination": "", "days": 0})
    assert resp.status_code == 422
