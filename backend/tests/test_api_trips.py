import json

import httpx
import pytest
import respx

from app.api.trips import get_amap
from app.main import app
from app.schemas.events import CompleteEvent, ProgressEvent
from app.services.amap import AMapService, PoiResult

PLANNER = "app.agent.planner.generate_trip"



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


async def test_generate_respects_request_thinking_effort(client, monkeypatch):
    """防回归：请求级 thinking 必须生效（曾被 get_glm 单例依赖掩盖）。"""
    import app.core.config as config_mod

    monkeypatch.setenv("GLM_API_KEY", "test-key")
    config_mod.get_settings.cache_clear()

    captured: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        draft = {
            "title": "t",
            "days": [
                {
                    "title": "d1",
                    "activities": [
                        {"name": "x", "type": "attraction", "startTime": "09:00", "endTime": "10:00", "cost": 0}
                    ],
                }
            ],
        }
        frame = json.dumps(
            {"choices": [{"delta": {"content": json.dumps(draft, ensure_ascii=False)}}]}
        )
        body = "data: " + frame + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=body.encode("utf-8"))

    with respx.mock:
        respx.post("https://open.bigmodel.cn/api/paas/v4/chat/completions").mock(side_effect=capture)

        class LocalAMap(StubAMap):
            async def search_poi(self, city, keyword):
                return PoiResult(name=keyword, address="", longitude=106.5, latitude=29.5, poi_id="P")

        app.dependency_overrides[get_amap] = lambda: LocalAMap(key="x")
        resp = await client.post(
            "/api/trips/generate", json={"destination": "重庆", "days": 1, "thinking_effort": "low"}
        )
        assert resp.status_code == 200
        assert '"type":"complete"' in resp.text
        assert captured[0]["thinking"] == {"type": "enabled", "effort": "low"}

        resp2 = await client.post(
            "/api/trips/generate", json={"destination": "重庆", "days": 1, "thinking_effort": "high"}
        )
        assert captured[-1]["thinking"] == {"type": "enabled", "effort": "high"}
        assert '"type":"complete"' in resp2.text
